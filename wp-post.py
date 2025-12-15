#!/usr/bin/env python3
"""
WordPress Markdown Poster
Posts markdown files with frontmatter to WordPress via REST API
"""

import warnings
warnings.filterwarnings("ignore", message="urllib3")
warnings.filterwarnings("ignore", category=DeprecationWarning)

import argparse
import json
import os
import sys
from pathlib import Path
import requests
import yaml
from datetime import datetime
import getpass

from gutenberg import GutenbergConverter


class WordPressPost:
    def __init__(self, site_url, username, app_password):
        self.site_url = site_url.rstrip('/')
        self.auth = (username, app_password)
        self.api_url = f"{self.site_url}/wp-json/wp/v2"
        self.uploaded_media = {}  # Track uploaded media: {url: media_id}
        
    def parse_frontmatter_only(self, filepath):
        """Parse just the frontmatter without processing content"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                return yaml.safe_load(parts[1]) or {}
        return {}

    def parse_markdown_file(self, filepath):
        """Parse markdown file with frontmatter and convert to Gutenberg blocks"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Split frontmatter and content
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1])
                markdown_content = parts[2].strip()
            else:
                frontmatter = {}
                markdown_content = content
        else:
            frontmatter = {}
            markdown_content = content

        # Convert markdown to Gutenberg blocks using image handler
        converter = GutenbergConverter(image_handler=self._handle_image)
        blocks_content = converter.convert(markdown_content)

        return frontmatter, blocks_content

    def _handle_image(self, image_url):
        """Handle image URL - upload and return (final_url, media_id)"""
        final_url = self.process_image_url(image_url)
        if final_url:
            media_id = self.uploaded_media.get(final_url)
            return (final_url, media_id)
        return (None, None)

    def parse_raw_file(self, filepath):
        """Parse file with frontmatter but keep content as-is (no markdown conversion)"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Split frontmatter and content
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1])
                raw_content = parts[2].strip()
            else:
                frontmatter = {}
                raw_content = content
        else:
            frontmatter = {}
            raw_content = content

        return frontmatter, raw_content

    def process_image_url(self, image_path_or_url):
        """Process image URL - upload local files and remote URLs to WordPress media library"""
        
        # If it's already a remote URL, upload it to WordPress
        if image_path_or_url.startswith(('http://', 'https://')):
            media_id = self.upload_media(image_path_or_url)
            if media_id:
                # Get the WordPress media URL
                try:
                    media_response = requests.get(f"{self.api_url}/media/{media_id}", auth=self.auth, timeout=30)
                    if media_response.status_code == 200:
                        media_url = media_response.json()['source_url']
                        self.uploaded_media[media_url] = media_id  # Track the media ID
                        print(f"✓ Downloaded and uploaded remote image: {image_path_or_url} → {media_url}")
                        return media_url
                except (requests.RequestException, KeyError, ValueError) as e:
                    print(f"⚠ Error getting media URL: {e}")
            
            # If upload failed, fall back to original URL
            print(f"⚠ Failed to upload remote image, using original URL: {image_path_or_url}")
            return image_path_or_url
        
        # Local file - upload to WordPress
        else:
            # Check if file exists
            if os.path.exists(image_path_or_url):
                media_id = self.upload_media(image_path_or_url)
                if media_id:
                    # Get the WordPress media URL
                    try:
                        media_response = requests.get(f"{self.api_url}/media/{media_id}", auth=self.auth, timeout=30)
                        if media_response.status_code == 200:
                            media_url = media_response.json()['source_url']
                            self.uploaded_media[media_url] = media_id  # Track the media ID
                            print(f"✓ Uploaded inline image: {image_path_or_url} → {media_url}")
                            return media_url
                    except (requests.RequestException, KeyError, ValueError) as e:
                        print(f"⚠ Error getting media URL: {e}")
                
                print(f"✗ Failed to upload inline image: {image_path_or_url}")
                return None
            else:
                print(f"✗ Inline image file not found: {image_path_or_url}")
                return None

    def get_categories(self):
        """Get all categories from WordPress, indexed by both name and slug"""
        response = requests.get(
            f"{self.api_url}/categories",
            auth=self.auth,
            params={'per_page': 100},
            timeout=30
        )
        if response.status_code == 200:
            cats = {}
            for cat in response.json():
                cats[cat['name']] = cat['id']
                cats[cat['slug']] = cat['id']
            return cats
        return {}

    def get_tags(self):
        """Get all tags from WordPress, indexed by both name and slug"""
        response = requests.get(
            f"{self.api_url}/tags",
            auth=self.auth,
            params={'per_page': 100},
            timeout=30
        )
        if response.status_code == 200:
            tags = {}
            for tag in response.json():
                tags[tag['name']] = tag['id']
                tags[tag['slug']] = tag['id']
            return tags
        return {}
    
    def create_category(self, name):
        """Create a new category"""
        data = {'name': name}
        response = requests.post(f"{self.api_url}/categories", auth=self.auth, json=data, timeout=30)
        if response.status_code == 201:
            return response.json()['id']
        return None
    
    def create_tag(self, name):
        """Create a new tag"""
        data = {'name': name}
        response = requests.post(f"{self.api_url}/tags", auth=self.auth, json=data, timeout=30)
        if response.status_code == 201:
            return response.json()['id']
        return None
    
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
        response = requests.get(
            f"{self.api_url}/{rest_base}",
            auth=self.auth,
            params={'per_page': 100},
            timeout=30
        )
        if response.status_code == 200:
            terms = {}
            for term in response.json():
                terms[term['name']] = term['id']
                terms[term['slug']] = term['id']
            return terms
        return {}

    def create_taxonomy_term(self, taxonomy, name):
        """Create a new term in a taxonomy"""
        rest_base = self.get_taxonomy_rest_base(taxonomy)
        data = {'name': name}
        response = requests.post(f"{self.api_url}/{rest_base}", auth=self.auth, json=data, timeout=30)
        if response.status_code == 201:
            return response.json()['id']
        return None

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

    def post_to_wordpress(self, filepath, draft=False, raw=False, author_context=None, verbose=False):
        """Post file to WordPress"""
        if raw:
            frontmatter, content = self.parse_raw_file(filepath)
            if verbose:
                print(f"[verbose] Parsed raw file: {filepath}")
        else:
            frontmatter, content = self.parse_markdown_file(filepath)
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

        # Prepare post data
        post_data = {
            'title': frontmatter.get('title', Path(filepath).stem),
            'content': content,
            'status': 'draft' if draft else frontmatter.get('status', 'publish'),
            'slug': frontmatter.get('slug', ''),
            'excerpt': frontmatter.get('excerpt', ''),
        }
        
        # Handle date
        if 'date' in frontmatter:
            if isinstance(frontmatter['date'], datetime):
                post_data['date'] = frontmatter['date'].isoformat()
            else:
                post_data['date'] = frontmatter['date']

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
        
        # Handle featured image
        if 'featured_image' in frontmatter:
            media_id = self.upload_media(frontmatter['featured_image'])
            if media_id:
                post_data['featured_media'] = media_id
        
        # Create or update post
        if verbose:
            debug_data = {k: v for k, v in post_data.items() if k != 'content'}
            debug_data['content'] = f"[{len(post_data.get('content', ''))} chars]"
            print(f"[verbose] Post data: {json.dumps(debug_data, indent=2, default=str)}")

        if 'id' in frontmatter:
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
            return {
                'success': True,
                'id': post['id'],
                'url': post['link'],
                'title': post['title']['rendered']
            }
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
    
    def upload_media(self, filepath_or_url):
        """Upload media file to WordPress from local file or remote URL"""
        # Check if it's a URL
        if filepath_or_url.startswith(('http://', 'https://')):
            return self.upload_media_from_url(filepath_or_url)
        else:
            return self.upload_media_from_file(filepath_or_url)
    
    def upload_media_from_url(self, url):
        """Upload media from remote URL to WordPress"""
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
            return media_info['id']
        else:
            print(f"✗ Failed to upload featured image: {upload_response.status_code} - {upload_response.text}")
            return None
    
    def upload_media_from_file(self, filepath):
        """Upload media from local file to WordPress"""
        if not os.path.exists(filepath):
            print(f"Warning: Featured image file '{filepath}' not found")
            return None
            
        with open(filepath, 'rb') as f:
            media_data = f.read()
        
        filename = os.path.basename(filepath)
        
        # Determine content type based on file extension
        ext = os.path.splitext(filename)[1].lower()
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
        
        content_type = content_type_map.get(ext, 'application/octet-stream')
        
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
            return media_info['id']
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


def main():
    parser = argparse.ArgumentParser(
        description='Post files with frontmatter to WordPress'
    )
    parser.add_argument('file', nargs='?', help='File to post')
    parser.add_argument('--site-url', help='WordPress site URL')
    parser.add_argument('--username', help='WordPress username')
    parser.add_argument('--app-password', help='WordPress application password')
    parser.add_argument('--draft', action='store_true', help='Post as draft')
    parser.add_argument('--init', action='store_true', help='Initialize configuration interactively')
    parser.add_argument('--config-path', action='store_true', help='Print path to active config file')
    parser.add_argument('--test', action='store_true', help='Test mode: preview content without posting')
    parser.add_argument('--markdown', action='store_true', help='Convert markdown to Gutenberg blocks')
    parser.add_argument('--raw', action='store_true', help='Post content as-is (override format frontmatter)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed debug output')
    
    args = parser.parse_args()
    
    # Handle --init flag
    if args.init:
        sys.exit(0 if init_config() else 1)

    # Handle --config-path flag
    if args.config_path:
        config_paths = get_config_paths()
        for name, path, exists in config_paths:
            if exists:
                print(path)
                sys.exit(0)
        print("No config file found", file=sys.stderr)
        sys.exit(1)

    # Handle --test flag (test mode doesn't need WordPress credentials)
    if args.test:
        if not args.file:
            parser.print_help()
            sys.exit(1)

        if not os.path.exists(args.file):
            print(f"Error: File '{args.file}' not found")
            sys.exit(1)

        # Create a dummy poster instance just for parsing (no image uploads in test mode)
        poster = WordPressPost('https://example.com', 'user', 'pass')

        # Resolve format: CLI > frontmatter > config > default
        config = load_config()
        frontmatter_peek = poster.parse_frontmatter_only(args.file)
        fmt = resolve_format(args.markdown, args.raw, frontmatter_peek, config)

        if fmt == 'markdown':
            print(f"Converting {args.file} to Gutenberg blocks...")
            frontmatter, content = poster.parse_markdown_file(args.file)

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
    
    # Create poster instance and post
    poster = WordPressPost(
        config['site_url'],
        config['username'],
        config['app_password']
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
    
    if result['success']:
        print(json.dumps({
            'success': True,
            'id': result['id'],
            'title': result['title'],
            'url': result['url']
        }))
    else:
        print(json.dumps({
            'success': False,
            'error': result['error']
        }))
        sys.exit(1)


if __name__ == '__main__':
    main()