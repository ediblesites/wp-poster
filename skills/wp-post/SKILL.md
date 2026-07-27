---
name: wp-post
description: >
  Publish and update WordPress posts using the wp-post CLI tool.
  Use when the user wants to: create a new WordPress post from a markdown or HTML file,
  update an existing WordPress post, publish content to WordPress, draft a blog post
  for WordPress, or work with files that have wp-post YAML frontmatter.
  Also use when the user asks to "post this", "publish this", or "send to WordPress".
  Handles frontmatter authoring, format selection, automatic id writeback,
  and wp-post invocation.
allowed-tools:
  - Bash
  - Read
  - Edit
  - Write
  - Glob
  - Grep
---

# wp-post

Post files with YAML frontmatter to WordPress via REST API.

## Workflow

### 1. Determine create vs update

- If the file already has `id:` in frontmatter → this is an **update**. Proceed to step 3.
- If no `id:` → this is a **new post**. `id` and `slug` are written back automatically after creation (step 5).

### 2. Author the file

Write content with YAML frontmatter between `---` delimiters. `title` is required; all other fields are optional. For the complete field reference, see [references/frontmatter.md](references/frontmatter.md).

Minimal example:

```markdown
---
title: My New Post
categories: [News]
---
Content goes here.
```

### 3. Choose format and invoke

```bash
# Markdown content → Gutenberg blocks
wp-post file.md --markdown

# HTML or raw content → posted as-is (default)
wp-post file.html

# Preview without posting
wp-post file.md --test --markdown

# Post as draft regardless of frontmatter status
wp-post file.md --markdown --draft
```

Format resolution (first match wins): CLI flags → frontmatter `format:` → config `default_format` → raw.

Use `--test` before the real post when generating new content or converting markdown, to verify the output looks correct.

### 4. Images

All images are uploaded to the WordPress media library automatically.

- **Featured image**: set `featured_image:` in frontmatter to a local path or URL.
- **Inline images** (markdown mode only): `![alt](file.jpg)` and `![alt](url)` are uploaded and their URLs are rewritten to the WordPress copy. `![alt](url "caption")` adds a `<figcaption>`. HTML `<figure>`/`<img>` tags are also handled.
- Remote upload failure → original URL kept. Local file missing → image dropped.
- `--test` skips all uploads.

Images are deduplicated per-article against the media library: before uploading, the script looks up an existing attachment under the article's scoped filename and reuses it if found. Inline image URLs that already point at the target site are reused directly (the existing attachment is resolved by exact `source_url`, with no re-download or re-upload).

### 5. Embedded Gutenberg blocks (markdown mode)

Raw Gutenberg block markup can be embedded directly in markdown, the same way
HTML can be embedded in markdown. It passes through to WordPress verbatim:

```markdown
Regular markdown paragraph.

<!-- wp:cover {"url":"https://example.com/bg.jpg"} -->
<div class="wp-block-cover"><p>Cover content</p></div>
<!-- /wp:cover -->

More markdown.
```

- The opening `<!-- wp:... -->` comment must start at the beginning of a line.
- Nested blocks (`wp:columns`/`wp:column`, `wp:group`) and self-closing blocks
  (`<!-- wp:archives /-->`) are supported.
- Content inside the block is not processed: no markdown conversion, no image
  upload/rewrite. URLs in embedded blocks are the author's responsibility.
- An unclosed block is a fatal error (reported with its line number); the post
  is not created.
- Gutenberg markup inside fenced code blocks is left as code, not extracted.

### 6. Automatic id/slug writeback (new posts only)

When `wp-post` creates a new post (no `id:` in frontmatter), it automatically writes the returned `id` and resolved `slug` back into the file's frontmatter. This prevents duplicate posts on re-run.

No manual action is required. After a successful create, the file is updated in-place and `wp-post` prints `✓ Wrote id and slug back to <file>`.

If WordPress resolved a slug conflict (e.g. `my-post` → `my-post-2`), the `slug` field is updated to match.

### 7. Translation linking (MSLS multisite)

For WordPress multisite networks with MSLS, wp-post can automatically link
translation siblings.

Add `translation_set` to frontmatter to group posts across sites:

```yaml
---
title: About Us
translation_set: about-us
---
```

On every publish, wp-post checks if siblings with the same `translation_set`
exist on other sites (and have been published with an `id`). If so, it writes
the MSLS options to link all members and reads each one back to confirm it
persisted.

- `translation_set` is opt-in. Posts without it are standalone.
- Linking runs on every publish (create and update) and is idempotent, so a
  failed or drifted link write self-heals on the next publish - no manual fix.
- Each write is retried on transient failure; if a member still can't be linked
  the failure is reported (`msls_failures` in the JSON output) and `wp-post`
  exits non-zero, so automation notices instead of silently losing links.
- The first post in a set has nothing to link — linking occurs when the
  second (or later) sibling is published.

Set up a multisite project with `wp-post --init-network`. This writes a single
root `.wp-poster.json` holding shared credentials plus a `network.sites` map,
where each site entry carries `content_path`, `site_url`, `locale`, and
`blog_id`. No per-site config files are needed (older per-site
`.wp-poster.json` files are still honored as a fallback).

### 8. Clearing the cache

After publishing, the SpinupWP plugin purges the page cache on its own, so no
action is normally needed. Use `wp-post --purge` when a change bypassed that:

    wp-post --purge --file content/de/my-post/index.md   # one page
    wp-post --purge --site de                            # one site
    wp-post --purge --network                            # every site

Most importantly, run `--purge --site` or `--purge --network` after publishing
a post with `translation_set`. MSLS links are written in a way that does not
trigger WordPress's own cache invalidation, so sibling-language pages keep
serving a stale language switcher until purged.

Requires `wp_cli_alias` in `.wp-poster.json`.

## Configuration

wp-post finds credentials from (first match wins):

1. CLI flags: `--site-url`, `--username`, `--app-password`
2. Environment variables: `WP_SITE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD`
3. Config file `.wp-poster.json` (walks up from cwd, then `~/.wp-poster.json`, then `~/.config/wp-poster/config.json`)

Check active config: `wp-post --config-path`

If no credentials are configured, run `wp-post --init` for interactive setup.

- `wp_cli_alias` - required only for `--purge`. A value starting with `@` is a
  WP-CLI alias; anything else is used as a `wp --ssh=` target. Network projects
  read `network.wp_cli_alias` instead.

## Error handling

- If `wp-post` exits non-zero or returns `{"success": false, ...}`, report the error to the user. Do not retry automatically.
- If the user's file is missing `title:` in frontmatter, add it before invoking.
- If credentials are missing, suggest `wp-post --init` or the three config methods above.
