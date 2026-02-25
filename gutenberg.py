"""
Markdown to Gutenberg block converter.

Uses mistune for CommonMark-compliant parsing with a custom renderer
that emits WordPress Gutenberg block markup.
"""

import re

import mistune
from mistune.plugins.footnotes import footnotes
from mistune.plugins.formatting import strikethrough
from mistune.plugins.table import table


# Sentinel used by the renderer to mark standalone images so
# paragraph() can promote them to wp:image blocks.
_IMAGE_SENTINEL = "\x00GUTENBERG_IMAGE\x00"


def _wp_image_block(url, alt, title=None, media_id=None):
    """Build a wp:image Gutenberg block string."""
    attrs = '"sizeSlug":"full","linkDestination":"none","align":"center"'
    if media_id:
        attrs = f'"id":{media_id},{attrs}'

    cls = f' class="wp-image-{media_id}"' if media_id else ""

    if title and title.strip():
        caption = f'<figcaption class="wp-element-caption">{title}</figcaption>'
    else:
        caption = ""

    return (
        f"<!-- wp:image {{{attrs}}} -->\n"
        f'<figure class="wp-block-image aligncenter size-full">'
        f'<img src="{url}" alt="{alt}"{cls}/>'
        f"{caption}</figure>\n"
        f"<!-- /wp:image -->"
    )


