# Design: markdown callouts

Date: 2026-07-31

Eight callout types authored as GFM blockquotes and rendered as core
Gutenberg blocks coloured from the active theme's palette.

## Motivation

wp-poster already renders the five GFM admonitions (`[!NOTE]`, `[!TIP]`,
`[!IMPORTANT]`, `[!WARNING]`, `[!CAUTION]`) as `wp:quote` blocks with
hardcoded GitHub hex colours. Two problems:

1. The colours are fixed, so a callout never matches the site it lands on.
2. The sibling project `tamara` has three further callout types that carry
   real editorial weight - a key-points summary, an FAQ accordion, and a
   related-post card - and there is no equivalent here.

This design ports all three, re-bases the existing five on theme colours,
and makes labels, icons, and colours configurable per project.

## Findings that shaped this design

Measured against `dashpadd.com` (Ollie theme) on 2026-07-31, not assumed.

### Ollie has no semantic hues

Ollie's `theme.json` declares `"defaultPalette": false` and an 11-slot
semantic palette:

| Slug                 | Role           |
|----------------------|----------------|
| `primary`            | Brand          |
| `primary-accent`     | Brand accent   |
| `primary-alt`        | Brand alt      |
| `primary-alt-accent` | Brand alt accent |
| `main`               | Contrast       |
| `main-accent`        | Contrast accent |
| `base`               | Base           |
| `secondary`          | Base accent    |
| `tertiary`           | Tint           |
| `border-light`       | Border base    |
| `border-dark`        | Border contrast |

There is no red, amber, or green. `dashpadd.com` currently *does* serve
`.has-vivid-red-color` and friends, because a Global Styles override
re-enabled the core default palette, but a clean Ollie install would not.
Type differentiation therefore cannot rely on hue; it relies on icon and
label, with hue available to any project that configures it.

### Ollie already styles the blocks we want

`core/quote` gets a 5px left border in `primary`; `core/details` gets a
bold `summary`. Both are dressed by the theme without wp-poster shipping
any CSS.

### Editor validity constrains the markup

Gutenberg validates stored markup by re-deriving it from block attributes.
Any inline style the block cannot produce from its own attributes is
flagged as invalid content on edit. This rules out CSS fallback chains
like `var(--wp--preset--color--primary, #cf2e2e)`: Gutenberg serialises a
preset reference as a bare `var(--wp--preset--color--primary)` with no
fallback. The fallback therefore lives in configuration instead - see
"Colour resolution" below.

## Decisions

| Question             | Decision                                                   |
|----------------------|------------------------------------------------------------|
| Colour source        | Theme palette slugs by default, hex literals by config     |
| Type differentiation | Icon plus label, not hue                                   |
| FAQ rendering        | `core/details` accordion, `<h3>` inside `<summary>`        |
| FAQ schema           | None. Google restricted FAQ rich results to authoritative gov/health sites in Aug 2023, and Rank Math is installed if schema is ever wanted |
| Bookmark card        | Resolved through the REST API at convert time              |
| Icons                | Inline SVG retained, with post-publish stripping detection |
| Demo                 | Published post on dashpadd.com                             |

## Module structure

A new `callouts.py` holds everything callout-specific. `gutenberg.py`
gains only wiring, following the `image_handler` precedent already in
place at `wp-post.py:98`.

```
callouts.py
  CALLOUT_TYPES          tuple of the eight recognised type names
  DEFAULT_CONFIG         built-in labels, icons, and colour slugs
  merge_config(user)     user config merged over the defaults
  callout_plugin(config, bookmark_resolver)  -> mistune plugin

gutenberg.py
  GutenbergConverter(image_handler=None,
                     callout_config=None,
                     bookmark_resolver=None)

wp-post.py
  reads the `callouts` key from .wp-poster.json
  passes self._resolve_bookmark as the resolver
```

`callout_plugin` is a factory rather than a plain plugin because it needs
per-project configuration and a resolver. The converter is already
constructed once per file, so construction-time configuration is enough.

## Syntax

All eight types are GFM blockquote callouts, matching the existing five:

```markdown
> [!NOTE]
> Body text, which may contain any block content.

> [!SUMMARY]
> - First key point
> - Second key point

> [!FAQ]
> **How long does setup take?**
> About ten minutes.
>
> **Is there a free tier?**
> Yes, up to 100 posts.

> [!BOOKMARK]
> /my-other-post/
```

Type matching stays case-insensitive.

## Parsing

The existing blockquote intercept in `_parse_gfm_admonition` is generalised
and moved to `callouts.py`. It widens the type pattern to all eight names
and emits a `callout` token carrying `attrs["name"]`.

Bodies are handled per type:

- **note, tip, important, warning, caution, summary** - body parsed as
  ordinary child blocks. Lists, code, tables, and images all work.
- **faq** - body split on lines of the form `**Question**`. Each pair
  emits a `faq_item` token with `attrs["question"]` and the answer parsed
  as child blocks, so answers may contain any block content. Text before
  the first `**Question**` line is dropped with a stderr warning.
