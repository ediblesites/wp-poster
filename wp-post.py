#!/usr/bin/env python3
"""
WordPress Markdown Poster
Posts markdown files with frontmatter to WordPress via REST API
"""

import warnings
warnings.filterwarnings("ignore", message="urllib3")
warnings.filterwarnings("ignore", category=DeprecationWarning)

import argparse
import base64
import glob as glob_mod
import html
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
import phpserialize
import requests
import yaml

# Use a persistent session with a browser UA so Cloudflare WAF doesn't block REST API POST requests
_session = requests.Session()
_session.headers['User-Agent'] = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
requests.get = _session.get
requests.post = _session.post
from datetime import date, datetime
import getpass

from gutenberg import GutenbergConverter


def normalize_yaml_dates(value):
    """Recursively coerce datetime.date / datetime.datetime values to ISO strings.

    yaml.safe_load() resolves unquoted ISO dates (e.g. `pricing_verified: 2026-06-07`)
    to date/datetime objects, which json.dumps() (used for the WP REST payload) cannot
    serialize. Normalizing once, right after parsing frontmatter, lets authors write
    natural unquoted dates anywhere in frontmatter. See issue #9.
    """
    if isinstance(value, dict):
        return {k: normalize_yaml_dates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_yaml_dates(v) for v in value]
    if isinstance(value, date):  # datetime is a subclass of date
        return value.isoformat()
    return value


def load_frontmatter(yaml_text):
    """Parse a frontmatter YAML block and normalize date values (issue #9)."""
    return normalize_yaml_dates(yaml.safe_load(yaml_text))


_DATE_ONLY_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_COMPACT_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def normalize_post_date(value, warn=None):
    """Coerce a frontmatter `date` to the date-time WordPress requires.

    WordPress rejects a bare `2026-06-07` with "Invalid parameter(s): date"
    - it wants a time component, though it accepts either a `T` or a space
    as the separator. A bare date is the most natural thing to write and
    the form YAML hands back, so fill in midnight rather than fail a
    publish over something we can resolve. See issue #19.

    Deliberately narrow: only unambiguous spellings are accepted. Slash
    formats are left alone because `07/06/2026` is 7 June in one country
    and 6 July in another, and guessing wrong silently backdates a post by
    a month. Anything unrecognised passes through for WordPress to reject,
    with a warning naming the forms that work.
    """
    warn = warn or (lambda m: print(f"⚠ {m}", file=sys.stderr))
    text = str(value).strip()
    if not text:
        return value

    m = _DATE_ONLY_RE.match(text) or _COMPACT_DATE_RE.match(text)
    if m:
        year, month, day = (int(p) for p in m.groups())
        try:
            return datetime(year, month, day).strftime("%Y-%m-%dT00:00:00")
        except ValueError:
            warn(f"date '{text}' is not a real calendar date; sending as-is")
            return value

    # Already carries a time, in either separator WordPress accepts.
    if re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text):
        return text

    warn(
        f"date '{text}' is not a format WordPress accepts and will likely be "
        "rejected. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS."
    )
    return value