class GutenbergRenderer(mistune.HTMLRenderer):
    """Mistune renderer that outputs WordPress Gutenberg block markup."""

    NAME = "html"

    def __init__(self, image_handler=None):
        super().__init__()
        self.image_handler = image_handler or (lambda url: (url, None))

    # ------------------------------------------------------------------
    # Block-level overrides
    # ------------------------------------------------------------------

    def paragraph(self, text):
        # A paragraph containing only an image sentinel is promoted
        # to a standalone wp:image block (no wrapping paragraph).
        stripped = text.strip()
        if stripped.startswith(_IMAGE_SENTINEL) and stripped.endswith(_IMAGE_SENTINEL):
            return stripped.replace(_IMAGE_SENTINEL, "") + "\n\n"

        # Handle HTML <img> tags that mistune passed through
        processed = self._process_html_images(text)

        return (
            f"<!-- wp:paragraph -->\n"
            f"<p>{processed}</p>\n"
            f"<!-- /wp:paragraph -->\n\n"
        )

    def heading(self, text, level, **attrs):
        return (
            f'<!-- wp:heading {{"level":{level}}} -->\n'
            f'<h{level} class="wp-block-heading">{text}</h{level}>\n'
            f"<!-- /wp:heading -->\n\n"
        )

    def block_code(self, code, info=None):
        from html import escape as html_escape
        lang_attr = f' class="language-{info}"' if info else ""
        escaped = html_escape(code.rstrip('\n'))
        return (
            f"<!-- wp:code -->\n"
            f'<pre class="wp-block-code"><code{lang_attr}>{escaped}</code></pre>\n'
            f"<!-- /wp:code -->\n\n"
        )

    def block_quote(self, text):
        return (
            f"<!-- wp:quote -->\n"
            f'<blockquote class="wp-block-quote">{text}</blockquote>\n'
            f"<!-- /wp:quote -->\n\n"
        )

    def thematic_break(self):
        return (
            "<!-- wp:separator -->\n"
            '<hr class="wp-block-separator has-alpha-channel-opacity"/>\n'
            "<!-- /wp:separator -->\n\n"
        )

    def list(self, text, ordered, **attrs):
        tag = "ol" if ordered else "ul"
        if ordered:
            return (
                f'<!-- wp:list {{"ordered":true}} -->\n'
                f"<{tag}>\n{text}</{tag}>\n"
                f"<!-- /wp:list -->\n\n"
            )
        return (
            f"<!-- wp:list -->\n"
            f"<{tag}>\n{text}</{tag}>\n"
            f"<!-- /wp:list -->\n\n"
        )

    def list_item(self, text):
        # Strip wrapping <p> that mistune adds for loose list items
        text = re.sub(r"^<p>(.*)</p>\n?$", r"\1", text.strip(), flags=re.DOTALL)
        return f"<li>{text}</li>\n"

    # ------------------------------------------------------------------
    # Inline-level overrides
    # ------------------------------------------------------------------

    def image(self, text, url, title=None):
        final_url, media_id = self.image_handler(url)
        if not final_url:
            return ""
        block = _wp_image_block(final_url, text, title=title, media_id=media_id)
        return f"{_IMAGE_SENTINEL}{block}{_IMAGE_SENTINEL}"

    def link(self, text, url, title=None):
        return f'<a href="{url}">{text}</a>'

    # Table plugin overrides are standalone functions — see _GUTENBERG_TABLE_*
    # below — registered via renderer.register() after plugin init.

    # ------------------------------------------------------------------
    # HTML image passthrough
    # ------------------------------------------------------------------

    def _process_html_images(self, text):
        """Process any raw HTML <img>/<figure> tags via the image handler."""
        figure_pattern = (
            r'<figure[^>]*>\s*<img\s+([^>]+)\s*/?>\s*'
            r'(?:<figcaption[^>]*>(.*?)</figcaption>)?\s*</figure>'
        )

        def _replace_figure(m):
            img_attrs = m.group(1)
            caption = m.group(2) or ""
            src = re.search(r'src\s*=\s*["\']([^"\']+)["\']', img_attrs)
            alt = re.search(r'alt\s*=\s*["\']([^"\']*)["\']', img_attrs)
            if not src:
                return m.group(0)
            final_url, media_id = self.image_handler(src.group(1))
            if not final_url:
                return m.group(0)
            caption_clean = re.sub(r'<[^>]+>', '', caption).strip() if caption else ""
            return _wp_image_block(
                final_url, alt.group(1) if alt else "",
                title=caption_clean or None, media_id=media_id,
            )

        text = re.sub(figure_pattern, _replace_figure, text, flags=re.DOTALL | re.IGNORECASE)

        standalone_img = r'<img\s+([^>]+)\s*/?>'

        def _replace_img(m):
            img_attrs = m.group(1)
            src = re.search(r'src\s*=\s*["\']([^"\']+)["\']', img_attrs)
            alt = re.search(r'alt\s*=\s*["\']([^"\']*)["\']', img_attrs)
            if not src:
                return m.group(0)
            final_url, media_id = self.image_handler(src.group(1))
            if not final_url:
                return m.group(0)
            return _wp_image_block(
                final_url, alt.group(1) if alt else "",
                media_id=media_id,
            )

        if '<!-- wp:image' not in text:
            text = re.sub(standalone_img, _replace_img, text, flags=re.IGNORECASE)

        return text


# ------------------------------------------------------------------
# Standalone table render functions for register() — the first arg
# is the renderer instance, injected by mistune's register mechanism.
# ------------------------------------------------------------------

def _gutenberg_table(renderer, text):
    return (
        f"<!-- wp:table -->\n"
        f'<figure class="wp-block-table"><table>{text}</table></figure>\n'
        f"<!-- /wp:table -->\n\n"
    )

def _gutenberg_table_head(renderer, text):
    return f"<thead><tr>\n{text}</tr></thead>"

def _gutenberg_table_body(renderer, text):
    return f"<tbody>\n{text}</tbody>"

def _gutenberg_table_row(renderer, text):
    return f"<tr>\n{text}</tr>\n"

def _gutenberg_table_cell(renderer, text, align=None, head=False):
    tag = "th" if head else "td"
    return f"<{tag}>{text}</{tag}>\n"


# ------------------------------------------------------------------
# GFM admonition plugin — intercepts blockquotes at the AST level,
# following the same pattern as mistune's built-in spoiler plugin.
# ------------------------------------------------------------------

_GFM_ADMONITION_RE = re.compile(
    r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*\n?",
    re.IGNORECASE,
)