- **bookmark** - body captured as a raw target string; no children.

## Colour resolution

Each type's `color` config value is either a palette slug or a hex
literal, and each serialises to editor-valid markup:

| Config value | Block attribute                        | Rendered style                                        |
|--------------|----------------------------------------|-------------------------------------------------------|
| `"primary"`  | `"color":"var:preset\|color\|primary"` | `border-left-color:var(--wp--preset--color--primary)` |
| `"#cf2e2e"`  | `"color":"#cf2e2e"`                    | `border-left-color:#cf2e2e`                           |

A value is treated as hex when it matches `^#[0-9a-fA-F]{3,8}$`; anything
else is a slug. A slug the theme does not define resolves to nothing, so
the box simply loses that colour rather than breaking - which is why the
defaults target slugs Ollie actually has.

The same rule applies to the group's `background` value.

## Block markup

### The six simple types

One `core/group`, one label paragraph, then the body:

```html
<!-- wp:group {"className":"is-callout is-callout-note","backgroundColor":"tertiary","style":{"border":{"left":{"color":"var:preset|color|primary","width":"4px"}},"spacing":{"padding":{"top":"var:preset|spacing|small","right":"var:preset|spacing|small","bottom":"var:preset|spacing|small","left":"var:preset|spacing|small"}}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group is-callout is-callout-note has-tertiary-background-color has-background" style="border-left-color:var(--wp--preset--color--primary);border-left-width:4px;padding-top:var(--wp--preset--spacing--small);...">
<!-- wp:paragraph {"className":"is-callout-label","style":{"color":{"text":"var:preset|color|primary"}}} -->
<p class="is-callout-label has-text-color" style="color:var(--wp--preset--color--primary)"><strong><svg ... fill="currentColor">...</svg> Note</strong></p>
<!-- /wp:paragraph -->
…body blocks…
</div>
<!-- /wp:group -->
```

Icons keep their existing inline SVG paths but change `fill` from a
hardcoded hex to `currentColor`, so the icon inherits the label
paragraph's palette colour.

The `is-callout` and `is-callout-<type>` classes are the extension point:
a theme that wants per-type hues adds CSS against them without wp-poster
changing.

### FAQ

The same group wrapper and label, then one `core/details` per pair:

```html
<!-- wp:details -->
<details class="wp-block-details">
<summary><h3 style="display:inline;margin:0">How long does setup take?</h3></summary>
<!-- wp:paragraph -->
<p>About ten minutes.</p>
<!-- /wp:paragraph -->
</details>
<!-- /wp:details -->
```

HTML5 permits heading content in `<summary>`. The inline display and zero
margin keep the heading on the disclosure marker's line with no vertical
gap.

### Bookmark

With a featured image, one `core/media-text` - a single primitive that is
responsive and stacks on mobile:

```html
<!-- wp:media-text {"mediaId":123,"mediaType":"image","mediaWidth":30,"className":"is-callout is-callout-bookmark"} -->
<div class="wp-block-media-text is-stacked-on-mobile is-callout is-callout-bookmark">
<figure class="wp-block-media-text__media"><img src="…" alt="…" class="wp-image-123"/></figure>
<div class="wp-block-media-text__content">
<!-- wp:paragraph {"className":"is-callout-label", …} --><p …><strong>… Read next</strong></p><!-- /wp:paragraph -->
<!-- wp:heading {"level":3} --><h3><a href="…">My Other Post</a></h3><!-- /wp:heading -->
<!-- wp:paragraph --><p>The excerpt…</p><!-- /wp:paragraph -->
</div></div>
<!-- /wp:media-text -->
```

Without a featured image, the standard group wrapper holding the same
label, linked heading, and excerpt.

## Bookmark resolution

`wp-post.py` supplies `_resolve_bookmark(target)`:

1. Normalise `target` - a bare slug, a `/path/`, or a full URL all reduce
   to a slug (last non-empty path segment).
2. `GET /wp/v2/posts?slug=<slug>&_embed`, then `/wp/v2/pages` if empty.
3. Return `{title, link, excerpt, image_url, image_id}` or `None`.
   Excerpt is stripped of HTML tags and of WordPress's `[…]` more-marker,
   then truncated at 200 characters on a word boundary.
4. Results cached per run in a dict on the `WordPressPost` instance, so a
   post linking the same target twice makes one request.

The featured image is already hosted on the target site, so it is
referenced by URL and attachment id - never re-downloaded or re-uploaded.

Under `--test` no resolver is passed, matching how `--test` already skips
image uploads.

## Error handling

No callout failure ever fails a publish.

