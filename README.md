# WordPress Poster

Post files with frontmatter to WordPress via REST API.

## Installation

```bash
git clone https://github.com/adam-marash/wp-poster
cd wp-poster
./install.sh
```

## Usage

```bash
# First-time setup
wp-post --init

# Post a file (content posted as-is)
wp-post my-file.html

# Post as draft
wp-post my-file.html --draft

# Convert markdown to Gutenberg blocks
wp-post my-file.md --markdown

# Test mode - preview without posting
wp-post my-file.html --test

# Verbose mode - debug output
wp-post my-file.html --verbose
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

### Credential Validation
Running `wp-post my-file.md` without credentials will show helpful error messages:
- Lists exactly which credentials are missing
- Suggests `wp-post --init` for interactive setup
- Shows all configuration options with examples

## Frontmatter

```yaml
---
title: Post Title
slug: post-slug
status: draft|publish
excerpt: Post excerpt
author: username|user_id  # overrides config author_context
post_type: post|page|custom-post-type
template: template-name  # page template (for pages)
parent: 123  # parent post ID (for hierarchical types)
featured_image: image.jpg|https://example.com/image.jpg
categories: [Cat1, Cat2]  # posts only, auto-created if missing
tags: [tag1, tag2]        # posts only, auto-created if missing
taxonomies:
  custom_taxonomy: Term Name  # any taxonomy, auto-created if missing
meta:
  custom_field: value
acf:
  field_name: value
date: 2025-01-01T10:00:00
---
```

Config file supports `author_context` for default author (set via `--init`).

Use `--verbose` or `-v` for detailed debug output.

## Markdown Mode

Use `--markdown` to convert markdown files to Gutenberg blocks before posting.

```bash
wp-post --markdown my-file.md
wp-post --markdown --draft my-file.md
wp-post --markdown --test my-file.md  # preview conversion
```

### Supported Markdown

- **Headings**: `# ## ###`
- **Text**: **bold**, *italic*, ~~strikethrough~~
- **Lists**: ordered (1. 2. 3.) and unordered (- * +) with nesting
- **Links**: `[text](url)`
- **Images**: `![alt](path)` - uploads local/remote to WordPress
- **Blockquotes**: `>` including multi-line
- **Code blocks**: ``` with syntax highlighting
- **Tables**: `| header | header |`
- **Shortcodes**: `[gallery]` - passed through to WordPress

## Testing & Development

### Test Mode
Preview content without posting:

```bash
# Preview file content
wp-post my-file.html --test

# Preview markdown conversion
wp-post my-file.md --test --markdown
```

## Recent Improvements

- **Raw posting by default**: Content posted as-is; use `--markdown` for conversion to Gutenberg
- **Smart config discovery**: Walks up directory tree to find project configs; local overrides global
- **Author context**: Set default author in config; override per-post with `author` frontmatter
- **Page templates**: Use `template` frontmatter for page template selection
- **Hierarchical posts**: Use `parent` frontmatter for parent post ID
- **Verbose mode**: Use `--verbose` or `-v` for detailed debug output
- **Taxonomy auto-creation**: Categories, tags, and custom taxonomy terms are created if they don't exist
- **Config info on bare run**: Running `wp-post` without arguments shows config file discovery