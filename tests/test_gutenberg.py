"""Tests for gutenberg.py — GutenbergConverter."""

import mistune
import pytest

from gutenberg import GutenbergConverter, youtube_id


# ---------------------------------------------------------------------------
# Inline markdown (tested via convert() producing paragraph blocks)
# ---------------------------------------------------------------------------

class TestInlineMarkdown:
    def test_bold(self, converter):
        result = converter.convert("**bold**")
        assert "<strong>bold</strong>" in result

    def test_italic(self, converter):
        result = converter.convert("*italic*")
        assert "<em>italic</em>" in result

    def test_bold_italic(self, converter):
        result = converter.convert("***both***")
        assert "<strong>" in result
        assert "<em>" in result
        assert "both" in result

    def test_strikethrough(self, converter):
        result = converter.convert("~~deleted~~")
        assert "<del>deleted</del>" in result

    def test_inline_code(self, converter):
        result = converter.convert("use `foo()` here")
        assert "<code>foo()</code>" in result

    def test_inline_code_escapes_html(self, converter):
        result = converter.convert("`<div>`")
        assert "<code>&lt;div&gt;</code>" in result

    def test_literal_quotes_not_escaped(self, converter):
        # Quotes in text content never need HTML escaping and must survive
        # so WordPress shortcodes carrying quoted attributes still parse.
        result = converter.convert('She said "hello" to me.')
        assert 'She said "hello" to me.' in result
        assert "&quot;" not in result

    def test_shortcode_quotes_preserved(self, converter):
        result = converter.convert('[np-image entity="smtp2go"]')
        assert '[np-image entity="smtp2go"]' in result
        assert "&quot;" not in result

    def test_text_still_escapes_html_entities(self, converter):
        # Dropping quote escaping must not stop escaping & < >.
        result = converter.convert("a < b & c > d")
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;" in result

    def test_link(self, converter):
        result = converter.convert("[click](https://example.com)")
        assert '<a href="https://example.com">click</a>' in result

    def test_reference_link(self, converter):
        md = "Visit [example][1] today.\n\n[1]: https://example.com"
        result = converter.convert(md)
        assert '<a href="https://example.com">example</a>' in result

    def test_footnote(self, converter):
        md = "Some text[^1].\n\n[^1]: Footnote content"
        result = converter.convert(md)
        assert "fnref-1" in result
        assert "Footnote content" in result


# ---------------------------------------------------------------------------
# Block conversion — convert()
# ---------------------------------------------------------------------------

class TestHeadings:
    def test_h1(self, converter):
        result = converter.convert("# Title")
        assert "wp:heading" in result
        assert '<h1 class="wp-block-heading">Title</h1>' in result

    def test_h2(self, converter):
        # WordPress omits the level attribute for an h2: 2 is the block's
        # default and save() only writes non-default attributes. Checked
        # against a live WordPress 7.1.1 install's own stored markup.
        result = converter.convert("## Subtitle")
        assert "<!-- wp:heading -->" in result
        assert '"level"' not in result
        assert '<h2 class="wp-block-heading">' in result

    def test_h3(self, converter):
        result = converter.convert("### H3")
        assert '"level":3' in result

    def test_heading_with_inline(self, converter):
        result = converter.convert("## **bold** heading")
        assert "wp:heading" in result
        assert "<strong>bold</strong>" in result


class TestParagraphs:
    def test_simple_paragraph(self, converter):
        result = converter.convert("Hello world")
        assert "wp:paragraph" in result
        assert "<p>Hello world</p>" in result

    def test_two_paragraphs(self, converter):
        result = converter.convert("Para 1\n\nPara 2")
        assert result.count("<!-- wp:paragraph -->") == 2


class TestCodeBlocks:
    def test_fenced_code(self, converter):
        md = "```\nprint('hi')\n```"
        result = converter.convert(md)
        assert "wp:code" in result
        assert "print(&#x27;hi&#x27;)" in result

    def test_fenced_code_with_language(self, converter):
        md = "```python\nprint('hi')\n```"
        result = converter.convert(md)
        assert 'language-python' in result

    def test_code_html_escaped(self, converter):
        md = "```\n<div>test</div>\n```"
        result = converter.convert(md)
        assert "&lt;div&gt;" in result


class TestHorizontalRules:
    def test_dashes(self, converter):
        result = converter.convert("---")
        assert "wp:separator" in result

    def test_asterisks(self, converter):
        result = converter.convert("***")
        assert "wp:separator" in result

    def test_underscores(self, converter):
        result = converter.convert("___")
        assert "wp:separator" in result


