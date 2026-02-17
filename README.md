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
  "ssh": {
    "key": "~/.ssh/my_key",
    "user": "ssh-user",
    "host": "192.168.1.1",
    "wp_path": "~/public_html"
  }
}
```

The `ssh` section is optional metadata for external tooling (not used by wp-post directly).

### Credential Validation
Running `wp-post my-file.md` without credentials will show helpful error messages:
- Lists exactly which credentials are missing
- Suggests `wp-post --init` for interactive setup
- Shows all configuration options with examples

## Frontmatter

```yaml
---
id: 123  # update existing post (omit to create new)
title: Post Title
slug: post-slug
status: draft|publish  # --draft flag overrides this
format: raw|markdown   # --markdown/--raw flags override this
excerpt: Post excerpt
author: username|user_id  # overrides config author_context
post_type: post|page|custom-post-type
template: template-name  # page template (for pages)
parent: 123  # parent post ID (for hierarchical types)
featured_image: path/to/image.jpg  # relative to cwd, or https://...
categories: [Cat1, Cat2]  # posts only, auto-created if missing
tags: [tag1, tag2]        # posts only, auto-created if missing
taxonomies:
  custom_taxonomy: Term Name  # any taxonomy, auto-created if missing
meta:
  custom_field: value
acf:
  field_name: value
rankmath:
  title: SEO Title           # shorthand keys: title, description, focus_keyword
  description: SEO desc      # full rank_math_* keys also accepted
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
- **Images**: `![alt](path)` - uploads to WordPress (re-uploads on each post)
- **Blockquotes**: `>` including multi-line
- **Code blocks**: ``` with syntax highlighting
- **Tables**: `| header | header |`
- **Horizontal rules**: `---`, `***`, `___`
- **Inline code**: `` `code` ``
- **Shortcodes**: `[gallery]` - passed through to WordPress

## Test Mode

Preview content without posting:

```bash
wp-post my-file.html --test
wp-post my-file.md --test --markdown
```

## Claude Code Skill

This repo includes a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) plugin with a `/wp-post` skill that teaches Claude how to publish and update posts using wp-post — including frontmatter authoring, format selection, and the create-then-update-local-file loop.

### Install

```bash
/plugin marketplace add ediblesites/wp-poster
/plugin install wp-poster@wp-poster
```

Then use `/wp-post` or just ask Claude to publish a file to WordPress.