class WordPressPost:
    def __init__(self, site_url, username, app_password,
                 callout_config=None, resolve_bookmarks=True, locale=None):
        self.site_url = site_url.rstrip('/')
        self.auth = (username, app_password)
        self.api_url = f"{self.site_url}/wp-json/wp/v2"
        self._media_source_cache = {}  # source path/URL -> (media_id, wp_source_url)
        self._current_article_scope = None  # set by post_to_wordpress for the duration of a publish
        self._callout_config = callout_config
        self._locale = locale
        self._resolve_bookmarks = resolve_bookmarks
        self._bookmark_cache = {}  # slug -> resolved dict or None
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
        
    def parse_frontmatter_only(self, filepath):
        """Parse just the frontmatter without processing content"""
        return read_frontmatter(filepath)

    def parse_markdown_file(self, filepath):
        """Parse markdown file with frontmatter and convert to Gutenberg blocks"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Split frontmatter and content
        line_offset = 0
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = load_frontmatter(parts[1])
                markdown_content = parts[2].strip()
                # Lines consumed by the frontmatter block plus blank
                # lines stripped from the body, so converter errors can
                # report file-relative line numbers.
                consumed = parts[0] + '---' + parts[1] + '---'
                leading = parts[2][:len(parts[2]) - len(parts[2].lstrip())]
                line_offset = consumed.count('\n') + leading.count('\n')
            else:
                frontmatter = {}
                markdown_content = content
        else:
            frontmatter = {}
            markdown_content = content

        # Convert markdown to Gutenberg blocks using image handler
        converter = GutenbergConverter(
            image_handler=self._handle_image,
            callout_config=self._callout_config,
            bookmark_resolver=self._resolve_bookmark if self._resolve_bookmarks else None,
            locale=self._locale,
        )
        blocks_content = converter.convert(markdown_content, line_offset=line_offset)

        return frontmatter, blocks_content

    def _handle_image(self, image_url):
        """Image handler callback for the markdown converter."""
        return self.process_image_url(image_url)

    def _resolve_bookmark(self, target):
        """Resolve a [!BOOKMARK] target to card data, or None.

        Accepts a bare slug, a /path/, or a full URL. Looks in posts
        first, then pages. Results are cached for the life of this
        instance so repeated links cost one request.
        """
        slug = self._bookmark_slug(target)
        if not slug:
            return None
        if slug in self._bookmark_cache:
            return self._bookmark_cache[slug]

        result = None
        for rest_base in ('posts', 'pages'):
            try:
                response = requests.get(
                    f"{self.api_url}/{rest_base}",
                    params={'slug': slug, '_embed': 'wp:featuredmedia'},
                    auth=self.auth,
                    timeout=15,
                )
            except requests.RequestException as e:
                # A network-level failure almost certainly repeats against
                # the same host/credentials on the next rest_base, so we
                # stop here rather than eating a second 15s timeout for no
                # benefit.
                print(f"⚠ Bookmark lookup failed for {target}: {e}", file=sys.stderr)
                break
            if response.status_code != 200:
                continue
            try:
                items = response.json()
            except ValueError:
                continue
            if not isinstance(items, list):
                print(
                    f"⚠ Bookmark lookup for {target} got an unexpected {rest_base} "
                    f"response (expected a list, got {type(items).__name__}); skipping",
                    file=sys.stderr,
                )
                continue
            if not items:
                continue
            if not isinstance(items[0], dict):
                print(
                    f"⚠ Bookmark lookup for {target} got an unexpected {rest_base} "
                    f"response (list item is {type(items[0]).__name__}, not an "
                    f"object); skipping",
                    file=sys.stderr,
                )
                continue
            # The item passed the shape gate above, but individual nested
            # fields (title/excerpt/_embedded) can still be malformed in
            # ways _bookmark_card_data tolerates by degrading that one
            # field rather than the whole item - warn_field surfaces those
            # so a misbehaving proxy/plugin is visible, without discarding
            # an otherwise-usable card over one bad field. A totally
            # unanticipated failure (a hostile dict subclass, etc.) is
            # still caught below and treated the same as a malformed
            # response: not a match for this rest_base, not a reason to
            # skip pages or leave the slug uncached.
            def warn_field(msg):
                print(f"⚠ Bookmark lookup for {target} got a malformed {rest_base} response ({msg})", file=sys.stderr)

            try:
                result = self._bookmark_card_data(items[0], warn=warn_field)
            except Exception as e:
                print(
                    f"⚠ Bookmark lookup for {target} could not parse the "
                    f"{rest_base} response ({e}); skipping",
                    file=sys.stderr,
                )
                continue
            break

        self._bookmark_cache[slug] = result
        return result

    def _warn_if_svg_stripped(self, sent_content, post):
        """Warn once if WordPress dropped the callout icons on save.

        kses strips <svg> for any user without unfiltered_html, which on
        multisite means anyone who is not a super admin. An absent or
        empty rendered field is not evidence of stripping, so stay quiet.
        """
        if '<svg' not in (sent_content or ''):
            return False
        rendered = (post.get('content') or {}).get('rendered') or ''
        if not rendered or '<svg' in rendered:
            return False
        print(
            "⚠ Callout icons were stripped by WordPress. The publishing user "
            "lacks the unfiltered_html capability, which removes <svg> from "
            "post content on save. Grant unfiltered_html to this user to keep "
            "the icons.",
            file=sys.stderr,
        )
        return True

    @staticmethod
    def _bookmark_slug(target):
        """Reduce a slug, /path/, or full URL to its final path segment.

        Case-folded, because WordPress lowercases slugs when it creates
        them: a target typed with the capitalisation of the post title
        ("/My-Post/") would otherwise miss and quietly degrade to a plain
        link card. A percent-encoded segment is left as written - WordPress
        encodes non-Latin slugs with uppercase hex (%E3%81%82), so folding
        one would turn a working lookup into a miss. See issue #21.
        """
        text = (target or '').strip()
        if not text:
            return None
        if '://' in text:
            text = urlparse(text).path
        segments = [s for s in text.split('/') if s]
        if not segments:
            return None
        slug = segments[-1]
        return slug if '%' in slug else slug.lower()

    @staticmethod
    def _bookmark_rendered_field(item, key, warn=None):
        """Read a WP REST {'rendered': ...} field, tolerating a malformed shape.

        `title` and `excerpt` are normally {'rendered': str, 'raw': str}
        objects. A field that's simply absent (not requested, stripped by
        a filter, a post type without an excerpt) is a normal partial
        response and yields '' silently. A field that's *present* but not
        that dict shape (a bare string, an explicit null, a list...) is a
        sign something is genuinely off about the response, so it's
        reported via `warn` before also falling back to ''.
        """
        if key not in item:
            return ''
        value = item[key]
        if isinstance(value, dict):
            return value.get('rendered', '') or ''
        if warn:
            warn(f"{key} is a {type(value).__name__}, not an object; treating as empty")
        return ''

    @staticmethod
    def _bookmark_featured_media(item, warn=None):
        """Extract the embedded featured-media list item, tolerating a malformed shape.

        `_embedded` (and `_embedded['wp:featuredmedia']`) being absent is
        the normal case when `_embed` wasn't honored or the post has no
        featured image - silent, no image. Either being present but not
        the expected object/list shape is warned about, then also treated
        as "no image" rather than raising.
        """
        if '_embedded' not in item:
            return []
        embedded = item['_embedded']
        if not isinstance(embedded, dict):
            if warn:
                warn(f"_embedded is a {type(embedded).__name__}, not an object; skipping featured image")
            return []
        if 'wp:featuredmedia' not in embedded:
            return []
        media = embedded['wp:featuredmedia']
        if not isinstance(media, list):
            if warn:
                warn(f"wp:featuredmedia is a {type(media).__name__}, not a list; skipping featured image")
            return []
        return media

    @staticmethod
    def _bookmark_card_data(item, warn=None):
        """Map a REST post/page object to the card fields the renderer wants."""
        excerpt = WordPressPost._bookmark_rendered_field(item, 'excerpt', warn)
        excerpt = re.sub(r'<[^>]+>', '', excerpt)
        excerpt = html.unescape(excerpt)
        excerpt = re.sub(r'\[\s*(?:…|\.\.\.)\s*\]', '', excerpt)
        excerpt = ' '.join(excerpt.split())
        if len(excerpt) > 200:
            excerpt = excerpt[:200].rsplit(' ', 1)[0] + '…'

        image_url = None
        image_id = None
        media = WordPressPost._bookmark_featured_media(item, warn)
        if media and isinstance(media[0], dict) and media[0].get('source_url'):
            image_url = media[0]['source_url']
            image_id = media[0].get('id') or item.get('featured_media')

        return {
            'title': html.unescape(WordPressPost._bookmark_rendered_field(item, 'title', warn)),
            'link': item.get('link', ''),
            'excerpt': excerpt,
            'image_url': image_url,
            'image_id': image_id,
        }

    def parse_raw_file(self, filepath):
        """Parse file with frontmatter but keep content as-is (no markdown conversion)"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Split frontmatter and content
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = load_frontmatter(parts[1])
                raw_content = parts[2].strip()
            else:
                frontmatter = {}
                raw_content = content
        else:
            frontmatter = {}
            raw_content = content

        return frontmatter, raw_content

    def process_image_url(self, image_path_or_url):
        """Process image URL - upload (or reuse existing) and return (final_url, media_id).

        For remote URLs that fail to upload, falls back to (original_url, None) so the
        post can still render with the source URL. For missing local files, returns
        (None, None), which signals the markdown converter to drop the image.
        """
        is_url = image_path_or_url.startswith(('http://', 'https://'))

        if not is_url and not os.path.exists(image_path_or_url):
            print(f"✗ Inline image file not found: {image_path_or_url}")
            return (None, None)

        media_id = self.upload_media(image_path_or_url)
        if media_id:
            cached = self._media_source_cache.get(image_path_or_url)
            if cached:
                _, source_url = cached
                return (source_url, media_id)

        if is_url:
            print(f"⚠ Failed to upload remote image, using original URL: {image_path_or_url}")
            return (image_path_or_url, None)
        print(f"✗ Failed to upload inline image: {image_path_or_url}")
        return (None, None)

    def _fetch_terms(self, url):
        """Every term at `url`, indexed by name and slug.

        Names arrive HTML-encoded ("Security &amp; Compliance") while
        frontmatter carries the plain text, so the encoded form is unescaped
        before indexing. Without that the lookup misses, the term is
        recreated, WordPress rejects the duplicate slug, and the term is
        silently dropped. See issue #17.

        Paginated: a site with more than 100 terms would otherwise lose
        everything past the first page to the same silent drop.
        """
        terms = {}
        page = 1
        while True:
            response = requests.get(
                url,
                auth=self.auth,
                params={'per_page': 100, 'page': page},
                timeout=30,
            )
            if response.status_code != 200:
                break
            try:
                batch = response.json()
            except ValueError:
                break
            if not isinstance(batch, list) or not batch:
                break
            for term in batch:
                if not isinstance(term, dict) or 'id' not in term:
                    continue
                if term.get('name'):
                    terms[html.unescape(term['name'])] = term['id']
                if term.get('slug'):
                    terms[term['slug']] = term['id']
            try:
                total_pages = int(response.headers.get('X-WP-TotalPages', 1) or 1)
            except ValueError:
                total_pages = 1
            if page >= total_pages:
                break
            page += 1
        return terms

    def _create_term(self, url, name, kind):
        """Create a term and return its id, or None if it could not be made.

        A name whose lookup missed is usually a term that already exists;
        WordPress says so with `term_exists` and includes the id, so reuse
        it rather than dropping the term. Any other failure warns instead
        of vanishing - a silently missing category is the reason issue #17
        went unnoticed.
        """
        response = requests.post(url, auth=self.auth, json={'name': name}, timeout=30)
        if response.status_code == 201:
            return response.json()['id']

        try:
            body = response.json()
        except ValueError:
            body = {}

        if body.get('code') == 'term_exists':
            data = body.get('data')
            term_id = data.get('term_id') if isinstance(data, dict) else None
            if term_id:
                return int(term_id)

        detail = body.get('message') or f"HTTP {response.status_code}"
        print(f"⚠ Could not assign {kind} '{name}': {detail}", file=sys.stderr)
        return None

    def get_categories(self):
        """Get all categories from WordPress, indexed by both name and slug"""
        return self._fetch_terms(f"{self.api_url}/categories")

    def get_tags(self):
        """Get all tags from WordPress, indexed by both name and slug"""
        return self._fetch_terms(f"{self.api_url}/tags")

    def create_category(self, name):
        """Create a new category"""
        return self._create_term(f"{self.api_url}/categories", name, 'category')

    def create_tag(self, name):
        """Create a new tag"""
        return self._create_term(f"{self.api_url}/tags", name, 'tag')


    def get_taxonomy_rest_base(self, taxonomy):
        """Get the REST API base for a taxonomy (may differ from slug)"""
        if not hasattr(self, '_taxonomy_cache'):
            self._taxonomy_cache = {}
        if taxonomy in self._taxonomy_cache:
            return self._taxonomy_cache[taxonomy]

        # Query WordPress for taxonomy info
        response = requests.get(f"{self.api_url}/taxonomies/{taxonomy}", auth=self.auth, timeout=30)
        if response.status_code == 200:
            rest_base = response.json().get('rest_base', taxonomy)
            self._taxonomy_cache[taxonomy] = rest_base
            return rest_base

        # Fallback to slug if taxonomy not found
        self._taxonomy_cache[taxonomy] = taxonomy
        return taxonomy

    def get_taxonomy_terms(self, taxonomy):
        """Get all terms for a taxonomy, indexed by both name and slug"""
        rest_base = self.get_taxonomy_rest_base(taxonomy)
        return self._fetch_terms(f"{self.api_url}/{rest_base}")

    def create_taxonomy_term(self, taxonomy, name):
        """Create a new term in a taxonomy"""
        rest_base = self.get_taxonomy_rest_base(taxonomy)
        return self._create_term(f"{self.api_url}/{rest_base}", name, taxonomy)

    def get_user_id(self, username_or_id):
        """Get user ID from username or return ID if already numeric"""
        # If it's already a number, return it
        if isinstance(username_or_id, int):
            return username_or_id
        if isinstance(username_or_id, str) and username_or_id.isdigit():
            return int(username_or_id)

        # Look up by username
        response = requests.get(
            f"{self.api_url}/users",
            auth=self.auth,
            params={'search': username_or_id},
            timeout=30
        )
        if response.status_code == 200:
            users = response.json()
            for user in users:
                if user.get('slug') == username_or_id or user.get('name') == username_or_id:
                    return user['id']
        return None

    def _writeback_frontmatter(self, filepath, post_id, post_url):
        """Write id and slug back into the file's frontmatter after a successful create."""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        if not content.startswith('---'):
            return

        parts = content.split('---', 2)
        if len(parts) < 3:
            return

        fm = load_frontmatter(parts[1]) or {}
        fm['id'] = post_id

        # Extract slug from URL: last non-empty path segment
        url_path = post_url.rstrip('/').split('/')
        if url_path:
            resolved_slug = url_path[-1]
            # Only update if it looks like a slug (not a query string like ?p=123)
            if '?' not in resolved_slug:
                fm['slug'] = resolved_slug

        new_frontmatter = yaml.dump(fm, default_flow_style=False, allow_unicode=True).rstrip()
        body = parts[2]
        new_content = f"---\n{new_frontmatter}\n---{body}"

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)

        print(f"✓ Wrote id and slug back to {filepath}")

    def link_msls_translations(self, filepath, frontmatter, post_id, verbose=False):
        """Write (and re-assert) MSLS links for a post with a translation_set.

        Runs on every publish - create and update - so a previously failed or
        drifted link write self-heals on the next run (issue #12). Returns the
        list of failed members (empty when all succeed), or None when linking
        does not apply (no translation_set / not a network project)."""
        translation_set = frontmatter.get('translation_set')
        if not translation_set:
            return

        project_root, network_config = find_network_config(filepath)
        if not project_root:
            return

        # Find which site this file belongs to by checking site content paths
        current_site_key, current_site_info = find_site_for_file(
            project_root, network_config, filepath
        )
        if not current_site_key:
            return

        # Resolve current site's locale/blog_id from the network.sites map
        # (falling back to a per-site config file when the map omits them).
        identity = resolve_site_identity(project_root, current_site_key, current_site_info)
        current_locale = identity.get('locale') or ''
        current_blog_id = identity.get('blog_id')
        if not current_locale:
            return

        siblings = find_translation_siblings(
            project_root, network_config, translation_set, current_locale
        )

        if not siblings:
            if verbose:
                print(f"[verbose] No translation siblings found for set '{translation_set}'")
            return

        current_post = {
            'locale': current_locale,
            'blog_id': current_blog_id,
            'post_id': post_id,
        }

        wp_cli_alias = network_config.get('network', {}).get('wp_cli_alias', '')
        total = len(siblings) + 1
        if verbose:
            print(f"[verbose] Writing MSLS links for {total} members")

        results = write_msls_links(wp_cli_alias, current_post, siblings)
        failures = [r for r in results if not r['ok']]
        if failures:
            print(f"✗ MSLS translation linking failed for {len(failures)}/{total} members:")
            for f in failures:
                print(f"    - {f['locale']} (post {f['post_id']}): {f['error']}")
            return failures

        print(f"✓ MSLS translation links written ({total} members)")
        return []

    def post_to_wordpress(self, filepath, draft=False, raw=False, author_context=None, verbose=False):
        """Post file to WordPress.

        Sets the per-publish article scope so all media uploaded for this
        article (featured image and inline images) are namespaced in the WP
        media library, preventing cross-article filename collisions in dedup
        lookups. The scope is cleared in finally so a failed publish doesn't
        leak state onto subsequent calls.
        """
        self._current_article_scope = self._article_scope_for(filepath)
        try:
            return self._do_post_to_wordpress(filepath, draft, raw, author_context, verbose)
        finally:
            self._current_article_scope = None

    def _do_post_to_wordpress(self, filepath, draft, raw, author_context, verbose):
        if raw:
            frontmatter, content = self.parse_raw_file(filepath)
            if verbose:
                print(f"[verbose] Parsed raw file: {filepath}")
        else:
            try:
                frontmatter, content = self.parse_markdown_file(filepath)
            except ValueError as e:
                print(f"Error: {e} in {filepath}")
                return None
            if verbose:
                print(f"[verbose] Parsed and converted markdown: {filepath}")
        
        # Determine post type and API endpoint
        post_type = frontmatter.get('post_type', 'posts')
        
        # Map common post type names to API endpoints
        if post_type in ['post', 'posts']:
            api_endpoint = 'posts'
        elif post_type in ['page', 'pages']:
            api_endpoint = 'pages'
        else:
            # Custom post type - use as-is
            api_endpoint = post_type

        if verbose:
            print(f"[verbose] Post type: {post_type} → endpoint: {api_endpoint}")

        # Require title in frontmatter
        if 'title' not in frontmatter:
            print(f"Error: No 'title' found in frontmatter of {filepath}")
            print("Please add a 'title' field to the YAML frontmatter.")
            return None

        # Prepare post data
        post_data = {
            'title': frontmatter['title'],
            'content': content,
            'status': 'draft' if draft else frontmatter.get('status', 'publish'),
            'slug': frontmatter.get('slug', ''),
            'excerpt': frontmatter.get('excerpt', ''),
        }
        
        # Handle date (already normalized to an ISO string by load_frontmatter)
        if 'date' in frontmatter:
            post_data['date'] = normalize_post_date(frontmatter['date'])

        # Handle template (for pages and hierarchical post types)
        if 'template' in frontmatter:
            post_data['template'] = frontmatter['template']

        # Handle parent (for hierarchical post types)
        if 'parent' in frontmatter:
            post_data['parent'] = frontmatter['parent']

        # Handle author (frontmatter overrides config)
        author = frontmatter.get('author', author_context)
        if author:
            author_id = self.get_user_id(author)
            if author_id:
                post_data['author'] = author_id
            else:
                print(f"⚠ Author '{author}' not found, using authenticated user")

        # Handle categories (only for posts)
        if 'categories' in frontmatter and api_endpoint == 'posts':
            existing_cats = self.get_categories()
            cat_ids = []
            for cat_name in frontmatter['categories']:
                if cat_name in existing_cats:
                    cat_ids.append(existing_cats[cat_name])
                else:
                    # Create new category
                    new_id = self.create_category(cat_name)
                    if new_id:
                        cat_ids.append(new_id)
            if cat_ids:
                post_data['categories'] = cat_ids
        
        # Handle tags (only for posts)
        if 'tags' in frontmatter and api_endpoint == 'posts':
            existing_tags = self.get_tags()
            tag_ids = []
            for tag_name in frontmatter['tags']:
                if tag_name in existing_tags:
                    tag_ids.append(existing_tags[tag_name])
                else:
                    # Create new tag
                    new_id = self.create_tag(tag_name)
                    if new_id:
                        tag_ids.append(new_id)
            if tag_ids:
                post_data['tags'] = tag_ids
        
        # Handle custom fields/meta
        if 'meta' in frontmatter:
            post_data['meta'] = frontmatter['meta']
        
        # Handle ACF fields if present
        if 'acf' in frontmatter:
            post_data['acf'] = frontmatter['acf']
        
        # Handle custom taxonomies
        if 'taxonomies' in frontmatter:
            for taxonomy, terms in frontmatter['taxonomies'].items():
                # Ensure terms is a list
                if isinstance(terms, str):
                    terms = [terms]
                
                # Get existing terms for this taxonomy
                existing_terms = self.get_taxonomy_terms(taxonomy)
                term_ids = []
                
                for term_name in terms:
                    if term_name in existing_terms:
                        term_ids.append(existing_terms[term_name])
                    else:
                        # Create new term
                        new_id = self.create_taxonomy_term(taxonomy, term_name)
                        if new_id:
                            term_ids.append(new_id)
                
                if term_ids:
                    post_data[taxonomy] = term_ids
        
        # Handle featured image (treat null/empty the same as absent)
        if frontmatter.get('featured_image'):
            media_id = self.upload_media(frontmatter['featured_image'])
            if media_id:
                post_data['featured_media'] = media_id
        
        # Create or update post
        if verbose:
            debug_data = {k: v for k, v in post_data.items() if k != 'content'}
            debug_data['content'] = f"[{len(post_data.get('content', ''))} chars]"
            print(f"[verbose] Post data: {json.dumps(debug_data, indent=2, default=str)}")

        # A bare `id:` in frontmatter loads as None; treat that as absent so
        # we don't POST to /{endpoint}/None and 404. Only a truthy id routes
        # to the update branch.
        if frontmatter.get('id'):
            # Update existing post
            url = f"{self.api_url}/{api_endpoint}/{frontmatter['id']}"
            if verbose:
                print(f"[verbose] Updating post: POST {url}")
            response = requests.post(url, auth=self.auth, json=post_data, timeout=30)
        else:
            # Create new post
            url = f"{self.api_url}/{api_endpoint}"
            if verbose:
                print(f"[verbose] Creating post: POST {url}")
            response = requests.post(url, auth=self.auth, json=post_data, timeout=30)

        if verbose:
            print(f"[verbose] Response: {response.status_code}")
        
        if response.status_code in [200, 201]:
            post = response.json()
            post_id = post['id']
            self._warn_if_svg_stripped(post_data.get('content', ''), post)

            # Handle Rank Math SEO meta via dedicated API.
            rankmath_meta = dict(frontmatter.get('rankmath', {}))
            # rankmath.schemas is a nested dict of PHP-serialised schema bodies;
            # pop it out before the scalar-meta pass so it isn't coerced into a
            # rank_math_schemas string. See issue #24.
            schemas = rankmath_meta.pop('schemas', None)
            # Warn on legacy rich-snippet keys and drop them. These fields
            # were dead code as of Rank Math ~1.0.62; the shape they wrote
            # into is no longer read by the JSON-LD renderer. See issue #24.
            _LEGACY_RANKMATH_KEYS = (
                'rich_snippet',
                'snippet_howto_type',
                'snippet_howto_name',
                'snippet_howto_desc',
            )
            for legacy_key in _LEGACY_RANKMATH_KEYS:
                if legacy_key in rankmath_meta:
                    print(
                        f"⚠ rankmath.{legacy_key} is a dead Rank Math field; "
                        f"use rankmath.schemas instead. Dropping.",
                        file=sys.stderr,
                    )
                    rankmath_meta.pop(legacy_key)
            # Reconcile rank_math_description to the excerpt so an excerpt change
            # can't leave a stale SEO description live (issue #13). An explicit
            # rankmath.description always wins; an empty/absent excerpt leaves
            # the override untouched. Under this tool's local-first model a
            # divergent wp-admin override is treated as drift and overwritten.
            excerpt = (frontmatter.get('excerpt') or '').strip()
            has_explicit_description = (
                'description' in rankmath_meta or 'rank_math_description' in rankmath_meta
            )
            if excerpt and not has_explicit_description:
                rankmath_meta['description'] = excerpt
            if rankmath_meta:
                self.update_rankmath_meta(post_id, rankmath_meta, verbose=verbose)
            # Schema write. Absent (None) or empty ({}) = no-op; populated dict
            # is written per-type via updateMeta. Failures do not fail the
            # publish; they surface through result['schema_failure'].
            schema_failure = None
            if schemas:
                schema_failure = self.update_rankmath_schemas(post_id, schemas, verbose=verbose)

            # Writeback id/slug (new posts only). Mirror the routing gate
            # above: a bare `id:` (== None) is a "new post" from routing's
            # perspective, so it needs writeback too.
            if not frontmatter.get('id'):
                self._writeback_frontmatter(filepath, post_id, post['link'])

            # MSLS translation linking runs on every publish (create + update)
            # so a failed or drifted link write self-heals on the next run
            # instead of needing manual remediation (issue #12). Cheap to skip
            # for non-translation posts: link_msls_translations early-returns
            # when there is no translation_set / network config.
            msls_failures = self.link_msls_translations(filepath, frontmatter, post_id, verbose=verbose) or []

            result = {
                'success': True,
                'id': post_id,
                'url': post['link'],
                'title': post['title']['rendered']
            }
            # The post is already live; MSLS linking failures are surfaced
            # separately so they aren't masked as a clean success (issue #11).
            if msls_failures:
                result['msls_failures'] = msls_failures
            # Same reasoning for schema-write failures (issue #24).
            if schema_failure:
                result['schema_failure'] = schema_failure
            return result
        else:
            error_msg = response.text
            # Check for author permission error
            try:
                error_data = response.json()
                if error_data.get('code') == 'rest_cannot_edit_others':
                    error_msg = f"Permission denied: cannot set author to another user. {error_data.get('message', '')}"
            except (ValueError, KeyError):
                pass
            return {
                'success': False,
                'error': error_msg,
                'status_code': response.status_code
            }
    
    def update_rankmath_meta(self, post_id, rankmath_meta, verbose=False):
        """Update Rank Math SEO meta via the Rank Math REST API.

        Args:
            post_id: WordPress post ID
            rankmath_meta: Dict with keys like title, description, focus_keyword.
                           Keys are mapped to rank_math_ prefixed meta keys.
        """
        # Map shorthand keys to full Rank Math meta keys
        meta = {}
        key_map = {
            'title': 'rank_math_title',
            'description': 'rank_math_description',
            'focus_keyword': 'rank_math_focus_keyword',
        }
        for short_key, full_key in key_map.items():
            if short_key in rankmath_meta:
                meta[full_key] = rankmath_meta[short_key]
        # Also allow passing full rank_math_ keys directly
        for k, v in rankmath_meta.items():
            if k.startswith('rank_math_'):
                meta[k] = v

        if not meta:
            return

        url = f"{self.site_url}/wp-json/rankmath/v1/updateMeta"
        payload = {
            'objectType': 'post',
            'objectID': post_id,
            'meta': meta,
        }

        if verbose:
            print(f"[verbose] Rank Math meta: POST {url}")
            print(f"[verbose] Rank Math payload: {json.dumps(payload, indent=2)}")

        try:
            resp = requests.post(url, auth=self.auth, json=payload, timeout=15)
            if resp.status_code == 200:
                print(f"✓ Rank Math SEO meta updated")
            else:
                print(f"⚠ Rank Math meta update failed: {resp.status_code} - {resp.text}")
        except requests.RequestException as e:
            print(f"⚠ Rank Math meta update error: {e}")

    def update_rankmath_schemas(self, post_id, schemas, verbose=False):
        """Write PHP-serialised rank_math_schema_<Type> meta via Rank Math updateMeta.

        Each key in `schemas` becomes a `rank_math_schema_<key>` post_meta row,
        with the value PHP-serialised so Rank Math's schema module reads it back
        into JSON-LD on render. Uses update_post_meta upsert semantics: an
        existing row for the same type is replaced. Types not listed in `schemas`
        are left alone; there is no delete-orphan pass (no REST route enumerates
        existing schema meta_ids). See issue #24.

        Args:
            post_id: WordPress post ID.
            schemas: {Type: dict} mapping. Empty dict is a no-op.

        Returns:
            None on success or when schemas is empty.
            On HTTP failure: {"status_code": int, "error": str, "types": [str]}.
            On request exception: {"error": str, "types": [str]}.
        """
        if not schemas:
            return None

        meta = {
            f"rank_math_schema_{type_name}": phpserialize.dumps(schema_body).decode("utf-8")
            for type_name, schema_body in schemas.items()
        }
        payload = {
            "objectType": "post",
            "objectID": post_id,
            "meta": meta,
        }
        url = f"{self.site_url}/wp-json/rankmath/v1/updateMeta"

        if verbose:
            print(f"[verbose] Rank Math schemas: POST {url}")
            print(f"[verbose] Types: {sorted(schemas.keys())}")

        types = sorted(schemas.keys())
        try:
            resp = requests.post(url, auth=self.auth, json=payload, timeout=15)
            if resp.status_code == 200:
                print(f"✓ Rank Math schemas written: {', '.join(types)}")
                return None
            print(
                f"⚠ Rank Math schema write failed: {resp.status_code} - {resp.text}",
                file=sys.stderr,
            )
            return {
                "status_code": resp.status_code,
                "error": resp.text,
                "types": types,
            }
        except requests.RequestException as e:
            print(f"⚠ Rank Math schema write error: {e}", file=sys.stderr)
            return {"error": str(e), "types": types}

    def _article_scope_for(self, filepath):
        """Derive a stable, per-article scope from a markdown filepath.

        Used as a filename prefix on uploads so that multiple articles which
        ship images with the same basename (e.g. each article's own hero.webp
        and body-1.webp) do not collide in the WP media library and don't
        false-positive each other in find_existing_media lookups.

        Strategy:
          1. Use the parent directory basename if it exists and isn't generic.
          2. Otherwise fall back to the markdown filename stem.
          3. Sanitize to slug form (lowercase, hyphens).

        Returns None if no usable scope can be derived.
        """
        if not filepath:
            return None
        abs_path = os.path.abspath(filepath)
        parent_dir = os.path.basename(os.path.dirname(abs_path))
        if parent_dir and parent_dir not in ('', '.', '/'):
            scope_raw = parent_dir
        else:
            scope_raw = os.path.splitext(os.path.basename(abs_path))[0]
        scope = re.sub(r'[^a-z0-9]+', '-', scope_raw.lower()).strip('-')
        return scope or None

    def _is_same_host_url(self, value):
        """True if value is an http(s) URL whose host matches the target site."""
        if not value.startswith(('http://', 'https://')):
            return False
        return urlparse(value).netloc.lower() == urlparse(self.site_url).netloc.lower()

    def resolve_local_attachment(self, url):
        """Resolve an image URL already hosted on the target site to its attachment.

        Returns (id, source_url) when an attachment's source_url matches the given
        URL exactly, else None. Matching is exact (not by basename) so a different
        image sharing the same basename at another upload path is not aliased.
        """
        filename = os.path.basename(urlparse(url).path)
        base = os.path.splitext(filename)[0]
        slug_base = re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-')
        if not slug_base:
            return None
        try:
            response = requests.get(
                f"{self.api_url}/media",
                auth=self.auth,
                params={'slug': slug_base, 'per_page': 10},
                timeout=30,
            )
            if response.status_code != 200:
                return None
            for item in response.json():
                if item.get('source_url', '') == url:
                    return (item['id'], item['source_url'])
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"⚠ Error resolving local attachment for {url}: {e}")
        return None

    def find_existing_media(self, filename):
        """Look up existing media by filename. Returns (id, source_url) or None.

        Queries WordPress by attachment slug (which is derived from the filename
        without extension via sanitize_title). Verifies that a candidate's
        source_url ends with the exact requested filename so that slug collisions
        across different file extensions are not treated as matches.
        """
        base = os.path.splitext(filename)[0]
        slug_base = re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-')
        if not slug_base:
            return None
        try:
            response = requests.get(
                f"{self.api_url}/media",
                auth=self.auth,
                params={'slug': slug_base, 'per_page': 10},
                timeout=30,
            )
            if response.status_code != 200:
                return None
            for item in response.json():
                source_url = item.get('source_url', '')
                if source_url.rsplit('/', 1)[-1].lower() == filename.lower():
                    return (item['id'], source_url)
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"⚠ Error querying existing media for {filename}: {e}")
        return None

    def upload_media(self, filepath_or_url):
        """Upload media to WordPress, deduping against the existing media library.

        When an article scope is set (post_to_wordpress sets it from the markdown
        file's parent directory), the upload target filename is prefixed with
        the scope to keep each article's images namespaced. This prevents
        cross-article false positives in dedup queries when multiple articles
        ship images with the same basename (e.g. hero.webp).

        Order of operations:
          1. In-run cache by source path/URL (avoids duplicate work in one run).
          2. Compute the scoped target filename for this upload.
          3. Pre-upload lookup via find_existing_media against the target
             filename (avoids re-creating attachments on republish).
          4. Actual upload via the file/URL helper, using the target filename
             in Content-Disposition.

        Returns the media id or None on failure.
        """
        cached = self._media_source_cache.get(filepath_or_url)
        if cached:
            return cached[0]

        # If the source already points at the target site, reuse the existing
        # attachment instead of re-downloading and re-uploading it (issue #10).
        # Falls through to the normal upload path when no attachment matches.
        if self._is_same_host_url(filepath_or_url):
            resolved = self.resolve_local_attachment(filepath_or_url)
            if resolved:
                media_id, source_url = resolved
                print(f"✓ Reusing existing media on this site: {source_url} (id={media_id})")
                self._media_source_cache[filepath_or_url] = (media_id, source_url)
                return media_id

        if filepath_or_url.startswith(('http://', 'https://')):
            original_filename = os.path.basename(filepath_or_url.split('?')[0])
        else:
            original_filename = os.path.basename(filepath_or_url)

        # Apply article scope to derive the target WP filename, and dedup only
        # against the scoped name. Without a scope we cannot safely dedup by
        # filename alone (different articles often share basenames like
        # hero.webp), so the no-scope path uploads fresh without a query.
        # Sources without a usable filename (e.g. https://picsum.photos/400/300)
        # also skip dedup and upload with the helper's default name.
        scope = self._current_article_scope
        target_filename = original_filename
        if scope and original_filename and '.' in original_filename:
            target_filename = f"{scope}-{original_filename}"
            existing = self.find_existing_media(target_filename)
            if existing:
                media_id, source_url = existing
                print(f"✓ Reusing existing media: {target_filename} (id={media_id})")
                self._media_source_cache[filepath_or_url] = (media_id, source_url)
                return media_id

        if filepath_or_url.startswith(('http://', 'https://')):
            result = self.upload_media_from_url(filepath_or_url, target_filename=target_filename or None)
        else:
            result = self.upload_media_from_file(filepath_or_url, target_filename=target_filename or None)

        if result:
            media_id, source_url = result
            self._media_source_cache[filepath_or_url] = (media_id, source_url)
            return media_id
        return None
    
    def upload_media_from_url(self, url, target_filename=None):
        """Upload media from remote URL to WordPress.

        target_filename, when provided, overrides the URL-derived filename
        (used by upload_media to apply article-scope prefixing).
        """
        try:
            print(f"Downloading featured image from URL: {url}")

            # Download the image
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                print(f"✗ Failed to download image from URL: {response.status_code}")
                return None

            media_data = response.content

            # Get filename from URL or generate one
            filename = os.path.basename(url.split('?')[0])  # Remove query params
            if not filename or '.' not in filename:
                # Generate filename based on content type
                content_type = response.headers.get('content-type', '').lower()
                if 'jpeg' in content_type or 'jpg' in content_type:
                    filename = 'image.jpg'
                elif 'png' in content_type:
                    filename = 'image.png'
                elif 'gif' in content_type:
                    filename = 'image.gif'
                elif 'webp' in content_type:
                    filename = 'image.webp'
                else:
                    filename = 'image.jpg'  # Default

            # Article-scope override - upload_media has already prepended the scope
            if target_filename:
                filename = target_filename

            # Get content type
            content_type = response.headers.get('content-type', 'application/octet-stream')

        except requests.exceptions.RequestException as e:
            print(f"✗ Error downloading image from URL: {e}")
            return None

        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': content_type
        }
        
        print(f"Uploading featured image: {filename}")

        upload_response = requests.post(
            f"{self.api_url}/media",
            auth=self.auth,
            headers=headers,
            data=media_data,
            timeout=60
        )
        
        if upload_response.status_code == 201:
            media_info = upload_response.json()
            print(f"✓ Featured image uploaded successfully: {media_info['source_url']}")
            return (media_info['id'], media_info['source_url'])
        else:
            print(f"✗ Failed to upload featured image: {upload_response.status_code} - {upload_response.text}")
            return None

    def upload_media_from_file(self, filepath, target_filename=None):
        """Upload media from local file to WordPress.

        target_filename, when provided, overrides the basename of filepath
        (used by upload_media to apply article-scope prefixing).
        """
        if not os.path.exists(filepath):
            print(f"Warning: Featured image file '{filepath}' not found")
            return None

        with open(filepath, 'rb') as f:
            media_data = f.read()

        # Determine content type from the SOURCE file's extension (the on-disk
        # extension is authoritative; target_filename always preserves it).
        source_ext = os.path.splitext(os.path.basename(filepath))[1].lower()
        content_type_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        }
        content_type = content_type_map.get(source_ext, 'application/octet-stream')

        filename = target_filename or os.path.basename(filepath)

        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': content_type
        }
        
        print(f"Uploading featured image: {filename}")

        response = requests.post(
            f"{self.api_url}/media",
            auth=self.auth,
            headers=headers,
            data=media_data,
            timeout=60
        )
        
        if response.status_code == 201:
            media_info = response.json()
            print(f"✓ Featured image uploaded successfully: {media_info['source_url']}")
            return (media_info['id'], media_info['source_url'])
        else:
            print(f"✗ Failed to upload featured image: {response.status_code} - {response.text}")
            return None