class TestLists:
    def test_unordered_list(self, converter):
        md = "- one\n- two\n- three"
        result = converter.convert(md)
        assert "wp:list" in result
        assert '<ul class="wp-block-list">' in result
        assert "<li>one</li>" in result

    def test_ordered_list(self, converter):
        md = "1. one\n2. two\n3. three"
        result = converter.convert(md)
        assert '"ordered":true' in result
        assert '<ol class="wp-block-list">' in result
        assert "<li>one</li>" in result

    def test_unordered_list_items_are_inner_blocks(self, converter):
        md = "- one\n- two\n- three"
        result = converter.convert(md)
        assert result.count("<!-- wp:list-item -->") == 3
        assert result.count("<!-- /wp:list-item -->") == 3
        # Each <li> is wrapped in wp:list-item delimiters
        assert "<!-- wp:list-item -->\n<li>one</li>\n<!-- /wp:list-item -->" in result

    def test_ordered_list_items_are_inner_blocks(self, converter):
        md = "1. one\n2. two"
        result = converter.convert(md)
        assert result.count("<!-- wp:list-item -->") == 2
        assert result.count("<!-- /wp:list-item -->") == 2

    def test_nested_list(self, converter):
        md = "- parent\n  - child"
        result = converter.convert(md)
        assert "wp:list" in result
        assert "parent" in result
        assert "<li>child</li>" in result

    def test_nested_list_structure(self, converter):
        md = "- parent\n  - child"
        result = converter.convert(md)
        # parent li + child li, each a wp:list-item inner block
        assert result.count("<!-- wp:list-item -->") == 2
        assert result.count("<!-- /wp:list-item -->") == 2
        # the child wp:list block nests inside the parent <li>
        assert result.count("<!-- wp:list -->") == 2
        inner_list = result.index("<!-- wp:list -->", result.index("<li>"))
        parent_li_close = result.index("</li>", result.index("<li>"))
        assert inner_list < parent_li_close, "nested wp:list must open inside parent <li>"

    def test_list_with_inline_markdown(self, converter):
        md = "- **bold** item\n- [link](https://example.com)"
        result = converter.convert(md)
        assert "<strong>bold</strong>" in result
        assert '<a href="https://example.com">link</a>' in result


class TestBlockquotes:
    def test_single_line(self, converter):
        result = converter.convert("> quote text")
        assert "wp:quote" in result
        assert "<p>quote text</p>" in result

    def test_multiline(self, converter):
        md = "> line 1\n> line 2"
        result = converter.convert(md)
        assert "wp:quote" in result
        assert "line 1" in result
        assert "line 2" in result


class TestCalloutsIntegration:
    def test_important(self, converter):
        md = "> [!IMPORTANT]\n> This is important."
        result = converter.convert(md)
        assert "is-callout" in result
        assert "is-callout-important" in result
        assert "Important" in result
        assert "This is important." in result

    def test_note(self, converter):
        md = "> [!NOTE]\n> A note."
        result = converter.convert(md)
        assert "is-callout-note" in result
        assert "Note</strong>" in result

    def test_tip(self, converter):
        md = "> [!TIP]\n> A tip."
        result = converter.convert(md)
        assert "is-callout-tip" in result
        assert "Tip</strong>" in result

    def test_warning(self, converter):
        md = "> [!WARNING]\n> Be careful."
        result = converter.convert(md)
        assert "is-callout-warning" in result
        assert "Warning</strong>" in result

    def test_caution(self, converter):
        md = "> [!CAUTION]\n> Danger zone."
        result = converter.convert(md)
        assert "is-callout-caution" in result
        assert "Caution</strong>" in result

    def test_callout_with_multiple_paragraphs(self, converter):
        md = "> [!NOTE]\n>\n> First paragraph.\n>\n> Second paragraph."
        result = converter.convert(md)
        assert "is-callout-note" in result
        assert "First paragraph." in result
        assert "Second paragraph." in result

    def test_callout_case_insensitive(self, converter):
        md = "> [!important]\n> Text."
        result = converter.convert(md)
        assert "is-callout-important" in result

    def test_regular_blockquote_unchanged(self, converter):
        result = converter.convert("> Just a regular quote.")
        assert "is-callout" not in result
        assert "wp:group" not in result
        assert "wp:quote" in result

    def test_callout_preserves_inline_formatting(self, converter):
        md = "> [!TIP]\n> Use `code` and **bold** here."
        result = converter.convert(md)
        assert "is-callout-tip" in result
        assert "<code>code</code>" in result
        assert "<strong>" in result

    def test_callout_border_uses_the_conventional_hue(self, converter):
        md = "> [!WARNING]\n> Watch out."
        result = converter.convert(md)
        assert "border-left-color:#9a6700" in result
        assert "border-left-style:solid" in result

    def test_callout_icon_inherits_its_label_colour(self, converter):
        # The icon has no colour of its own - currentColor makes it follow
        # the label, so one config value drives both.
        md = "> [!NOTE]\n> Info here."
        result = converter.convert(md)
        assert "<svg" in result
        assert 'fill="currentColor"' in result
        assert 'fill="#0969da"' not in result

    def test_callout_label_uses_the_conventional_hue(self, converter):
        md = "> [!CAUTION]\n> Danger."
        result = converter.convert(md)
        assert "color:#d1242f" in result

    def test_callout_background_still_comes_from_the_theme(self, converter):
        # Hues apply to the accent only; the background stays theme-driven.
        result = converter.convert("> [!CAUTION]\n> Danger.")
        assert "has-tertiary-background-color" in result