def _parse_gfm_admonition(block, m, state):
    """Replace the block_quote parser; emit gfm_admonition or block_quote."""
    text, end_pos = block.extract_block_quote(m, state)
    if not text.endswith("\n"):
        text += "\n"

    admon = _GFM_ADMONITION_RE.match(text)
    if admon:
        tok_type = "gfm_admonition"
        text = text[admon.end():]
        attrs = {"name": admon.group(1).lower()}
    else:
        tok_type = "block_quote"
        attrs = {}

    child = state.child_state(text)
    if state.depth() >= block.max_nested_level - 1:
        rules = list(block.block_quote_rules)
        rules.remove("block_quote")
    else:
        rules = block.block_quote_rules

    block.parse(child, rules)
    token = {"type": tok_type, "children": child.tokens, "attrs": attrs}
    if end_pos:
        state.prepend_token(token)
        return end_pos
    state.append_token(token)
    return state.cursor


_ADMONITION_STYLES = {
    "note": {
        "color": "#0969da",
        "icon": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="20" height="20" fill="#0969da" style="display:inline-block;vertical-align:middle;margin-right:6px;position:relative;top:-2px;"><path d="M0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8Zm8-6.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM6.5 7.75A.75.75 0 0 1 7.25 7h1a.75.75 0 0 1 .75.75v2.75h.25a.75.75 0 0 1 0 1.5h-2a.75.75 0 0 1 0-1.5h.25v-2h-.25a.75.75 0 0 1-.75-.75ZM8 6a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z"></path></svg>',
    },
    "tip": {
        "color": "#1a7f37",
        "icon": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="20" height="20" fill="#1a7f37" style="display:inline-block;vertical-align:middle;margin-right:6px;position:relative;top:-2px;"><path d="M8 1.5c-2.363 0-4 1.69-4 3.75 0 .984.424 1.625.984 2.304l.214.253c.223.264.47.556.673.848.284.411.537.896.621 1.49a.75.75 0 0 1-1.484.211c-.04-.282-.163-.547-.37-.847a8.456 8.456 0 0 0-.542-.68c-.084-.1-.173-.205-.268-.32C3.201 7.75 2.5 6.766 2.5 5.25 2.5 2.31 4.863 0 8 0s5.5 2.31 5.5 5.25c0 1.516-.701 2.5-1.328 3.259-.095.115-.184.22-.268.319-.207.245-.383.453-.541.681-.208.3-.33.565-.37.847a.751.751 0 0 1-1.485-.212c.084-.593.337-1.078.621-1.489.203-.292.45-.584.673-.848.075-.088.147-.173.213-.253.561-.679.985-1.32.985-2.304 0-2.06-1.637-3.75-4-3.75ZM5.75 12h4.5a.75.75 0 0 1 0 1.5h-4.5a.75.75 0 0 1 0-1.5ZM6 15.25a.75.75 0 0 1 .75-.75h2.5a.75.75 0 0 1 0 1.5h-2.5a.75.75 0 0 1-.75-.75Z"></path></svg>',
    },
    "important": {
        "color": "#8250df",
        "icon": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="20" height="20" fill="#8250df" style="display:inline-block;vertical-align:middle;margin-right:6px;position:relative;top:-2px;"><path d="M0 1.75C0 .784.784 0 1.75 0h12.5C15.216 0 16 .784 16 1.75v9.5A1.75 1.75 0 0 1 14.25 13H8.06l-2.573 2.573A1.458 1.458 0 0 1 3 14.543V13H1.75A1.75 1.75 0 0 1 0 11.25Zm1.75-.25a.25.25 0 0 0-.25.25v9.5c0 .138.112.25.25.25h2a.75.75 0 0 1 .75.75v2.19l2.72-2.72a.749.749 0 0 1 .53-.22h6.5a.25.25 0 0 0 .25-.25v-9.5a.25.25 0 0 0-.25-.25Zm7 2.25v2.5a.75.75 0 0 1-1.5 0v-2.5a.75.75 0 0 1 1.5 0ZM9 9a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z"></path></svg>',
    },
    "warning": {
        "color": "#9a6700",
        "icon": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="20" height="20" fill="#9a6700" style="display:inline-block;vertical-align:middle;margin-right:6px;position:relative;top:-2px;"><path d="M6.457 1.047c.659-1.234 2.427-1.234 3.086 0l6.082 11.378A1.75 1.75 0 0 1 14.082 15H1.918a1.75 1.75 0 0 1-1.543-2.575Zm1.763.707a.25.25 0 0 0-.44 0L1.698 13.132a.25.25 0 0 0 .22.368h12.164a.25.25 0 0 0 .22-.368Zm.53 3.996v2.5a.75.75 0 0 1-1.5 0v-2.5a.75.75 0 0 1 1.5 0ZM9 11a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z"></path></svg>',
    },
    "caution": {
        "color": "#d1242f",
        "icon": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="20" height="20" fill="#d1242f" style="display:inline-block;vertical-align:middle;margin-right:6px;position:relative;top:-2px;"><path d="M4.47.22A.749.749 0 0 1 5 0h6c.199 0 .389.079.53.22l4.25 4.25c.141.14.22.331.22.53v6a.749.749 0 0 1-.22.53l-4.25 4.25A.749.749 0 0 1 11 16H5a.749.749 0 0 1-.53-.22L.22 11.53A.749.749 0 0 1 0 11V5c0-.199.079-.389.22-.53Zm.84 1.28L1.5 5.31v5.38l3.81 3.81h5.38l3.81-3.81V5.31L10.69 1.5ZM8 4a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 8 4Zm0 8a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z"></path></svg>',
    },
}