def find_local_config():
    """Walk up directory tree from cwd to find nearest .wp-poster.json"""
    current = Path.cwd()
    while current != current.parent:
        config_path = current / '.wp-poster.json'
        if config_path.exists():
            return config_path
        current = current.parent
    # Check root directory
    config_path = current / '.wp-poster.json'
    if config_path.exists():
        return config_path
    return None


def find_network_config(filepath):
    """From a file path, walk up to find a .wp-poster.json containing a 'network' key.

    Returns (project_root, network_config) or (None, None).
    """
    current = Path(filepath).resolve().parent
    while True:
        config_path = current / '.wp-poster.json'
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = json.load(f)
            if 'network' in config:
                return str(current), config
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None, None


def resolve_site_identity(project_root, site_key, site_info):
    """Resolve a network site's identity (site_url, locale, blog_id).

    Prefers values declared inline in the network.sites entry (site_info).
    Falls back to a per-site <site_key>/.wp-poster.json for any missing key,
    preserving backward compatibility with the older per-site-config layout.
    """
    identity = {
        'site_url': site_info.get('site_url'),
        'locale': site_info.get('locale'),
        'blog_id': site_info.get('blog_id'),
    }
    if all(v is not None for v in identity.values()):
        return identity

    site_config_path = os.path.join(project_root, site_key, '.wp-poster.json')
    if os.path.exists(site_config_path):
        try:
            with open(site_config_path, 'r') as f:
                site_config = json.load(f)
            for key in ('site_url', 'locale', 'blog_id'):
                if identity[key] is None:
                    identity[key] = site_config.get(key)
        except (OSError, json.JSONDecodeError):
            pass

    return identity