class TestTables:
    def test_basic_table(self, converter):
        md = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        result = converter.convert(md)
        assert "wp:table" in result
        assert "<th>A</th>" in result
        assert "<td>1</td>" in result


class TestImages:
    def test_markdown_image(self, converter):
        result = converter.convert("![alt text](https://img.example.com/pic.jpg)")
        assert "wp:image" in result
        assert 'src="https://img.example.com/pic.jpg"' in result
        assert 'alt="alt text"' in result

    def test_alt_text_quote_is_escaped(self, converter):
        # A literal quote in alt text must not close the attribute early.
        # text() itself leaves quotes alone (WordPress shortcodes need that),
        # so the escaping happens where the alt attribute is built instead.
        result = converter.convert('![Say "hi" to the cat](https://img.example.com/pic.jpg)')
        assert 'alt="Say &quot;hi&quot; to the cat"' in result
        assert '<img src="https://img.example.com/pic.jpg" alt="Say &quot;hi&quot; to the cat"/>' in result

    def test_image_with_media_id(self):
        c = GutenbergConverter(image_handler=lambda url: (url, 42))
        result = c.convert("![photo](https://img.example.com/pic.jpg)")
        assert '"id":42' in result
        assert "wp-image-42" in result

    def test_image_with_title(self, converter):
        result = converter.convert('![alt](https://img.example.com/pic.jpg "My Caption")')
        assert "wp:image" in result
        assert "My Caption" in result

    def test_standalone_image_not_wrapped_in_paragraph(self, converter):
        result = converter.convert("![alt](https://img.example.com/pic.jpg)")
        assert "wp:image" in result
        assert "wp:paragraph" not in result

    def test_image_mixed_with_text(self, converter):
        md = "Before image.\n\n![alt](https://img.example.com/pic.jpg)\n\nAfter image."
        result = converter.convert(md)
        assert "wp:image" in result
        assert result.count("wp:paragraph") >= 2


# ---------------------------------------------------------------------------
# Video, written as an image pointing at YouTube
# ---------------------------------------------------------------------------

VIDEO = "![Video: the filter comes out.](https://youtu.be/bNsGaNe0jfo)"


class TestYoutubeEmbeds:
    @pytest.mark.parametrize(
        "url",
        [
            "https://youtu.be/bNsGaNe0jfo",
            "https://www.youtube.com/watch?v=bNsGaNe0jfo",
            "https://youtube.com/watch?v=bNsGaNe0jfo",
            "https://m.youtube.com/watch?v=bNsGaNe0jfo",
            "https://www.youtube.com/watch?v=bNsGaNe0jfo&t=30s",
            "https://www.youtube.com/shorts/bNsGaNe0jfo",
            "https://www.youtube.com/live/bNsGaNe0jfo",
            "https://www.youtube.com/embed/bNsGaNe0jfo",
            "https://www.youtube-nocookie.com/embed/bNsGaNe0jfo",
        ],
    )
    def test_youtube_id_reads_every_shape_an_author_might_paste(self, url):
        assert youtube_id(url) == "bNsGaNe0jfo"

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/a.jpg",
            "https://www.youtube.com/results?search_query=x",
            "https://www.youtube.com/@somechannel",
            "https://notyoutube.com/watch?v=bNsGaNe0jfo",
            "https://evilyoutube.com/watch?v=bNsGaNe0jfo",
            "cat.jpg",
        ],
    )
    def test_youtube_id_rejects_everything_else(self, url):
        assert youtube_id(url) is None

    def test_a_lone_youtube_image_becomes_an_embed_block(self, converter):
        out = converter.convert(VIDEO)
        assert (
            '<!-- wp:embed {"url":"https://www.youtube.com/watch?v=bNsGaNe0jfo",'
            '"type":"video","providerNameSlug":"youtube","responsive":true,'
            '"className":"wp-embed-aspect-16-9 wp-has-aspect-ratio"} -->' in out
        )
        assert (
            '<figure class="wp-block-embed is-type-video is-provider-youtube '
            'wp-block-embed-youtube wp-embed-aspect-16-9 wp-has-aspect-ratio">' in out
        )
        assert (
            '<div class="wp-block-embed__wrapper">\n'
            "https://www.youtube.com/watch?v=bNsGaNe0jfo\n</div>" in out
        )
        assert "wp:image" not in out
        assert "wp:paragraph" not in out

    def test_any_url_shape_normalises_to_the_watch_url(self, converter):
        out = converter.convert("![](https://www.youtube.com/shorts/bNsGaNe0jfo)")
        assert out.count("https://www.youtube.com/watch?v=bNsGaNe0jfo") == 2

    def test_alt_text_becomes_the_caption(self, converter):
        assert (
            '<figcaption class="wp-element-caption">Video: the filter comes out.'
            "</figcaption>" in converter.convert(VIDEO)
        )

    def test_a_video_without_alt_text_has_no_caption(self, converter):
        out = converter.convert("![](https://youtu.be/bNsGaNe0jfo)")
        assert "figcaption" not in out
        assert "wp:embed" in out

    def test_the_caption_is_escaped(self, converter):
        out = converter.convert("![Tools & tips](https://youtu.be/bNsGaNe0jfo)")
        assert "&amp;" in out
        assert "Tools & tips" not in out

    def test_a_youtube_url_with_no_video_id_says_so_instead_of_embedding(self, converter):
        out = converter.convert("![x](https://www.youtube.com/results?search_query=mould)")
        assert "wp:embed" not in out
        assert "wp:image" not in out
        assert "no video id" in out

    def test_a_video_inside_a_sentence_degrades_to_a_link(self, converter):
        out = converter.convert("Watch ![this clip](https://youtu.be/bNsGaNe0jfo) first.")
        assert "wp:embed" not in out
        assert "<!-- wp:paragraph -->" in out
        assert '<a href="https://www.youtube.com/watch?v=bNsGaNe0jfo">this clip</a>' in out

    def test_two_videos_in_one_article_keep_their_own_captions(self, converter):
        out = converter.convert(
            "![first](https://youtu.be/bNsGaNe0jfo)\n\n"
            "![second](https://youtu.be/QIS0JIj5ZQM)"
        )
        assert ">first</figcaption>" in out
        assert ">second</figcaption>" in out
        assert "watch?v=QIS0JIj5ZQM" in out

    def test_an_ordinary_image_is_untouched_by_the_video_path(self, converter):
        out = converter.convert("![a cat](https://x/a.jpg)")
        assert "wp:image" in out
        assert "wp:embed" not in out


