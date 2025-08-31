---
title: My First WordPress Post from Markdown
slug: my-first-markdown-post
status: draft
excerpt: This is an example post created from a markdown file with frontmatter
categories:
  - Technology
  - Tutorial
tags:
  - markdown
  - wordpress
  - automation
date: 2025-08-31T10:00:00
---

# Introduction

This is an example markdown file that demonstrates how to post to WordPress using frontmatter metadata.

## Features

The wp-poster tool supports:

- **Frontmatter parsing** - Define post metadata in YAML format
- **Automatic HTML conversion** - Markdown is converted to WordPress-compatible HTML
- **Category management** - Creates categories if they don't exist
- **Tag management** - Creates tags automatically
- **Draft/Publish control** - Set post status via frontmatter or command line

## Code Example

Here's how to use the tool:

```bash
# Post a markdown file
wp-post example-post.md

# Post as draft (overrides frontmatter)
wp-post example-post.md --draft

# Specify credentials via command line
wp-post example-post.md --site-url https://mysite.com --username admin --app-password "xxxx xxxx xxxx xxxx"
```

## Configuration

You can configure the tool in three ways:

1. **Environment variables:**
   ```bash
   export WP_SITE_URL="https://your-site.com"
   export WP_USERNAME="your-username"
   export WP_APP_PASSWORD="your-app-password"
   ```

2. **Config file** (`~/.wp-poster.json`):
   ```json
   {
     "site_url": "https://your-site.com",
     "username": "your-username",
     "app_password": "your-app-password"
   }
   ```

3. **Command line arguments** (see example above)

## Tables Support

| Feature | Supported |
|---------|-----------|
| Markdown | ✓ |
| Frontmatter | ✓ |
| Categories | ✓ |
| Tags | ✓ |
| Featured Images | ✓ |

## Conclusion

This tool makes it easy to write blog posts in markdown and publish them to WordPress!