---
name: wp-post
description: >
  Publish and update WordPress posts using the wp-post CLI tool.
  Use when the user wants to: create a new WordPress post from a markdown or HTML file,
  update an existing WordPress post, publish content to WordPress, draft a blog post
  for WordPress, or work with files that have wp-post YAML frontmatter.
  Also use when the user asks to "post this", "publish this", or "send to WordPress".
  Handles frontmatter authoring, format selection, the create→update-local-file loop,
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
- If no `id:` → this is a **new post**. The post-publish loop (step 4) is required.

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

Images are re-uploaded on each post (no deduplication across runs).

### 5. Post-publish loop (new posts only)

This step is **critical** for new posts (no `id:` in frontmatter).

After `wp-post` succeeds, it prints JSON to stdout:

```json
{"success": true, "id": 456, "title": "My New Post", "url": "https://example.com/my-new-post/"}
```

Immediately after a successful create:

1. **Extract `id`** from the JSON output.
2. **Extract the actual slug** from the `url` field (the path segment before the trailing slash).
3. **Update the local file's frontmatter**: add `id: <id>` and correct `slug:` if WordPress resolved a conflict (e.g. you wrote `slug: my-post` but the URL shows `/my-post-2/`).
4. Do NOT skip this step. Without it, the next `wp-post` run will create a **duplicate** post instead of updating.

Example — before posting:

```yaml
---
title: My New Post
slug: my-post
categories: [News]
---
```

After posting (id 456 returned, slug was conflict-resolved):

```yaml
---
title: My New Post
id: 456
slug: my-post-2
categories: [News]
---
```

Place `id` right after `title` for readability.

## Configuration

wp-post finds credentials from (first match wins):

1. CLI flags: `--site-url`, `--username`, `--app-password`
2. Environment variables: `WP_SITE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD`
3. Config file `.wp-poster.json` (walks up from cwd, then `~/.wp-poster.json`, then `~/.config/wp-poster/config.json`)

Check active config: `wp-post --config-path`

If no credentials are configured, run `wp-post --init` for interactive setup.

## Error handling

- If `wp-post` exits non-zero or returns `{"success": false, ...}`, report the error to the user. Do not retry automatically.
- If the user's file is missing `title:` in frontmatter, add it before invoking.
- If credentials are missing, suggest `wp-post --init` or the three config methods above.