# ---------------------------------------------------------------------------
# Full document round-trip
# ---------------------------------------------------------------------------

class TestFullDocument:
    def test_multiple_block_types(self, converter):
        md = (
            "# Title\n\n"
            "A paragraph.\n\n"
            "- item 1\n"
            "- item 2\n\n"
            "> a quote\n\n"
            "---\n\n"
            "```python\nx = 1\n```\n"
        )
        result = converter.convert(md)
        assert "wp:heading" in result
        assert "wp:paragraph" in result
        assert "wp:list" in result
        assert "wp:quote" in result
        assert "wp:separator" in result
        assert "wp:code" in result

    def test_blocks_separated_by_double_newlines(self, converter):
        result = converter.convert("# Heading\n\nParagraph")
        parts = result.split("\n\n")
        assert len(parts) >= 2


# ---------------------------------------------------------------------------
# Embedded raw Gutenberg blocks (passthrough)
# ---------------------------------------------------------------------------

class TestEmbeddedGutenberg:
    def test_simple_block_passes_through_verbatim(self, converter):
        block = (
            '<!-- wp:cover {"url":"x.jpg"} -->\n'
            '<div class="wp-block-cover"><p>Hello</p></div>\n'
            "<!-- /wp:cover -->"
        )
        result = converter.convert(block)
        assert block in result

    def test_block_between_markdown_paragraphs(self, converter):
        block = (
            '<!-- wp:cover {"url":"x.jpg"} -->\n'
            '<div class="wp-block-cover"><p>Hello</p></div>\n'
            "<!-- /wp:cover -->"
        )
        md = f"Intro text.\n\n{block}\n\nOutro text."
        result = converter.convert(md)
        assert block in result
        assert "<p>Intro text.</p>" in result
        assert "<p>Outro text.</p>" in result
        # Order preserved
        assert result.index("Intro") < result.index("wp:cover") < result.index("Outro")

    def test_nested_blocks_captured_as_one_region(self, converter):
        block = (
            "<!-- wp:columns -->\n"
            '<div class="wp-block-columns">\n'
            "<!-- wp:column -->\n"
            '<div class="wp-block-column"><p>Left</p></div>\n'
            "<!-- /wp:column -->\n"
            "<!-- wp:column -->\n"
            '<div class="wp-block-column"><p>Right</p></div>\n'
            "<!-- /wp:column -->\n"
            "</div>\n"
            "<!-- /wp:columns -->"
        )
        result = converter.convert(block)
        assert block in result

    def test_self_closing_block(self, converter):
        block = '<!-- wp:archives {"showPostCounts":true} /-->'
        md = f"Before.\n\n{block}\n\nAfter."
        result = converter.convert(md)
        assert block in result

    def test_block_with_blank_lines_inside(self, converter):
        block = (
            "<!-- wp:group -->\n"
            '<div class="wp-block-group">\n'
            "\n"
            "<p>Spaced content</p>\n"
            "\n"
            "</div>\n"
            "<!-- /wp:group -->"
        )
        result = converter.convert(block)
        assert block in result

    def test_markdown_inside_block_not_processed(self, converter):
        block = (
            "<!-- wp:html -->\n"
            "# not a heading\n"
            "*not emphasis*\n"
            "<!-- /wp:html -->"
        )
        result = converter.convert(block)
        assert block in result
        assert "<h1" not in result
        assert "<em>" not in result

    def test_unclosed_block_raises_with_line_number(self, converter):
        import pytest

        md = "Intro.\n\n<!-- wp:cover -->\n<div>oops</div>\n"
        with pytest.raises(ValueError, match=r"wp:cover.*line 3"):
            converter.convert(md)

    def test_inline_wp_comment_not_extracted(self, converter):
        md = "Some text with <!-- wp:cover --> inline mention."
        result = converter.convert(md)
        # Falls through to existing behavior (escaped), no passthrough
        assert "<!-- wp:cover -->" not in result

    def test_multiple_blocks_in_one_document(self, converter):
        block1 = '<!-- wp:spacer {"height":"50px"} -->\n<div style="height:50px"></div>\n<!-- /wp:spacer -->'
        block2 = '<!-- wp:archives /-->'
        md = f"One.\n\n{block1}\n\nTwo.\n\n{block2}\n\nThree."
        result = converter.convert(md)
        assert block1 in result
        assert block2 in result
        assert result.index(block1) < result.index("Two") < result.index(block2)

    def test_gutenberg_inside_fenced_code_block_stays_code(self, converter):
        md = (
            "```html\n"
            "<!-- wp:cover -->\n"
            "<div>x</div>\n"
            "<!-- /wp:cover -->\n"
            "```"
        )
        result = converter.convert(md)
        assert "wp:code" in result
        assert "&lt;!-- wp:cover --&gt;" in result
        assert "<!-- wp:cover -->" not in result