def _render_gfm_admonition(renderer, text, name, **attrs):
    """Render a GFM admonition as a wp:quote with GitHub-style icon and border."""
    style = _ADMONITION_STYLES.get(name, {"icon": "", "color": "#666"})
    icon = style["icon"]
    color = style["color"]
    title = (
        f"<!-- wp:paragraph -->\n"
        f'<p style="color: {color}; font-weight: 500;">'
        f"{icon}{name.capitalize()}</p>\n"
        f"<!-- /wp:paragraph -->\n"
    )
    return (
        f'<!-- wp:quote {{"className":"is-admonition is-admonition-{name}"}} -->\n'
        f'<blockquote class="wp-block-quote is-admonition is-admonition-{name}"'
        f' style="border-left-color: {color};">'
        f"{title}{text}</blockquote>\n"
        f"<!-- /wp:quote -->\n\n"
    )


def gfm_admonition(md):
    """Mistune plugin: GFM admonition syntax in blockquotes."""
    md.block.register("block_quote", None, _parse_gfm_admonition)
    if md.renderer and md.renderer.NAME == "html":
        md.renderer.register("gfm_admonition", _render_gfm_admonition)


class GutenbergConverter:
    """Converts markdown to WordPress Gutenberg blocks."""

    def __init__(self, image_handler=None):
        """
        Initialize converter.

        Args:
            image_handler: Optional callable(image_url) -> (final_url, media_id)
                          If None, images are left as-is with no media ID.
        """
        self._renderer = GutenbergRenderer(image_handler=image_handler)

        self._md = mistune.Markdown(
            renderer=self._renderer,
            plugins=[table, footnotes, strikethrough, gfm_admonition],
        )

        # Register table overrides *after* plugins so we replace the
        # default renderers the table plugin just wired up.
        self._renderer.register("table", _gutenberg_table)
        self._renderer.register("table_head", _gutenberg_table_head)
        self._renderer.register("table_body", _gutenberg_table_body)
        self._renderer.register("table_row", _gutenberg_table_row)
        self._renderer.register("table_cell", _gutenberg_table_cell)

    def convert(self, markdown_content):
        """Convert markdown to Gutenberg block format."""
        raw = self._md(markdown_content)

        # Collapse runs of blank lines and trim, then re-join blocks
        # with double-newlines for Gutenberg spacing.
        blocks = [b.strip() for b in re.split(r'\n{2,}', raw) if b.strip()]
        return '\n\n'.join(blocks)
