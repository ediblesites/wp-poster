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

from callouts import callout_plugin


# Sentinel used by the renderer to mark standalone images so
# paragraph() can promote them to wp:image blocks.
_IMAGE_SENTINEL = "\x00GUTENBERG_IMAGE\x00"

# Placeholder template for raw Gutenberg blocks extracted from the
# source before markdown parsing (reinserted verbatim afterwards).
_RAW_BLOCK_SENTINEL = "\x00GUTENBERG_RAW_{}\x00"

# Matches a Gutenberg block comment delimiter: opener, closer, or
# self-closing — e.g. <!-- wp:cover {"url":"x"} -->, <!-- /wp:cover -->,
# <!-- wp:archives /-->.
_WP_BLOCK_COMMENT_RE = re.compile(
    r"<!--\s+(?P<close>/)?wp:(?P<name>[a-z][\w-]*(?:/[a-z][\w-]*)?)"
    r"(?:\s+\{.*?\})?\s*(?P<self_close>/)?-->",
    re.IGNORECASE,
)


def _extract_raw_gutenberg(text, line_offset=0):
    """Extract top-level raw Gutenberg block regions from markdown source.

    A region starts at a line beginning (column 0) with a Gutenberg
    opening comment and runs to its matching closer, tracking nesting
    depth so container blocks (wp:columns, wp:group) are captured whole.
    Self-closing blocks are a complete region on their own.

    Returns (text_with_placeholders, blocks) where each region in the
    source is replaced by a unique placeholder paragraph.

    Raises ValueError if an opening comment has no matching closer.
    line_offset is added to reported line numbers so callers that strip
    a prefix (e.g. frontmatter) can report file-relative positions.
    """
    lines = text.split("\n")
    out_lines = []
    blocks = []
    fence = None  # open code-fence marker, e.g. "```" or "~~~~"
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # Skip extraction inside fenced code blocks so Gutenberg markup
        # can be shown as a code example.
        fence_m = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence is None and fence_m:
            fence = fence_m.group(1)
        elif fence and fence_m and fence_m.group(1)[0] == fence[0] \
                and len(fence_m.group(1)) >= len(fence):
            fence = None
        if fence is not None or fence_m:
            out_lines.append(line)
            i += 1
            continue

        m = _WP_BLOCK_COMMENT_RE.match(line)
        if not m or m.group("close"):
            # Not a Gutenberg opener at column 0 (stray closers fall
            # through to normal markdown handling).
            out_lines.append(line)
            i += 1
            continue

        open_name = m.group("name")
        open_line_no = i + 1 + line_offset
        depth = 0
        region = []
        j = i
        while j < n:
            cur = lines[j]
            region.append(cur)
            for cm in _WP_BLOCK_COMMENT_RE.finditer(cur):
                if cm.group("self_close"):
                    continue
                depth += -1 if cm.group("close") else 1
            j += 1
            if depth == 0:
                break

        if depth != 0:
            raise ValueError(
                f"Unclosed Gutenberg block 'wp:{open_name}' "
                f"opened at line {open_line_no}"
            )

        placeholder = _RAW_BLOCK_SENTINEL.format(len(blocks))
        blocks.append("\n".join(region))
        # Blank lines ensure the placeholder is parsed as its own paragraph.
        out_lines.extend(["", placeholder, ""])
        i = j

    return "\n".join(out_lines), blocks


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
        block_attrs = ' {"ordered":true}' if ordered else ""
        return (
            f"<!-- wp:list{block_attrs} -->\n"
            f'<{tag} class="wp-block-list">\n{text}</{tag}>\n'
            f"<!-- /wp:list -->\n\n"
        )

    def list_item(self, text):
        # Strip wrapping <p> that mistune adds for loose list items
        text = re.sub(r"^<p>(.*)</p>\n?$", r"\1", text.strip(), flags=re.DOTALL)
        return (
            f"<!-- wp:list-item -->\n"
            f"<li>{text}</li>\n"
            f"<!-- /wp:list-item -->\n"
        )

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

    def text(self, text):
        # Escape &, <, > but NOT quotes. Text nodes are never inside HTML
        # attributes, so per the HTML spec quotes need no escaping here.
        # Escaping them to &quot; breaks WordPress shortcodes carrying
        # quoted attributes (e.g. [np-image entity="smtp2go"]).
        from mistune.util import escape
        return escape(text, quote=False)

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


class GutenbergConverter:
    """Converts markdown to WordPress Gutenberg blocks."""

    def __init__(self, image_handler=None, callout_config=None, bookmark_resolver=None):
        """
        Initialize converter.

        Args:
            image_handler: Optional callable(image_url) -> (final_url, media_id)
                          If None, images are left as-is with no media ID.
            callout_config: Optional dict merged over callouts.DEFAULT_CONFIG.
            bookmark_resolver: Optional callable(target) -> dict | None used by
                          [!BOOKMARK] callouts. If None, bookmarks degrade to
                          a plain link card without a network request.
        """
        self._renderer = GutenbergRenderer(image_handler=image_handler)

        self._md = mistune.Markdown(
            renderer=self._renderer,
            plugins=[
                table,
                footnotes,
                strikethrough,
                callout_plugin(callout_config, bookmark_resolver),
            ],
        )

        # Register table overrides *after* plugins so we replace the
        # default renderers the table plugin just wired up.
        self._renderer.register("table", _gutenberg_table)
        self._renderer.register("table_head", _gutenberg_table_head)
        self._renderer.register("table_body", _gutenberg_table_body)
        self._renderer.register("table_row", _gutenberg_table_row)
        self._renderer.register("table_cell", _gutenberg_table_cell)

    def convert(self, markdown_content, line_offset=0):
        """Convert markdown to Gutenberg block format.

        line_offset shifts line numbers in error messages so callers
        that strip a frontmatter prefix report file-relative positions.
        """
        # Pull raw Gutenberg regions out before parsing so they pass
        # through verbatim (no escaping, no markdown processing).
        text, raw_blocks = _extract_raw_gutenberg(
            markdown_content, line_offset=line_offset
        )

        raw = self._md(text)

        # Collapse runs of blank lines and trim, then re-join blocks
        # with double-newlines for Gutenberg spacing.
        blocks = [b.strip() for b in re.split(r'\n{2,}', raw) if b.strip()]
        result = '\n\n'.join(blocks)

        # Reinsert raw Gutenberg blocks, replacing the whole placeholder
        # paragraph (not just the sentinel) so no wp:paragraph wrapper
        # is left around the block.
        for idx, block in enumerate(raw_blocks):
            sentinel = _RAW_BLOCK_SENTINEL.format(idx)
            wrapped = (
                f"<!-- wp:paragraph -->\n<p>{sentinel}</p>\n<!-- /wp:paragraph -->"
            )
            if wrapped in result:
                result = result.replace(wrapped, block)
            else:
                result = result.replace(sentinel, block)

        return result