class TestConfigurableImageAlign:
    """A site whose theme already places images can opt out of the alignment.

    Center is what every site using this tool has had, so it stays the
    default. h2gr's own publisher emitted no alignment, and forcing one on 415
    live articles would be a visible change nobody asked for.
    """

    def test_center_is_the_default(self):
        out = GutenbergConverter().convert("![a cat](https://x/a.jpg)")
        assert '"align":"center"' in out
        assert "wp-block-image aligncenter size-full" in out

    def test_none_produces_an_unaligned_block(self):
        out = GutenbergConverter(image_align=None).convert("![a cat](https://x/a.jpg)")
        assert '"align"' not in out
        assert "aligncenter" not in out
        assert 'class="wp-block-image size-full"' in out

    def test_another_alignment_is_honoured(self):
        out = GutenbergConverter(image_align="wide").convert("![a cat](https://x/a.jpg)")
        assert '"align":"wide"' in out
        assert "wp-block-image alignwide size-full" in out

    def test_the_image_is_otherwise_unchanged(self):
        aligned = GutenbergConverter().convert("![a cat](https://x/a.jpg)")
        plain = GutenbergConverter(image_align=None).convert("![a cat](https://x/a.jpg)")
        assert 'alt="a cat"' in aligned and 'alt="a cat"' in plain
        assert '"sizeSlug":"full"' in aligned and '"sizeSlug":"full"' in plain


# ---------------------------------------------------------------------------
# Images that are not alone in their paragraph (issue #27)
# ---------------------------------------------------------------------------


