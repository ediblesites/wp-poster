# WordPress Poster

Post files with frontmatter to WordPress via REST API.

## Installation

```bash
git clone https://github.com/ediblesites/wp-poster
cd wp-poster
./install.sh
```

## Usage

```bash
# First-time setup (creates .wp-poster.json, tests connection)
wp-post --init

# Post a file (content posted without Gutenberg conversion)
wp-post my-file.html

# Post as draft (overrides frontmatter status)
wp-post my-file.html --draft

# Convert markdown to Gutenberg blocks
wp-post my-file.md --markdown

# Force raw posting (override format frontmatter)
wp-post my-file.md --raw

# Test mode - preview without posting
wp-post my-file.html --test

# Verbose mode - debug output
wp-post my-file.html --verbose

# Show active config file path
wp-post --config-path

# Clear the SpinupWP page cache
wp-post --purge --file my-file.md      # just that page
wp-post --purge --site de              # one site in a network
wp-post --purge --network              # every site in the network
```

## Configuration

Three ways to configure:
1. **Interactive**: `wp-post --init` (creates `.wp-poster.json` in current directory)
2. **Environment variables**: `WP_SITE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD`
3. **Command line**: `--site-url`, `--username`, `--app-password`

### Config File Discovery

Config files are searched in this order (first match wins):
1. **Local/project**: Walks up from current directory to find nearest `.wp-poster.json`
2. **User global**: `~/.wp-poster.json`
3. **XDG config**: `~/.config/wp-poster/config.json`
4. **App default**: Script directory `.wp-poster.json`

This means project-specific configs override global configs, and running from `/project/src/deep/` will find `/project/.wp-poster.json`.

### Config File Format

```json
{
  "site_url": "https://example.com",
  "username": "your-username",
  "app_password": "your-app-password",
  "author_context": "default-author",
  "default_format": "raw",
  "wp_cli_alias": "myhost/sites/example.com/files",
  "ssh": {
    "key": "~/.ssh/my_key",
    "user": "ssh-user",
    "host": "192.168.1.1",
    "wp_path": "~/public_html"
  }
}
```

The `ssh` section is optional metadata for external tooling (not used by wp-post directly).

`wp_cli_alias` is required for `--purge`, and network projects also use it for
MSLS translation linking. A value starting with `@` is a WP-CLI alias resolved
through `~/.wp-cli/config.yml`; anything else is used as a `wp --ssh=` target,
which needs no WP-CLI config at all - but only `--purge` understands that
form. MSLS translation linking passes the alias straight to `wp` and requires
the `@alias` form; an ssh target there will break translation linking even
though `--purge` keeps working. Network projects read `wp_cli_alias` from
`network.wp_cli_alias` instead, where it already exists.

For `--purge --file`, config is resolved by walking up from the target file,
not from the working directory, so purging a file in another project always
uses that project's configuration.

### Credential Validation
Running `wp-post my-file.md` without credentials will show helpful error messages:
- Lists exactly which credentials are missing
- Suggests `wp-post --init` for interactive setup
- Shows all configuration options with examples

## Frontmatter

```yaml
---
id: 123                            # update existing post (omit to create new)
title: Post Title
slug: post-slug
status: draft|publish              # --draft flag overrides this
format: raw|markdown               # --markdown/--raw flags override this
excerpt: Post excerpt
author: username|user_id           # overrides config author_context
post_type: post|page|custom-post-type
template: template-name            # page template (for pages)
parent: 123                        # parent post ID (for hierarchical types)
featured_image: path/to/image.jpg  # relative to cwd, or https://...
categories: [Cat1, Cat2]           # posts only, auto-created if missing
tags: [tag1, tag2]                 # posts only, auto-created if missing
taxonomies:
  custom_taxonomy: Term Name       # any taxonomy, auto-created if missing
meta:
  custom_field: value
acf:
  field_name: value
rankmath:
  title: SEO Title                 # shorthand keys: title, description, focus_keyword
  description: SEO desc            # full rank_math_* keys also accepted
  focus_keyword: keyword
date: 2025-01-01T10:00:00
---
```