| Condition                             | Behaviour                                                    |
|---------------------------------------|--------------------------------------------------------------|
| Bookmark target not found             | Styled link card using the raw target, warning on stderr     |
| Bookmark lookup raises / times out    | Same fallback, warning on stderr                             |
| Resolver absent (`--test`)            | Styled link card, no warning                                 |
| FAQ body with no `**Question**` lines | Body rendered as ordinary callout content, warning on stderr |
| Unknown colour slug                   | Silent - the theme simply has no such colour                 |
| Config naming an unknown type         | Ignored, warning on stderr                                   |

## SVG stripping detection

WordPress runs `wp_filter_post_kses` for any user lacking the
`unfiltered_html` capability, which on multisite is super-admins only.
That strips `<svg>` from post content on save. Rather than avoid SVG, the
publish path detects the loss and says so.

In `post_to_wordpress`, after a 200/201 response (`wp-post.py:532`):

- If the content sent contained `<svg` and `post['content']['rendered']`
  does not, print one warning to stderr naming the likely cause and the
  fix - grant `unfiltered_html` to the publishing user.
- If `content.rendered` is missing or empty, skip the check. An absent
  field is not evidence of stripping.

One warning per publish, not one per callout. The post still succeeds.

## Configuration

An optional `callouts` key in `.wp-poster.json`, merged over the built-in
defaults. Every field is optional; a partial override touches only what it
names.

```json
"callouts": {
  "background": "tertiary",
  "types": {
    "note":     {"label": "Note",      "color": "primary"},
    "caution":  {"label": "Caution",   "color": "#cf2e2e"},
    "bookmark": {"label": "Read next", "color": "primary", "icon": ""}
  }
}
```

- `label` - the text after the icon. Also serves the localisation need
  that drove tamara's `calloutLabels`.
- `color` - palette slug or hex literal, per "Colour resolution".
- `icon` - inline HTML overriding the built-in SVG. `""` disables the icon.
- `background` - one slug or hex for all callout groups.

Defaults target Ollie: `tertiary` background, `primary` accent for every
type. All eight therefore share the site's tone and differ by icon and
label, which is the intended baseline.

## Deliberate omissions

- **tamara's SUMMARY flattening.** tamara rewrites paragraphs and stray
  lines into `<li>` elements. That works around an authoring habit rather
  than a real requirement. Here, a markdown list produces a `wp:list` and
  anything else renders as itself.
- **FAQPage JSON-LD.** See Decisions.
- **Nested callouts.** A callout inside a callout is not supported; the
  existing `max_nested_level` guard already prevents runaway nesting.

## Testing

Extending `tests/test_gutenberg.py`, plus a new `tests/test_callouts.py`:

- Markup assertions for all eight types.
- Colour resolution: slug produces `var:preset|color|…`, hex produces the
  literal, and the two paths differ in both block attributes and inline
  style.
- Config merge: partial override leaves untouched fields at their
  defaults; unknown type names warn and are ignored.
- FAQ pair splitting, including answers containing lists and code, a
  single-pair body, and a body with no questions.
- Bookmark against a stubbed resolver: with image (`media-text`), without
  image (group), resolution returning `None`, resolver raising, and
  resolver absent.
- SVG stripping detection: warns when the response lacks `<svg`, stays
  quiet when it is present, and stays quiet when `content.rendered` is
  absent.

## Documentation and versioning

- `skills/wp-post/SKILL.md` gains a callouts section. Admonitions are
  currently undocumented there, so this covers all eight types, the
  syntax, and the `callouts` config key.
- The `--help` epilog in `wp-post.py` gains a callouts block alongside the
  existing frontmatter and images sections.
- `install.sh` must copy `callouts.py` to `$INSTALL_DIR`. It currently
  installs only `wp-post`, `wp-post.py`, and `gutenberg.py`, so without
  this the system-wide `wp-post` at `/opt/wp-poster` fails on import as
  soon as `gutenberg.py` starts importing the new module.
- `.claude-plugin/plugin.json` goes to 1.12.0, per the project rule that
  any `skills/` change bumps the version.

## Behaviour change

The five existing admonitions currently emit `wp:quote` and will emit
`wp:group`. Posts already published keep their stored markup until
re-published.

## To verify during implementation

Two things cannot be settled from outside the site and are resolved by the
demo post rather than by assumption:

1. Whether Gutenberg's `core/details` accepts an `<h3>` inside its summary
   RichText without a validation warning. Fallback: a plain `<summary>`
   styled to h3 size.
2. Whether `core/group` serialises split (per-side) border colour as
   assumed. Fallback: a full border in the accent colour, or a
   `core/quote` wrapper, which Ollie already gives a left border.

Both are front-end-correct either way; the risk is confined to the editor.

## Demo

`callouts-demo.md` in the repo exercises all eight types, with the
bookmark pointing at a real dashpadd.com post. Published live to
dashpadd.com with `./wp-post callouts-demo.md --markdown`.

The leading `./` matters. `wp-post` on `PATH` symlinks to
`/opt/wp-poster`, which holds the installed copy, not the branch. The
repo launcher resolves its own directory, so invoking it directly runs the
branch code without needing `sudo ./install.sh` first.