class TestImagesInsideText:
    def test_no_nul_byte_ever_reaches_the_output(self, converter):
        md = (
            "[![](https://x/a.jpg)](https://example.com/)\n\n"
            "Text ![](https://x/b.png) more text.\n\n"
            "# Head ![](https://x/c.png)\n\n"
            "- item ![](https://x/d.png)\n\n"
            "| A |\n| --- |\n| ![](https://x/e.png) |\n"
        )
        assert "\x00" not in converter.convert(md)

    def test_an_image_beside_text_is_a_plain_img(self, converter):
        out = converter.convert("Text ![b](https://x/b.png) more text.")
        assert out == (
            "<!-- wp:paragraph -->\n"
            '<p>Text <img src="https://x/b.png" alt="b"/> more text.</p>\n'
            "<!-- /wp:paragraph -->"
        )

    def test_an_inline_image_keeps_its_media_id_class(self):
        c = GutenbergConverter(image_handler=lambda url: (url, 42))
        out = c.convert("Text ![b](https://x/b.png) more.")
        assert '<img src="https://x/b.png" alt="b" class="wp-image-42"/>' in out
        assert "wp:image" not in out

    def test_a_linked_image_alone_is_one_linked_block(self, converter):
        out = converter.convert("[![a](https://x/a.jpg)](https://example.com/)")
        assert out == (
            '<!-- wp:image {"sizeSlug":"full","linkDestination":"custom","align":"center"} -->\n'
            '<figure class="wp-block-image aligncenter size-full">'
            '<a href="https://example.com/"><img src="https://x/a.jpg" alt="a"/></a></figure>\n'
            "<!-- /wp:image -->"
        )

    def test_a_linked_image_beside_text_stays_in_the_paragraph(self, converter):
        out = converter.convert("See [![a](https://x/a.jpg)](https://example.com/) here.")
        assert "wp:image" not in out
        assert '<a href="https://example.com/"><img src="https://x/a.jpg" alt="a"/></a>' in out

    def test_a_broken_bookmark_card_gives_clean_paragraphs(self, converter):
        # A bookmark card (see TestBookmarkCards) that lost its closing
        # "](url)": the blank lines break it apart, leaving each image
        # beside text.
        md = (
            "[![](https://x/card.jpg)\n\n"
            "Title | site\n\n"
            "![](https://x/favicon.ico)www.site.de"
        )
        out = converter.convert(md)
        assert "\x00" not in out
        assert "wp:image" not in out
        assert '<p>[<img src="https://x/card.jpg" alt=""/></p>' in out
        assert '<img src="https://x/favicon.ico" alt=""/>www.site.de' in out

    def test_each_image_block_is_written_once(self, converter):
        out = converter.convert("[![](https://x/a.jpg)](https://example.com/)")
        assert out.count("<!-- wp:image") == 1
        assert out.count("<!-- /wp:image -->") == 1


# ---------------------------------------------------------------------------
# A dropped image leaves no empty block behind (issue #29)
# ---------------------------------------------------------------------------


class TestDroppedImage:
    @pytest.fixture
    def dropping(self):
        # The handler's answer for a local file that is missing.
        return GutenbergConverter(image_handler=lambda url: (None, None))

    def test_a_lone_dropped_image_leaves_no_block(self, dropping):
        out = dropping.convert("Before.\n\n![x](missing.jpg)\n\nAfter.")
        assert "<p></p>" not in out
        assert out.count("<!-- wp:paragraph -->") == 2

    def test_a_lone_dropped_linked_image_leaves_no_empty_link(self, dropping):
        out = dropping.convert("[![x](missing.jpg)](https://e.com/)")
        assert out == ""

    def test_text_around_a_dropped_image_stays(self, dropping):
        out = dropping.convert("Text ![x](missing.jpg) more.")
        assert "<p>Text  more.</p>" in out

    def test_a_link_with_its_own_text_stays(self, dropping):
        out = dropping.convert("[see ![x](missing.jpg)](https://e.com/)")
        assert '<a href="https://e.com/">see </a>' in out


# ---------------------------------------------------------------------------
# Bookmark cards (mamaduka/bookmark-card), issue #33
# ---------------------------------------------------------------------------

# A real card as the news-feed ingest writes it, and the block the editor
# stored for it on live. Blank lines between the parts are the usual shape.
CARD_MD = (
    "[![](https://www.idowa.de/imgs/w766.jpeg)\n"
    "\n"
    "Rudolf Hell - der Jahrhundert-Ingenieur aus Eggmühl\n"
    "\n"
    "idowa.de informiert Sie zuverlässig über aktuelle Nachrichten\n"
    "\n"
    "![](https://www.idowa.de/favicon.ico)www.idowa.de](https://www.idowa.de/inhalt.a23b.html)"
)
CARD_BLOCK = (
    '<!-- wp:mamaduka/bookmark-card {"url":"https://www.idowa.de/inhalt.a23b.html",'
    '"className":"is-style-horizontal"} -->\n'
    '<figure class="wp-block-mamaduka-bookmark-card is-style-horizontal">'
    '<a class="bookmark-card" href="https://www.idowa.de/inhalt.a23b.html">'
    '<div class="bookmark-card__image"><img src="https://www.idowa.de/imgs/w766.jpeg"/></div>'
    '<div class="bookmark-card__content">'
    '<div class="bookmark-card__title">Rudolf Hell - der Jahrhundert-Ingenieur aus Eggmühl</div>'
    '<div class="bookmark-card__description">idowa.de informiert Sie zuverlässig über aktuelle Nachrichten</div>'
    '<div class="bookmark_card__meta">'
    '<img class="bookmark_card__meta-icon" src="https://www.idowa.de/favicon.ico"/>'
    '<span class="bookmark_card__meta-publisher">www.idowa.de</span>'
    "</div></div></a></figure>\n"
    "<!-- /wp:mamaduka/bookmark-card -->"
)