Config file supports `author_context` for default author (set via `--init`).

Use `--verbose` or `-v` for detailed debug output.

## Format

Content is posted raw by default. Use `format` frontmatter or `--markdown` flag for Gutenberg conversion.

### Precedence

Command line flags override frontmatter, which overrides config file defaults:

| Source | Example | Notes |
|--------|---------|-------|
| Default | raw | content posted as-is |
| Config | `"default_format": "markdown"` | set in `.wp-poster.json` |
| Frontmatter | `format: markdown` | per-file setting |
| CLI | `--markdown` / `--raw` | overrides all above |

```bash
# File has format: markdown, but post raw anyway
wp-post my-file.md --raw

# File has no format, convert to Gutenberg
wp-post my-file.md --markdown

# Let frontmatter decide
wp-post my-file.md
```

### Supported Markdown

- **Headings**: `# ## ###`
- **Text**: **bold**, *italic*, ~~strikethrough~~
- **Lists**: ordered (1. 2. 3.) and unordered (- * +) with nesting
- **Links**: `[text](url)`
- **Images**: `![alt](path)` and `![alt](url "caption")` — see [Images](#images) below
- **Blockquotes**: `>` including multi-line
- **Code blocks**: ``` with syntax highlighting
- **Tables**: `| header | header |`
- **Horizontal rules**: `---`, `***`, `___`
- **Inline code**: `` `code` ``
- **Shortcodes**: `[gallery]` - passed through to WordPress
- **Embedded Gutenberg blocks**: raw `<!-- wp:... -->` markup - passed through verbatim, see below

### Embedded Gutenberg blocks

Raw Gutenberg block markup can be embedded in markdown, the same way HTML can be embedded in markdown:

```markdown
Regular markdown paragraph.

<!-- wp:cover {"url":"https://example.com/bg.jpg"} -->
<div class="wp-block-cover"><p>Cover content</p></div>
<!-- /wp:cover -->

More markdown.
```

Rules:

- The opening `<!-- wp:... -->` comment must start at the beginning of a line.
- Nested container blocks (`wp:columns`/`wp:column`, `wp:group`) and self-closing blocks (`<!-- wp:archives /-->`) are supported.
- Content inside an embedded block is not processed: no markdown conversion, no escaping, and no image upload/rewrite. URLs inside embedded blocks are the author's responsibility.
- An unclosed block is a fatal error reported with its file line number; the post is not created.
- Gutenberg markup inside fenced code blocks is shown as code, not extracted.

## Images

All images are uploaded to the WordPress media library — both the `featured_image` frontmatter field and inline images in markdown mode.

### Featured image

Set `featured_image` in frontmatter to a local file path (relative to cwd) or a remote URL. The file is uploaded and set as the post thumbnail.

### Inline images (markdown mode only)

Inline images in the post body are uploaded and their URLs are rewritten to point to the WordPress media copy. Supported syntaxes:

| Syntax                            | Behavior                                          |
|-----------------------------------|---------------------------------------------------|
| `![alt](local.jpg)`              | Local file uploaded to media library               |
| `![alt](https://example.com/img)`| Remote URL downloaded and re-uploaded (unless already on this site - see below) |
| `![alt](url "caption text")`     | Caption becomes a `<figcaption>` on the image block|
| `<figure><img src="..."></figure>`| HTML image tags also detected and uploaded         |
| `<img src="...">`                | Standalone img tags handled the same way           |

**Failure behavior:**
- Remote URL upload fails → original URL is kept as-is
- Local file missing or upload fails → image is dropped from output

All uploaded images become Gutenberg `wp:image` blocks (center-aligned, full size). When a caption is present, it appears as a `<figcaption>`.

### Media library dedup

Each article publishes its media into a per-article namespace in the WordPress media library. Before uploading, the script queries for an existing attachment under that namespace; if a match is found it is reused, so republishing a post does **not** create duplicate media or trigger WordPress's `image-1.jpg`, `image-2.jpg` filename suffixing.

**How the namespace is derived:** the markdown file's parent directory basename, sanitized to slug form. For `content/old-tablet-bedtime-routine-display/index.md` the scope is `old-tablet-bedtime-routine-display`. For markdown files at the project root with no meaningful parent directory, the markdown filename stem is used as a fallback. The scope becomes a prefix on every image uploaded for that article: `hero.webp` from that article uploads as `old-tablet-bedtime-routine-display-hero.webp`. Inline images are scoped the same way as the featured image.

The lookup uses `GET /wp/v2/media?slug=<scope>-<basename>` and verifies that a candidate's `source_url` ends with the exact scoped filename, so a `foo.jpg` upload will not be confused with an existing `foo.png`. Cross-article filename collisions are impossible because the scope is part of the slug.

**Images already hosted on this site:** when an image URL's host matches the target site, the script skips the download/upload entirely and resolves the existing attachment by exact `source_url` match (`GET /wp/v2/media?slug=<basename>`). This applies regardless of article scope, so referencing a WordPress media URL directly in your markdown reuses the existing attachment instead of duplicating it. A same-basename image at a different upload path is not aliased; if no attachment matches exactly, it falls back to the normal download/upload path.

**Caveats:**
- Each *local* image gets its own per-article copy, even if two articles intentionally reference the same source file (e.g. a site logo). For intentional cross-article sharing, reference the WordPress media URL directly in your markdown - same-host URLs reuse the existing attachment (see above) rather than re-uploading.
- Renaming an article's parent directory changes the scope, so the next publish uploads a fresh scoped attachment - the prior one becomes orphaned in the media library.
- Sources whose URL has no usable filename (e.g. `https://picsum.photos/400/300`) cannot be scoped or deduped and will upload fresh on each run.
- Calling `upload_media` directly without going through `post_to_wordpress` (no article context) intentionally skips the dedup query entirely - filename-only dedup is unsafe across articles.

`--test` mode skips all uploads.

## Test Mode

Preview content without posting:

```bash
wp-post my-file.html --test
wp-post my-file.md --test --markdown
```

## Cache purging

`--purge` clears the SpinupWP page cache. It requires exactly one scope:

| Scope                 | Clears                                            |
|-----------------------|---------------------------------------------------|
| `--file <path>`       | the single page published from that file          |
| `--site [key]`        | one site (network key, or bare for a single site) |
| `--network`           | every site in the network                         |

`--file`, `--site`, and `--network` are purge-scope selectors: they are only
valid together with `--purge`. Passing one without `--purge` is a hard error
(exit 1) rather than being silently ignored, since `--site` also reads as an
abbreviation of the unrelated `--site-url` flag and misreading it that way
could publish to the wrong site.

It never runs automatically - the SpinupWP plugin already purges on ordinary
content updates. Reach for it when a change bypassed that, most notably after
MSLS translation linking: those links are written with `wp eval` and
`update_option`, which never fires `save_post`, so the sibling-language pages
keep serving a stale language switcher. `--purge --file` clears only the page
you name, so use `--site` or `--network` after linking translations.

Add `--test` to print the commands without running them. A failure on one site
is reported and the remaining sites are still purged; the exit code is 1 if any
target failed.

Cloudflare is deliberately not purged. These sites serve
`cf-cache-status: DYNAMIC` for HTML, so there is nothing cached at the edge to
clear; see `docs/superpowers/specs/2026-07-27-cache-purge-design.md`.

## Claude Code Skill

This repo includes a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill that teaches Claude how to publish and update posts using wp-post - covering frontmatter authoring, format selection, callouts, and the create-then-update-local-file loop.

`./install.sh` installs it to `~/.claude/skills/wp-post/` alongside the CLI, so there is one install step for both. Then use `/wp-post`, or just ask Claude to publish a file to WordPress.

The skill is copied, not symlinked. Editing `skills/wp-post/SKILL.md` does not change the installed copy until you re-run `./install.sh`.
