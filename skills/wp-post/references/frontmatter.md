# Frontmatter Reference

## Complete schema

```yaml
---
title: Post Title              # REQUIRED - post will fail without this
id: 123                        # omit to create new; include to update existing
slug: post-slug                # URL slug; WordPress may alter on conflict
status: draft|publish          # default: publish; --draft flag overrides
format: raw|markdown           # see format resolution; --markdown/--raw override
excerpt: Post excerpt
date: 2025-01-01T10:00:00     # ISO 8601 publish date

author: username|user_id       # overrides config author_context
post_type: post|page|custom    # default: post
template: template-name        # page template (hierarchical types only)
parent: 123                    # parent post ID (hierarchical types only)

featured_image: path/to/img.jpg  # local path (relative to cwd) or https:// URL
                                 # uploaded to WordPress media library

categories: [Cat1, Cat2]      # posts only; auto-created if missing
tags: [tag1, tag2]             # posts only; auto-created if missing

taxonomies:                    # any custom taxonomy; terms auto-created
  custom_taxonomy: Term Name   # single term
  another_tax: [Term1, Term2]  # multiple terms

meta:                          # custom post meta
  custom_field: value

acf:                           # Advanced Custom Fields
  field_name: value

rankmath:                      # Rank Math SEO plugin
  title: SEO Title             # shorthand → rank_math_title
  description: SEO desc        # shorthand → rank_math_description
  focus_keyword: keyword       # shorthand → rank_math_focus_keyword
                               # full rank_math_* keys also accepted
---
```

## Field details

| Field            | Type          | Required | Notes                                                  |
|------------------|---------------|----------|--------------------------------------------------------|
| `title`          | string        | YES      | Post will not be created without it                    |
| `id`             | integer       | no       | Omit = create new post; present = update existing post |
| `slug`           | string        | no       | WordPress may resolve conflicts by appending `-2` etc  |
| `status`         | string        | no       | `draft` or `publish`; `--draft` flag overrides         |
| `format`         | string        | no       | `raw` or `markdown`; CLI flags override                |
| `excerpt`        | string        | no       |                                                        |
| `date`           | ISO 8601      | no       | Publish date                                           |
| `author`         | string or int | no       | Username string or numeric user ID                     |
| `post_type`      | string        | no       | `post`, `page`, or any custom post type slug           |
| `template`       | string        | no       | Only for pages/hierarchical types                      |
| `parent`         | integer       | no       | Only for hierarchical types                            |
| `featured_image` | string        | no       | Local file path or URL; uploaded to media library      |
| `categories`     | list          | no       | Posts only; auto-created if they don't exist           |
| `tags`           | list          | no       | Posts only; auto-created if they don't exist           |
| `taxonomies`     | map           | no       | Keys are taxonomy slugs; values are term(s)            |
| `meta`           | map           | no       | Arbitrary key-value pairs                              |
| `acf`            | map           | no       | ACF field name-value pairs                             |
| `rankmath`       | map           | no       | SEO meta; shorthand or full `rank_math_*` keys         |

## Format resolution (first match wins)

1. CLI flags (`--raw`, `--markdown`)
2. Frontmatter `format` field
3. Config `default_format` setting
4. Default: `raw`