class TestBookmarkCards:
    def test_a_real_card_becomes_the_block_the_editor_stores(self, converter):
        assert converter.convert(CARD_MD) == CARD_BLOCK

    def test_a_card_without_blank_lines_is_the_same_card(self, converter):
        tight = CARD_MD.replace("\n\n", "\n")
        assert converter.convert(tight) == CARD_BLOCK

    def test_card_images_are_never_uploaded(self):
        seen = []
        c = GutenbergConverter(image_handler=lambda url: (seen.append(url), ("x", 1))[1])
        assert c.convert(CARD_MD) == CARD_BLOCK
        assert seen == []

    def test_text_around_the_card_stays_paragraphs(self, converter):
        out = converter.convert(f"Before.\n\n{CARD_MD}\n\nAfter.")
        assert out == (
            "<!-- wp:paragraph -->\n<p>Before.</p>\n<!-- /wp:paragraph -->\n\n"
            f"{CARD_BLOCK}\n\n"
            "<!-- wp:paragraph -->\n<p>After.</p>\n<!-- /wp:paragraph -->"
        )

    def test_a_publisher_without_a_favicon(self, converter):
        out = converter.convert(
            "[![](https://e.com/i.jpg)\nTitle\nSummary.\nwww.e.com](https://e.com/a)")
        assert "meta-icon" not in out
        assert '<span class="bookmark_card__meta-publisher">www.e.com</span>' in out
        assert '<div class="bookmark-card__description">Summary.</div>' in out

    def test_title_only_takes_the_publisher_from_the_url(self, converter):
        out = converter.convert("[![](https://e.com/i.jpg)\nJust a title](https://www.e.com/a)")
        assert '<div class="bookmark-card__title">Just a title</div>' in out
        assert '<div class="bookmark-card__description"></div>' in out
        assert '<span class="bookmark_card__meta-publisher">e.com</span>' in out

    def test_no_publisher_line_keeps_every_line_after_the_title(self, converter):
        out = converter.convert(
            "[![](https://e.com/i.jpg)\nTitle\nFirst line.\nSecond line.](https://e.com/a)")
        assert '<div class="bookmark-card__description">First line. Second line.</div>' in out
        assert '<span class="bookmark_card__meta-publisher">e.com</span>' in out

    def test_image_alt_text_is_dropped(self, converter):
        out = converter.convert("[![a photo](https://e.com/i.jpg)\nTitle](https://e.com/a)")
        assert '<img src="https://e.com/i.jpg"/>' in out

    def test_text_is_escaped_like_the_editor_does(self, converter):
        out = converter.convert(
            '[![](https://e.com/i.jpg)\nCats & "dogs" <3\nA &amp; B](https://e.com/a?x=1&y=2)')
        assert '<div class="bookmark-card__title">Cats &amp; "dogs" &lt;3</div>' in out
        assert '<div class="bookmark-card__description">A &amp; B</div>' in out
        assert 'href="https://e.com/a?x=1&amp;y=2"' in out
        assert '{"url":"https://e.com/a?x=1\\u0026y=2"' in out

    def test_a_plain_inline_link_stays_inline(self, converter):
        out = converter.convert("Read [the article](https://e.com/a) today.")
        assert "bookmark-card" not in out
        assert '<a href="https://e.com/a">the article</a>' in out

    def test_a_link_without_an_image_stays_a_link(self, converter):
        out = converter.convert("[Title\nSummary\ne.com](https://e.com/a)")
        assert "bookmark-card" not in out

    def test_a_plain_image_is_still_an_image_block(self, converter):
        out = converter.convert("![alt](https://e.com/i.jpg)")
        assert "wp:image" in out
        assert "bookmark-card" not in out

    def test_a_linked_image_is_still_an_image_block(self, converter):
        out = converter.convert("[![alt](https://e.com/i.jpg)](https://e.com/a)")
        assert "wp:image" in out
        assert "bookmark-card" not in out

    def test_an_unclosed_card_is_left_alone(self, converter):
        out = converter.convert("[![](https://e.com/i.jpg)\n\nTitle\n\nMore text.")
        assert "bookmark-card" not in out
        assert "Title" in out and "More text." in out

    def test_an_unclosed_image_link_before_a_later_link_is_not_a_card(self, converter):
        out = converter.convert(
            "[![](https://e.com/i.jpg)\n\nTitle\n\nRead [more](https://e.com/b) here](https://e.com/a)")
        assert "bookmark-card" not in out

    def test_a_card_in_a_code_fence_is_shown_as_code(self, converter):
        out = converter.convert(f"```\n{CARD_MD}\n```")
        assert "wp:code" in out
        assert "wp:mamaduka" not in out


# ---------------------------------------------------------------------------
# Emphasis next to punctuation (issue #43)
# ---------------------------------------------------------------------------

_MISTUNE_HAS_FLANKING_RULE = tuple(int(n) for n in mistune.__version__.split(".")[:2]) >= (3, 3)