def find_site_for_file(project_root, network_config, filepath):
    """Return (site_key, site_info) for the network site whose content_path
    contains filepath, or (None, None) if no site matches.

    Containment is checked on path boundaries rather than string prefixes: a
    file under 'de/content-evil/' must not match the site rooted at
    'de/content/', which a startswith comparison would wrongly accept once
    the trailing slash is normalised away.
    """
    file_path = Path(filepath).resolve()
    sites = network_config.get('network', {}).get('sites', {})
    for site_key, site_info in sites.items():
        content_root = Path(project_root, site_info['content_path']).resolve()
        try:
            file_path.relative_to(content_root)
        except ValueError:
            continue
        return site_key, site_info
    return None, None


def resolve_locale_for_file(filepath):
    """The declared locale of the network site a file belongs to, or None.

    Reads on-disk config only - no network calls - so `--test` and a real
    publish resolve callout labels through exactly the same path.

    Best-effort by construction. The helpers it calls are not:
    find_network_config json.load()s without a guard, and
    find_site_for_file indexes site_info['content_path'] directly, so
    malformed JSON or a site entry missing content_path raises. Those
    already run on the publish path, but only when --site-url is absent;
    this function runs unconditionally and under --test, so an exception
    here would newly break paths that used to work. A label falling back
    to English must never cost a publish.
    """
    try:
        net_root, net_config = find_network_config(filepath)
        if not net_config:
            return None
        site_key, site_info = find_site_for_file(net_root, net_config, filepath)
        if not site_info:
            return None
        return resolve_site_identity(net_root, site_key, site_info).get('locale')
    except Exception as e:
        print(
            f"⚠ Could not determine the site language for {filepath} ({e}); "
            "using English callout labels",
            file=sys.stderr,
        )
        return None


