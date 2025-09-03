# WordPress Poster

Post markdown files with frontmatter to WordPress via REST API. Converts markdown to proper Gutenberg blocks.

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

# Post a markdown file
wp-post my-post.md

# Post as draft
wp-post my-post.md --draft

# Test mode - convert to Gutenberg blocks without posting
wp-post my-post.md --test
```

## Configuration

Three ways to configure:
1. **Interactive**: `wp-post --init` (creates `.wp-poster.json` in current directory)
2. **Environment variables**: `WP_SITE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD`
3. **Command line**: `--site-url`, `--username`, `--app-password`

## Frontmatter

```yaml
---
title: Post Title
slug: post-slug
status: draft|publish
excerpt: Post excerpt
post_type: post|page|custom-post-type
featured_image: image.jpg|https://example.com/image.jpg
categories: [Cat1, Cat2]  # posts only
tags: [tag1, tag2]        # posts only
taxonomies:
  custom_taxonomy: Term Name
meta:
  custom_field: value
acf:
  field_name: value
date: 2025-01-01T10:00:00
---
```

## Supported Markdown

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
Debug markdown-to-Gutenberg conversion without WordPress credentials:

```bash
# Test conversion without posting
wp-post my-file.md --test

# Shows frontmatter and generated Gutenberg blocks
# Useful for debugging formatting issues
```

### Full Integration Test
```bash
# Test all features (before install.sh)
./wp-post comprehensive-test.md

# After install.sh, can use globally:
wp-post comprehensive-test.md

# Check WordPress admin to verify Gutenberg blocks render correctly
```

## Recent Improvements

- **Fixed list generation**: Lists now properly group all items in a single block instead of creating separate blocks per item
- **Fixed content ordering**: Paragraphs now appear in correct order relative to lists and headings
- **Added test mode**: Use `--test` flag to preview Gutenberg blocks without posting to WordPress