class TestEmphasisNextToPunctuation:
    """mistune 3.3+ follows CommonMark here; wp-post keeps the 3.2 output."""

    @pytest.mark.parametrize(
        "md, html",
        [
            ("**Rates:**Before.", "<strong>Rates:</strong>Before."),
            ("**Fragen?**Kontaktieren Sie uns", "<strong>Fragen?</strong>Kontaktieren Sie uns"),
            ("**簡潔な回答：**確認します", "<strong>簡潔な回答：</strong>確認します"),
            ("**연락처(예시)**를", "<strong>연락처(예시)</strong>를"),
            ("**Rates:** Before.", "<strong>Rates:</strong> Before."),
            ("*note:*x", "<em>note:</em>x"),
            ("a**(b)**c", "a<strong>(b)</strong>c"),
            ("「**重要**」です", "「<strong>重要</strong>」です"),
            ("**a.**", "<strong>a.</strong>"),
        ],
    )
    def test_star_emphasis_closes_and_opens_next_to_punctuation(self, converter, md, html):
        assert f"<p>{html}</p>" in converter.convert(md)

    @pytest.mark.parametrize(
        "md, html",
        [
            # The same output as 3.2, where CommonMark nests or stays literal.
            ('a**"foo"**', "a<strong>\"foo\"</strong>"),
            ("**(**foo)", "<strong>(</strong>foo)"),
            ("*(*foo*)*", "<em>(</em>foo<em>)</em>"),
        ],
    )
    def test_matches_mistune_3_2_where_it_differs_from_commonmark(self, converter, md, html):
        assert f"<p>{html}</p>" in converter.convert(md)

    def test_underscore_keeps_mistunes_rule(self, converter):
        assert "<p>__a:__b</p>" in converter.convert("__a:__b")

    def test_whitespace_still_stops_emphasis(self, converter):
        assert "<p>** a**</p>" in converter.convert("** a**")
        assert "<p>2 * 3 * 4</p>" in converter.convert("2 * 3 * 4")


@pytest.mark.skipif(not _MISTUNE_HAS_FLANKING_RULE, reason="mistune < 3.3 has no flanking rule to replace")
class TestFlankingPatchGuard:
    """The rule is replaced in mistune's private module, so a move must fail loudly."""

    def test_the_patch_target_exists_on_this_mistune(self):
        from mistune._inline import emphasis
        GutenbergConverter()
        assert emphasis._can_open_emphasis._wp_poster
        assert emphasis._can_close_emphasis._wp_poster

    def test_a_missing_function_is_an_error(self, monkeypatch):
        from mistune._inline import emphasis
        monkeypatch.delattr(emphasis, "_can_close_emphasis")
        monkeypatch.setattr(emphasis, "_can_open_emphasis", lambda text, start, size, marker: True)
        with pytest.raises(RuntimeError, match="#43"):
            GutenbergConverter()

    def test_a_changed_signature_is_an_error(self, monkeypatch):
        from mistune._inline import emphasis
        monkeypatch.setattr(emphasis, "_can_open_emphasis", lambda text, start: True)
        with pytest.raises(RuntimeError, match="#43"):
            GutenbergConverter()


class TestLeftoverEmphasisWarning:
    """A `*` pair that reaches the page as literal text is reported, not posted silently."""

    @pytest.fixture
    def commonmark_rule(self, monkeypatch):
        """Put a strict closing rule back, as an unpatched mistune 3.3+ would."""
        if not _MISTUNE_HAS_FLANKING_RULE:
            pytest.skip("mistune < 3.3 has no flanking rule to replace")
        from mistune._inline import emphasis
        warnings = []
        converter = GutenbergConverter(warn=warnings.append)
        original = emphasis._can_close_emphasis

        def strict(text, start, size, marker):
            previous = text[start - 1] if start > 0 else "\n"
            following = text[start + size] if start + size < len(text) else "\n"
            if not previous.isalnum() and following.isalnum():
                return False
            return original(text, start, size, marker)

        monkeypatch.setattr(emphasis, "_can_close_emphasis", strict)
        return converter, warnings

    def test_literal_pair_is_reported_with_its_line(self, commonmark_rule):
        converter, warnings = commonmark_rule
        out = converter.convert("Intro.\n\n**Rates:**Before.", line_offset=4)
        assert "**Rates:**Before." in out
        assert warnings == ["line 7: **Rates:** shows as literal asterisks, not bold or italic"]

    def test_repeated_pair_is_reported_on_each_line(self, commonmark_rule):
        converter, warnings = commonmark_rule
        converter.convert("**a:**b\n\n**a:**b")
        assert [w.split(":")[0] for w in warnings] == ["line 1", "line 3"]

    def test_rendered_emphasis_is_not_reported(self):
        warnings = []
        GutenbergConverter(warn=warnings.append).convert("**Rates:**Before. *x* and **y**")
        assert warnings == []

    @pytest.mark.parametrize(
        "md",
        [
            r"\*\*escaped\*\*",
            "`**code**`",
            "```\n**Rates:**Before.\n```",
            "2 * 3 * 4",
        ],
    )
    def test_intended_asterisks_are_not_reported(self, md):
        warnings = []
        GutenbergConverter(warn=warnings.append).convert(md)
        assert warnings == []