def find_translation_siblings(project_root, network_config, translation_set, exclude_locale):
    """Find sibling posts with matching translation_set that have been published (have an id).

    Returns list of {"locale": ..., "blog_id": ..., "post_id": ...}.
    """
    siblings = []
    sites = network_config.get('network', {}).get('sites', {})

    for site_key, site_info in sites.items():
        content_path = os.path.join(project_root, site_info['content_path'])
        if not os.path.isdir(content_path):
            continue

        # Resolve locale/blog_id from the network.sites map (falling back to a
        # per-site config file when the map omits them).
        identity = resolve_site_identity(project_root, site_key, site_info)
        site_locale = identity.get('locale') or ''
        if not site_locale or site_locale == exclude_locale:
            continue

        # Search for markdown files with matching translation_set
        for md_path in glob_mod.glob(os.path.join(content_path, '**', '*.md'), recursive=True):
            try:
                # Reuse lightweight frontmatter parsing
                with open(md_path, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                if not file_content.startswith('---'):
                    continue
                parts = file_content.split('---', 2)
                if len(parts) < 3:
                    continue
                fm = load_frontmatter(parts[1]) or {}
                if fm.get('translation_set') == translation_set and 'id' in fm:
                    siblings.append({
                        'locale': site_locale,
                        'blog_id': identity.get('blog_id'),
                        'post_id': fm['id'],
                    })
            except (OSError, yaml.YAMLError):
                continue

    return siblings


# Each member's link write is attempted up to this many times, sleeping
# _MSLS_BACKOFF[attempt-1] seconds before each retry, so a transient transport
# failure (SSH blip, timeout) self-heals in-run rather than needing a re-run.
_MSLS_MAX_ATTEMPTS = 3
_MSLS_BACKOFF = [1, 2]


def _msls_eval_command(wp_cli_alias, blog_id, post_id, others):
    """Build the combined write-and-verify wp eval for one translation member.

    The payload is passed base64-encoded so any character in it (quotes,
    apostrophes, unicode) cannot break the PHP string. The same eval writes the
    option and echoes the stored value back via wp_json_encode, so the caller
    can confirm the write actually took effect without a second round-trip.
    """
    payload_b64 = base64.b64encode(json.dumps(others).encode()).decode()
    script = (
        f'switch_to_blog({blog_id}); '
        f'update_option("msls_{post_id}", json_decode(base64_decode("{payload_b64}"), true)); '
        f'echo wp_json_encode(get_option("msls_{post_id}")); '
        f'restore_current_blog();'
    )
    return ['wp', wp_cli_alias, 'eval', script]


def _normalize_msls_map(raw):
    """Normalize a decoded msls option to {locale_str: post_id_int} for comparison.

    PHP/JSON round-trips may hand back string post ids or encode an empty map as
    a JSON array; normalize both so equality checks are type-stable.
    """
    if isinstance(raw, dict):
        return {str(k): int(v) for k, v in raw.items()}
    return {}  # empty PHP array encodes as [], or any non-object


def write_msls_links(wp_cli_alias, current_post, siblings):
    """Write and verify MSLS options for all members of a translation set.

    current_post: {"locale": "en_US", "blog_id": 1, "post_id": 4773}
    siblings: [{"locale": "es_ES", "blog_id": 2, "post_id": 266}, ...]

    For each member the option is written and immediately read back; the write
    is retried on transient failure and only reported ok once the stored value
    matches what we intended to write (issue #12). Returns a per-member status
    list (issue #11):
        [{"locale", "post_id", "ok": bool, "error": str | None}, ...]
    A failure on one member does not abort writes for the others.
    """
    all_members = [current_post] + siblings
    results = []

    for member in all_members:
        # This member's msls option is the mesh of all OTHER members.
        others = {m['locale']: m['post_id'] for m in all_members if m != member}
        expected = _normalize_msls_map(others)
        cmd = _msls_eval_command(wp_cli_alias, member['blog_id'], member['post_id'], others)

        status = {'locale': member['locale'], 'post_id': member['post_id'], 'ok': False, 'error': None}
        last_error = None
        for attempt in range(_MSLS_MAX_ATTEMPTS):
            if attempt > 0:
                time.sleep(_MSLS_BACKOFF[attempt - 1])
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            except FileNotFoundError:
                # wp-cli absent: cannot self-heal within this run, so fail fast.
                last_error = "wp-cli not found / alias misconfigured (is `wp` on PATH?)"
                break
            except subprocess.TimeoutExpired:
                last_error = "wp eval timed out after 15s"
                continue

            if result.returncode != 0:
                detail = (result.stderr or result.stdout or '').strip()
                last_error = f"wp eval exited {result.returncode}" + (f": {detail}" if detail else "")
                continue

            # Read-back verification: confirm the option actually persisted.
            try:
                got = _normalize_msls_map(json.loads(result.stdout))
            except (ValueError, TypeError):
                last_error = f"could not parse read-back output: {result.stdout.strip()!r}"
                continue
            if got == expected:
                status['ok'] = True
                last_error = None
                break
            last_error = f"read-back mismatch: expected {expected}, got {got}"

        if not status['ok']:
            status['error'] = last_error
        results.append(status)

    return results


# ---------------------------------------------------------------------------
# Cache purging (SpinupWP page cache, via the plugin's WP-CLI commands)
# ---------------------------------------------------------------------------

_PURGE_TIMEOUT = 30


class PurgeConfigError(Exception):
    """A purge could not be resolved from configuration.

    Raised before any subprocess is spawned, so a misconfigured run costs
    nothing and reports the exact file, key or value to fix.
    """


def read_frontmatter(filepath):
    """Parse just the frontmatter of a file, returning {} when it has none."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            return load_frontmatter(parts[1]) or {}
    return {}


def _global_config_paths():
    """Global config locations, in precedence order.

    Deliberately excludes the cwd-relative lookup that load_config() performs:
    a purge must never be steered by which directory the shell happens to be
    in. Defined as a function so tests can substitute it.
    """
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    return [
        Path.home() / '.wp-poster.json',
        Path.home() / '.config/wp-poster/config.json',
        script_dir / '.wp-poster.json',
    ]


def find_config_for_purge(anchor_path):
    """Locate the config governing anchor_path.

    Returns (config, config_path, project_root). project_root is the config's
    directory when the config describes a network, otherwise None.

    Anchoring at the target file rather than the working directory is what
    makes `wp-post --purge --file /other/project/post.md` purge the site that
    file belongs to, instead of whatever project the shell is sitting in. A
    network config found anywhere up the tree beats a nearer non-network one,
    so the legacy per-site config layout cannot shadow the network map.
    """
    start = Path(anchor_path).resolve()
    current = start if start.is_dir() else start.parent
    nearest = None

    while True:
        candidate = current / '.wp-poster.json'
        if candidate.exists():
            try:
                with open(candidate, 'r') as f:
                    config = json.load(f)
            except (OSError, ValueError) as e:
                raise PurgeConfigError(f"Could not read {candidate}: {e}")
            if 'network' in config:
                return config, str(candidate), str(current)
            if nearest is None:
                nearest = (config, str(candidate))
        if current.parent == current:
            break
        current = current.parent

    if nearest:
        return nearest[0], nearest[1], None

    for path in _global_config_paths():
        if path.exists():
            try:
                with open(path, 'r') as f:
                    config = json.load(f)
            except (OSError, ValueError) as e:
                raise PurgeConfigError(f"Could not read {path}: {e}")
            # A global config can itself describe a network; project_root must
            # then point at its directory, mirroring the walk-up branch above,
            # or resolve_site_identity's os.path.join(None, ...) raises.
            project_root = str(path.parent) if 'network' in config else None
            return config, str(path), project_root

    raise PurgeConfigError(
        f"No .wp-poster.json found from {start} upward, or in any global location."
    )


def resolve_wp_cli_transport(config, config_path):
    """Return the argv prefix for wp-cli calls, e.g. ['wp', '@payperfax'].

    The alias is read from network.wp_cli_alias when the config describes a
    network (where the key already exists for MSLS linking), otherwise from a
    top-level wp_cli_alias. A value starting with '@' is a wp-cli alias
    resolved through ~/.wp-cli/config.yml; anything else is used as an --ssh=
    target, so a project can be self-contained with no external wp-cli config.
    """
    alias = (config.get('network') or {}).get('wp_cli_alias') or config.get('wp_cli_alias')
    if not alias:
        raise PurgeConfigError(
            f"No wp_cli_alias in {config_path}. Add one, either as a wp-cli alias\n"
            "resolved through ~/.wp-cli/config.yml:\n"
            '  "wp_cli_alias": "@myalias"\n'
            "or as an ssh target, which needs no wp-cli config at all:\n"
            '  "wp_cli_alias": "myhost/sites/example.com/files"'
        )
    if not isinstance(alias, str):
        raise PurgeConfigError(
            f"wp_cli_alias in {config_path} must be a string, got {type(alias).__name__}."
        )
    if alias.startswith('@'):
        return ['wp', alias]
    return ['wp', f'--ssh={alias}']


def _validate_purge_target(target, source):
    """Reject a target that could not be safely turned into a wp-cli command.

    Runs before any subprocess, so a half-configured network entry fails with
    a readable message instead of shipping `--url=None` to the server.
    """
    site_url = target['site_url']
    if not isinstance(site_url, str) or not site_url.startswith(('http://', 'https://')):
        raise PurgeConfigError(
            f"Target '{target['label']}' has an unusable site_url ({site_url!r}) "
            f"in {source}. Expected an http(s) URL."
        )
    post_id = target['post_id']
    if post_id is not None:
        if isinstance(post_id, bool) or not isinstance(post_id, int) or post_id <= 0:
            raise PurgeConfigError(
                f"Target '{target['label']}' has an unusable post id ({post_id!r}) "
                f"in {source}. Expected a positive integer."
            )
    return target


def resolve_purge_targets(scope, value, config, project_root=None, config_path=None):
    """Resolve a purge scope to an ordered list of validated targets.

    scope: 'file' | 'site' | 'network'
    value: file path for 'file'; site key (or '' meaning "the configured
           site") for 'site'; ignored for 'network'.

    Returns [{'label': str, 'site_url': str, 'post_id': int | None}, ...]
    where a post_id of None means "purge this whole site".

    Every failure mode raises PurgeConfigError naming what to fix, rather than
    guessing at a target - purging the wrong blog is worse than not purging.
    """
    source = config_path or 'the loaded config'
    network = config.get('network') or {}
    sites = network.get('sites') or {}

    if scope == 'network':
        if not sites:
            raise PurgeConfigError(
                f"--network needs a network config, but {source} has no 'network' key. "
                "Use --site for a single-site project."
            )
        targets = []
        for site_key, site_info in sites.items():
            identity = resolve_site_identity(project_root, site_key, site_info)
            targets.append(_validate_purge_target({
                'label': site_key,
                'site_url': identity['site_url'],
                'post_id': None,
            }, source))
        return targets

    if scope == 'site':
        if not sites:
            site_url = config.get('site_url')
            if not site_url:
                raise PurgeConfigError(f"No site_url in {source}; cannot resolve --site.")
            return [_validate_purge_target(
                {'label': site_url, 'site_url': site_url, 'post_id': None}, source)]
        valid = ', '.join(sorted(sites))
        if not value:
            raise PurgeConfigError(
                f"--site requires a site key on a network project (from {source}). "
                f"Valid keys: {valid}"
            )
        if value not in sites:
            raise PurgeConfigError(
                f"Unknown site '{value}' in {source}. Valid keys: {valid}"
            )
        identity = resolve_site_identity(project_root, value, sites[value])
        return [_validate_purge_target(
            {'label': value, 'site_url': identity['site_url'], 'post_id': None}, source)]

    # scope == 'file'
    try:
        frontmatter = read_frontmatter(value)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise PurgeConfigError(f"Could not read frontmatter from {value}: {e}")

    post_id = frontmatter.get('id')
    if not post_id:
        raise PurgeConfigError(
            f"{value} has no post id in its frontmatter, so it has not been "
            "published yet and nothing is cached for it."
        )

    # Names both the config and the offending file, so a validation failure
    # below (e.g. a bad post id) points at the file the user actually ran
    # --purge on, not just the config that supplied the site_url.
    file_source = f"{value} (config: {source})"

    if sites:
        try:
            site_key, site_info = find_site_for_file(project_root, config, value)
        except (KeyError, TypeError) as e:
            # A network.sites entry with a missing or null content_path breaks
            # find_site_for_file's containment check; report it instead of
            # letting the KeyError/TypeError escape as a raw traceback.
            raise PurgeConfigError(
                f"A network.sites entry in {source} has an invalid or missing "
                f"content_path ({e}); cannot determine which site owns {value}."
            )
        if site_key is None:
            configured = ', '.join(sorted(
                p for p in (s.get('content_path') for s in sites.values()) if p
            ))
            raise PurgeConfigError(
                f"{value} is not inside any configured content_path ({configured}) "
                f"from {source}, so its site could not be determined."
            )
        identity = resolve_site_identity(project_root, site_key, site_info)
        return [_validate_purge_target({
            'label': f'{site_key} #{post_id}',
            'site_url': identity['site_url'],
            'post_id': post_id,
        }, file_source)]

    site_url = config.get('site_url')
    if not site_url:
        raise PurgeConfigError(f"No site_url in {source}; cannot resolve --file.")
    return [_validate_purge_target(
        {'label': f'#{post_id}', 'site_url': site_url, 'post_id': post_id}, file_source)]


def build_purge_command(transport, target):
    """Build the wp-cli argv that purges one target.

    A target with a post_id purges just that post; without one it purges the
    whole site. --url= is how wp-cli selects a blog within a multisite
    network, and is harmless on a single site.
    """
    base = transport + ['spinupwp', 'cache']
    if target['post_id'] is None:
        return base + ['purge-site', f"--url={target['site_url']}"]
    return base + ['purge-post', str(target['post_id']), f"--url={target['site_url']}"]


def spinupwp_purge(transport, target, timeout=_PURGE_TIMEOUT):
    """Purge one target. Returns (ok, error) and never raises.

    Failures are returned rather than raised so the caller can keep purging
    the remaining targets: one unreachable site should not leave the rest of
    the network stale.
    """
    cmd = build_purge_command(transport, target)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return False, "wp-cli not found (is `wp` on PATH?)"
    except subprocess.TimeoutExpired:
        # Not an OSError subclass, so this clause is load-bearing.
        return False, f"wp timed out after {timeout}s"
    except OSError as e:
        return False, f"could not run wp: {e}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip()
        return False, f"wp exited {result.returncode}" + (f": {detail}" if detail else "")
    return True, None


def handle_purge(args):
    """Resolve the requested scope, purge each target, return an exit code.

    Configuration problems are reported before anything runs. Once purging
    starts, a failure on one target is recorded and the loop continues, so a
    single unreachable site cannot leave the rest of the network stale.
    """
    selected = [
        ('file', args.purge_file is not None),
        ('site', args.purge_site is not None),
        ('network', bool(args.purge_network)),
    ]
    chosen = [name for name, active in selected if active]
    if len(chosen) != 1:
        problem = "Specify exactly one scope" if not chosen else f"Got {len(chosen)} scopes"
        print(f"✗ {problem} for --purge: --file <path>, --site [key], or --network",
              file=sys.stderr)
        return 1
    scope = chosen[0]
    value = {'file': args.purge_file, 'site': args.purge_site, 'network': None}[scope]

    # Anchor config discovery at the target file when there is one, so a
    # --file from another project is never purged against the shell's site.
    anchor = args.purge_file or os.getcwd()

    try:
        config, config_path, project_root = find_config_for_purge(anchor)
        transport = resolve_wp_cli_transport(config, config_path)
        targets = resolve_purge_targets(scope, value, config, project_root, config_path)
    except PurgeConfigError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1

    noun = 'site' if len(targets) == 1 else 'sites'
    print(f"Purging SpinupWP cache ({len(targets)} {noun})")

    failures = 0
    for target in targets:
        if args.test:
            print(f"  [test] {target['label']:<12} {' '.join(build_purge_command(transport, target))}")
            continue
        if args.verbose:
            print(f"  → {' '.join(build_purge_command(transport, target))}")
        ok, error = spinupwp_purge(transport, target)
        if ok:
            print(f"  ✓ {target['label']:<12} {target['site_url']}")
        else:
            failures += 1
            print(f"  ✗ {target['label']:<12} {target['site_url']}  ({error})")

    if args.test:
        return 0
    purged = len(targets) - failures
    mark = '✓' if failures == 0 else '✗'
    print(f"{mark} {purged} purged, {failures} failed")
    return 1 if failures else 0


def resolve_format(cli_markdown, cli_raw, frontmatter, config):
    """Resolve format: CLI > frontmatter > config > default(raw)"""
    if cli_raw:
        return 'raw'
    if cli_markdown:
        return 'markdown'
    if frontmatter.get('format') in ('raw', 'markdown'):
        return frontmatter['format']
    if config.get('default_format') in ('raw', 'markdown'):
        return config['default_format']
    return 'raw'


def get_config_paths():
    """Get all config paths in precedence order with their status."""
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    local_config = find_local_config()

    paths = []
    seen = set()

    if local_config:
        paths.append(('Local project', local_config, True))
        seen.add(local_config.resolve())

    candidates = [
        ('User global', Path.home() / '.wp-poster.json'),
        ('XDG config', Path.home() / '.config/wp-poster/config.json'),
        ('App default', script_dir / '.wp-poster.json'),
    ]

    for name, path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved not in seen:
            paths.append((name, path, path.exists()))
            if path.exists():
                seen.add(resolved)

    return paths


def load_config():
    """Load configuration from various sources.

    Precedence (first match wins):
    1. Local/project config (nearest .wp-poster.json walking up from cwd)
    2. User global (~/.wp-poster.json)
    3. XDG config (~/.config/wp-poster/config.json)
    4. App default (script directory .wp-poster.json)
    """
    config = {}

    # Get the directory where this script is located
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))

    # Find local config by walking up directory tree
    local_config = find_local_config()

    # Check for config file in various locations (highest priority first)
    config_paths = []
    if local_config:
        config_paths.append(local_config)
    config_paths.extend([
        Path.home() / '.wp-poster.json',
        Path.home() / '.config/wp-poster/config.json',
        script_dir / '.wp-poster.json',  # App default (lowest priority)
    ])

    for config_path in config_paths:
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = json.load(f)
                break
    
    # Override with environment variables
    if 'WP_SITE_URL' in os.environ:
        config['site_url'] = os.environ['WP_SITE_URL']
    if 'WP_USERNAME' in os.environ:
        config['username'] = os.environ['WP_USERNAME']
    if 'WP_APP_PASSWORD' in os.environ:
        config['app_password'] = os.environ['WP_APP_PASSWORD']
    
    return config


def init_config():
    """Interactive configuration setup"""
    print("WordPress Poster Configuration Setup")
    print("=" * 40)
    print("\nThis will create a .wp-poster.json file in the current directory.\n")
    
    # Check if config already exists
    config_path = Path.cwd() / '.wp-poster.json'
    if config_path.exists():
        response = input("Config file already exists. Overwrite? (y/N): ").strip().lower()
        if response != 'y':
            print("Configuration cancelled.")
            return False
    
    config = {}
    
    # Get site URL
    while True:
        site_url = input("WordPress site URL (e.g., https://example.com): ").strip()
        if site_url:
            if not site_url.startswith(('http://', 'https://')):
                site_url = 'https://' + site_url
            config['site_url'] = site_url.rstrip('/')
            break
        print("Site URL is required.")
    
    # Get username
    while True:
        username = input("WordPress username: ").strip()
        if username:
            config['username'] = username
            break
        print("Username is required.")
    
    # Get application password
    while True:
        app_password = getpass.getpass("Application Password: ").strip()
        if app_password:
            # Remove spaces from the password if they were included
            app_password = app_password.replace(' ', '')
            config['app_password'] = app_password
            break
        print("Application Password is required.")
    
    # Test the connection
    print("\nTesting connection...")
    try:
        response = requests.get(
            f"{config['site_url']}/wp-json/wp/v2/users/me",
            auth=(config['username'], config['app_password']),
            timeout=10
        )
        if response.status_code == 200:
            user_data = response.json()
            print(f"✓ Successfully connected as: {user_data.get('name', config['username'])}")

            # Ask for default author context
            print("\nDefault author for posts (optional):")
            print("  Leave blank to use authenticated user, or enter username/ID")
            author_context = input("Default author: ").strip()
            if author_context:
                config['author_context'] = author_context

            # Ask for SSH configuration
            print("\nConfigure SSH for external tooling? (y/N)")
            if input().strip().lower() == 'y':
                ssh_config = {}
                print("\nSSH Configuration:")

                key = input("  SSH key path (e.g., ~/.ssh/id_rsa): ").strip()
                if key:
                    ssh_config['key'] = key

                user = input("  SSH user: ").strip()
                if user:
                    ssh_config['user'] = user

                host = input("  SSH host: ").strip()
                if host:
                    ssh_config['host'] = host

                wp_path = input("  WordPress path on server (e.g., ~/public_html): ").strip()
                if wp_path:
                    ssh_config['wp_path'] = wp_path

                if ssh_config:
                    config['ssh'] = ssh_config
        elif response.status_code == 401:
            print("✗ Authentication failed. Please check your credentials.")
            retry = input("Would you like to try again? (y/N): ").strip().lower()
            if retry == 'y':
                return init_config()
            return False
        else:
            print(f"✗ Connection failed with status: {response.status_code}")
            print("Please check your site URL and try again.")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ Connection error: {e}")
        print("Please check your site URL and internet connection.")
        return False
    
    # Save configuration
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"\n✓ Configuration saved to: {config_path}")
    print("\nYou can now use: wp-post <file>")
    return True


def init_network_config():
    """Interactive network (multisite) configuration setup."""
    print("WordPress Multisite Network Configuration")
    print("=" * 45)
    print("\nThis will scaffold a multisite project directory.\n")

    # Get WP-CLI alias
    while True:
        wp_cli_alias = input("WP-CLI alias (e.g., @payperfax): ").strip()
        if wp_cli_alias:
            break
        print("WP-CLI alias is required.")

    # Discover sites
    print(f"\nDiscovering sites via: wp {wp_cli_alias} site list ...")
    try:
        result = subprocess.run(
            ['wp', wp_cli_alias, 'site', 'list', '--format=json'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            print(f"✗ wp site list failed: {result.stderr}")
            return False
        sites_data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"✗ Error discovering sites: {e}")
        return False

    if not sites_data:
        print("✗ No sites found in the network.")
        return False

    print(f"Found {len(sites_data)} site(s):")
    for site in sites_data:
        print(f"  blog_id={site['blog_id']}  {site['url']}")

    # Get locale for each site
    print("\nQuerying locales...")
    for site in sites_data:
        try:
            result = subprocess.run(
                ['wp', wp_cli_alias, 'eval',
                 f'switch_to_blog({site["blog_id"]}); '
                 f'$l = get_option("WPLANG"); echo $l ?: "en_US"; '
                 f'restore_current_blog();'],
                capture_output=True, text=True, timeout=15
            )
            site['locale'] = result.stdout.strip() if result.returncode == 0 else 'en_US'
        except (subprocess.TimeoutExpired, FileNotFoundError):
            site['locale'] = 'en_US'
        print(f"  blog_id={site['blog_id']}  locale={site['locale']}")

    # Get shared credentials
    print("\nShared credentials for all sites:")
    while True:
        username = input("  WordPress username: ").strip()
        if username:
            break
        print("  Username is required.")
    while True:
        app_password = getpass.getpass("  Application Password: ").strip()
        if app_password:
            app_password = app_password.replace(' ', '')
            break
        print("  Application Password is required.")

    # Test connection against first site
    test_url = sites_data[0]['url'].rstrip('/')
    print(f"\nTesting connection against {test_url} ...")
    try:
        response = requests.get(
            f"{test_url}/wp-json/wp/v2/users/me",
            auth=(username, app_password),
            timeout=10
        )
        if response.status_code == 200:
            user_data = response.json()
            print(f"✓ Connected as: {user_data.get('name', username)}")
        else:
            print(f"✗ Authentication failed: HTTP {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ Connection error: {e}")
        return False

    # Prompt for subdirectory names
    print("\nSubdirectory names for each site:")
    site_dirs = {}
    for site in sites_data:
        lang_prefix = site['locale'].split('_')[0]
        default = lang_prefix
        dir_name = input(f"  blog_id={site['blog_id']} ({site['locale']}) [{default}]: ").strip()
        if not dir_name:
            dir_name = default
        site_dirs[site['blog_id']] = dir_name

    # Scaffold directory structure
    project_root = Path.cwd()
    network_sites = {}

    for site in sites_data:
        dir_name = site_dirs[site['blog_id']]
        content_dir = project_root / dir_name / 'content'
        content_dir.mkdir(parents=True, exist_ok=True)

        # Site identity lives inline in the network.sites map (no per-site files).
        network_sites[dir_name] = {
            'content_path': f'{dir_name}/content/',
            'site_url': site['url'].rstrip('/'),
            'locale': site['locale'],
            'blog_id': int(site['blog_id']),
        }

    # Write single root config: shared credentials + full site map.
    root_config = {
        'username': username,
        'app_password': app_password,
        'network': {
            'wp_cli_alias': wp_cli_alias,
            'sites': network_sites,
        },
    }
    root_config_path = project_root / '.wp-poster.json'
    with open(root_config_path, 'w') as f:
        json.dump(root_config, f, indent=2)
    print(f"  ✓ {root_config_path}")

    print(f"\n✓ Network project scaffolded with {len(sites_data)} site(s) in one config.")
    print("Add 'translation_set' to frontmatter to link posts across sites.")
    return True


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description='Post files with frontmatter to WordPress',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
frontmatter fields:
  Input files use YAML frontmatter delimited by --- lines.

  title           (required) Post title
  id              Update existing post instead of creating new
  status          draft or publish (default: publish, --draft overrides)
  slug            URL slug
  excerpt         Post excerpt
  post_type       post, page, or custom post type (default: post)
  format          raw or markdown (see format resolution below)
  date            Publish date in ISO 8601 format
  author          Username or user ID (overrides config author_context)
  template        Page template name (hierarchical post types)
  parent          Parent post ID (hierarchical post types)
  featured_image  Local file path or URL (uploaded to media library)
  categories      List of category names (posts only, auto-created)
  tags            List of tag names (posts only, auto-created)
  taxonomies      Custom taxonomies as {taxonomy: term} or {taxonomy: [terms]}
                  Terms are auto-created if they don't exist
  meta            Custom post meta as {key: value}
  acf             Advanced Custom Fields as {field: value}
  rankmath        Rank Math SEO meta with shorthand keys:
                    title, description, focus_keyword
                  Full rank_math_* keys also accepted
  translation_set MSLS translation group key (multisite only)

format resolution (first match wins):
  1. CLI flags (--raw, --markdown)
  2. Frontmatter 'format' field
  3. Config 'default_format' setting
  4. Default: raw

images:
  featured_image in frontmatter uploads to the media library and sets
  the post thumbnail. Accepts a local path or remote URL.

  In markdown mode, inline images are also uploaded to the media library
  and their URLs are rewritten to the WordPress copy:
    - ![alt](local.jpg)           local file uploaded
    - ![alt](https://...)         remote URL downloaded and re-uploaded
    - ![alt](url "caption")      "caption" becomes a <figcaption>
    - <figure>/<img> HTML tags    also detected and uploaded
  If a remote upload fails, the original URL is kept. If a local file
  is missing or fails to upload, the image is dropped from output.

  Each article publishes its media into a per-article namespace in the
  WordPress media library. The namespace (scope) is derived from the
  markdown file's parent directory basename, sanitized to slug form, and
  is prefixed onto every uploaded filename - so an article in
  content/my-post/ uploads its hero.webp as my-post-hero.webp. Before
  uploading, the script queries by the scoped slug and reuses any
  existing attachment, so republishing a post does not create duplicates
  or trigger filename suffixing (image-1.jpg, image-2.jpg, ...). The
  scoping prevents cross-article filename collisions when multiple
  articles ship images with the same basename. Caveats: renaming an
  article's parent directory orphans the prior scoped attachment;
  sources without a usable filename (e.g. https://picsum.photos/400/300)
  cannot be scoped and will upload fresh on each run.
  --test mode skips all uploads.

callouts:
  Eight callout types are written as GFM blockquotes in markdown mode:
    [!NOTE] [!TIP] [!IMPORTANT] [!WARNING] [!CAUTION]  bordered group
    [!SUMMARY]   key points; write a markdown list
    [!FAQ]       wp:details accordion, one per **question** line
    [!BOOKMARK]  post card resolved from a slug, /path/, or URL

  A [!FAQ] question is a line that is entirely **bold** and is either
  the first line of the body or preceded by a blank line; otherwise it
  stays part of the previous answer instead of starting a new question.
  The rule cuts both ways - a bold-only line after a blank line becomes a
  question even mid-answer, so write lead-ins as "**Note:** text" with
  the text on the same line, which is never mistaken for a question.

  Backgrounds come from the theme palette (tertiary), so callouts pick up
  the site's tint. Accents - border, icon, label - use GitHub's
  conventional hues for the five GFM types (note #0969da, tip #1a7f37,
  important #8250df, warning #9a6700, caution #d1242f). SUMMARY, FAQ, and
  BOOKMARK have no such convention and use the theme's
  primary-alt-accent.
  Override colour and icon per type in .wp-poster.json under "callouts",
  where a value like "#cf2e2e" is used as a literal and anything else is
  treated as a palette slug. See the wp-post skill for the full schema.

  Labels are not configurable. They come from a built-in table in eleven
  languages, selected by the destination site's locale in network.sites -
  a post under a de_DE site gets "Warnung", not "Warning". A language with
  no entry falls back to English and warns. --test resolves the locale the
  same way, so a preview matches a publish.

  Icons are inline SVG and need the unfiltered_html capability to survive
  WordPress's content filter; wp-post warns after publishing if they were
  stripped.

output:
  Omit id to create a new post; include id to update an existing one.

  JSON to stdout on success:
    {"success": true, "id": 123, "title": "...", "url": "..."}
  JSON to stdout on failure:
    {"success": false, "error": "..."}
  Progress and diagnostics are printed to stdout as plain text.

example file:
  ---
  title: My Post
  categories: [News, Updates]
  tags: [release]
  featured_image: header.jpg
  rankmath:
    focus_keyword: my topic
  ---
  Post content here (markdown if --markdown or format: markdown).
"""
    )
    parser.add_argument('file', nargs='?', help='File to post')
    parser.add_argument('--site-url', help='WordPress site URL')
    parser.add_argument('--username', help='WordPress username')
    parser.add_argument('--app-password', help='WordPress application password')
    parser.add_argument('--draft', action='store_true', help='Post as draft')
    parser.add_argument('--init', action='store_true', help='Initialize configuration interactively')
    parser.add_argument('--init-network', action='store_true', help='Initialize multisite network project')
    parser.add_argument('--config-path', action='store_true', help='Print path to active config file')
    parser.add_argument('--ping', action='store_true', help='Test connection to the configured WordPress site')
    parser.add_argument('--test', action='store_true', help='Test mode: preview content without posting')
    parser.add_argument('--markdown', action='store_true', help='Convert markdown to Gutenberg blocks')
    parser.add_argument('--raw', action='store_true', help='Post content as-is (override format frontmatter)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed debug output')
    parser.add_argument('--purge', action='store_true',
                        help='Clear the SpinupWP page cache (requires a scope selector)')
    # dest is mandatory here: a bare --file would collide with the positional
    # 'file' argument and silently parse to None.
    parser.add_argument('--file', dest='purge_file', metavar='PATH',
                        help='--purge scope: the page published from this file')
    parser.add_argument('--site', dest='purge_site', nargs='?', const='', metavar='KEY',
                        help='--purge scope: one site (network key, or bare for a single site)')
    parser.add_argument('--network', dest='purge_network', action='store_true',
                        help='--purge scope: every site in the network')
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    # Handle --purge flag
    if args.purge:
        sys.exit(handle_purge(args))

    # A purge scope selector without --purge means the flag was likely meant
    # for --purge but the flag itself was left off, or argparse's abbreviation
    # matching silently intercepted a similarly named option (e.g. --site
    # matching --site-url). Fail loudly instead of silently dropping the
    # value or posting to the wrong site.
    given = [flag for flag, active in (
        ('--file', args.purge_file is not None),
        ('--site', args.purge_site is not None),
        ('--network', args.purge_network),
    ) if active]
    if given:
        print(f"✗ {', '.join(given)} only valid with --purge", file=sys.stderr)
        sys.exit(1)

    # Handle --init flag
    if args.init:
        sys.exit(0 if init_config() else 1)

    # Handle --init-network flag
    if args.init_network:
        sys.exit(0 if init_network_config() else 1)

    # Handle --config-path flag
    if args.config_path:
        config_paths = get_config_paths()
        for name, path, exists in config_paths:
            if exists:
                print(path)
                sys.exit(0)
        print("No config file found", file=sys.stderr)
        sys.exit(1)

    # Handle --ping flag
    if args.ping:
        config = load_config()
        site_url = args.site_url or config.get('site_url')
        username = args.username or config.get('username')
        app_password = args.app_password or config.get('app_password')

        if not all([site_url, username, app_password]):
            print("✗ Missing credentials. Run --init or provide --site-url, --username, --app-password", file=sys.stderr)
            sys.exit(1)

        print(f"Pinging {site_url} ...")
        try:
            response = requests.get(
                f"{site_url.rstrip('/')}/wp-json/wp/v2/users/me",
                params={'context': 'edit'},
                auth=(username, app_password),
                timeout=10
            )
            if response.status_code == 200:
                user_data = response.json()
                print(f"✓ Connected as: {user_data.get('name', username)} (ID {user_data.get('id')})")
                print(f"  Username: {username}")
                print(f"  Site: {site_url}")
                print(f"  Roles: {', '.join(user_data.get('roles', []))}")
                sys.exit(0)
            else:
                print(f"✗ Authentication failed: HTTP {response.status_code}", file=sys.stderr)
                sys.exit(1)
        except requests.exceptions.ConnectionError:
            print(f"✗ Could not connect to {site_url}", file=sys.stderr)
            sys.exit(1)
        except requests.exceptions.Timeout:
            print(f"✗ Connection timed out", file=sys.stderr)
            sys.exit(1)

    # Handle --test flag (test mode doesn't need WordPress credentials)
    if args.test:
        if not args.file:
            parser.print_help()
            sys.exit(1)

        if not os.path.exists(args.file):
            print(f"Error: File '{args.file}' not found")
            sys.exit(1)

        # Create a dummy poster instance just for parsing (no bookmark
        # lookups in test mode - the dummy site URL is not real). The
        # locale is still resolved for real, so --test previews the same
        # callout labels a publish would emit.
        poster = WordPressPost('https://example.com', 'user', 'pass',
                               callout_config=load_config().get('callouts'),
                               resolve_bookmarks=False,
                               locale=resolve_locale_for_file(args.file))

        # Resolve format: CLI > frontmatter > config > default
        config = load_config()
        frontmatter_peek = poster.parse_frontmatter_only(args.file)
        fmt = resolve_format(args.markdown, args.raw, frontmatter_peek, config)

        if fmt == 'markdown':
            print(f"Converting {args.file} to Gutenberg blocks...")
            try:
                frontmatter, content = poster.parse_markdown_file(args.file)
            except ValueError as e:
                print(f"Error: {e} in {args.file}")
                sys.exit(1)

            print("Frontmatter:")
            print("=" * 40)
            print(yaml.dump(frontmatter, default_flow_style=False))

            print("Generated Gutenberg blocks:")
            print("=" * 40)
            print(content)
        else:
            print(f"Parsing {args.file} (no conversion)...")
            frontmatter, content = poster.parse_raw_file(args.file)

            print("Frontmatter:")
            print("=" * 40)
            print(yaml.dump(frontmatter, default_flow_style=False))

            print("Content:")
            print("=" * 40)
            print(content)
        sys.exit(0)
    
    # If no file provided and not init/test, show help and config info
    if not args.file:
        parser.print_help()
        print("\nConfig files (in precedence order):")
        config_paths = get_config_paths()
        active_found = False
        active_config = None
        for name, path, exists in config_paths:
            if exists and not active_found:
                print(f"  ✓ {name}: {path} (active)")
                active_found = True
                with open(path, 'r') as f:
                    active_config = json.load(f)
            elif exists:
                print(f"    {name}: {path}")
            else:
                print(f"    {name}: {path} (not found)")
        if not active_found:
            print("  No config file found. Run 'wp-post --init' to create one.")
        elif active_config and active_config.get('author_context'):
            print(f"\nDefault author: {active_config['author_context']}")
        sys.exit(1)
    
    # Load configuration
    config = load_config()
    
    # Network mode: when the target file lives under a network.sites content_path,
    # resolve site_url (and fill in shared credentials) from the root network
    # config, so a single root .wp-poster.json can serve every site. Explicit
    # --site-url still wins.
    if not args.site_url:
        net_root, net_config = find_network_config(args.file)
        if net_config:
            site_key, site_info = find_site_for_file(net_root, net_config, args.file)
            if site_info:
                identity = resolve_site_identity(net_root, site_key, site_info)
                if identity.get('site_url'):
                    config['site_url'] = identity['site_url']
            # Shared credentials may live in the root network config.
            for key in ('username', 'app_password'):
                if key not in config and key in net_config:
                    config[key] = net_config[key]

    # Override with command line arguments
    if args.site_url:
        config['site_url'] = args.site_url
    if args.username:
        config['username'] = args.username
    if args.app_password:
        config['app_password'] = args.app_password

    # Validate required configuration
    required = ['site_url', 'username', 'app_password']
    missing = [key for key in required if key not in config]
    
    if missing:
        print(f"Error: Missing configuration: {', '.join(missing)}")
        print("\nNo configuration found. Run 'wp-post --init' to set up your credentials interactively.")
        print("\nAlternatively, you can provide configuration through:")
        print("1. Command line arguments (--site-url, --username, --app-password)")
        print("2. Environment variables (WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD)")
        print("3. Config file (~/.wp-poster.json or .wp-poster.json in current directory)")
        print("\nExample config file:")
        print(json.dumps({
            "site_url": "https://your-site.com",
            "username": "your-username",
            "app_password": "your-app-password"
        }, indent=2))
        sys.exit(1)
    
    # Check if file exists
    if not os.path.exists(args.file):
        print(f"Error: File '{args.file}' not found")
        sys.exit(1)
    
    # Create poster instance and post. Language follows the file's site
    # mapping, not --site-url: the content's language does not change
    # based on where it is pushed.
    poster = WordPressPost(
        config['site_url'],
        config['username'],
        config['app_password'],
        callout_config=config.get('callouts'),
        locale=resolve_locale_for_file(args.file)
    )

    # Resolve format: CLI > frontmatter > config > default
    frontmatter_peek = poster.parse_frontmatter_only(args.file)
    fmt = resolve_format(args.markdown, args.raw, frontmatter_peek, config)

    print(f"Posting {args.file} to {config['site_url']}...")
    result = poster.post_to_wordpress(
        args.file,
        draft=args.draft,
        raw=(fmt == 'raw'),
        author_context=config.get('author_context'),
        verbose=args.verbose
    )

    if result is None:
        sys.exit(1)

    if result['success']:
        summary = {
            'success': True,
            'id': result['id'],
            'title': result['title'],
            'url': result['url']
        }
        # The post is live, but MSLS translation links failed to write. Surface
        # it in the machine-readable output and exit non-zero so automation
        # notices instead of treating the publish as fully complete (issue #11).
        msls_failures = result.get('msls_failures')
        if msls_failures:
            summary['msls_failures'] = msls_failures
            print(json.dumps(summary))
            sys.exit(1)
        print(json.dumps(summary))
    else:
        print(json.dumps({
            'success': False,
            'error': result['error']
        }))
        sys.exit(1)


if __name__ == '__main__':
    main()