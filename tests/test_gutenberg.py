"""Tests for gutenberg.py — GutenbergConverter."""

from gutenberg import GutenbergConverter


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
        result = converter.convert("## Subtitle")
        assert '"level":2' in result
        assert "<h2" in result

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
        assert "<ul>" in result
        assert "<li>one</li>" in result

    def test_ordered_list(self, converter):
        md = "1. one\n2. two\n3. three"
        result = converter.convert(md)
        assert '"ordered":true' in result
        assert "<ol>" in result
        assert "<li>one</li>" in result

    def test_nested_list(self, converter):
        md = "- parent\n  - child"
        result = converter.convert(md)
        assert "wp:list" in result
        assert "parent" in result
        assert "<li>child</li>" in result

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


class TestAdmonitions:
    def test_important(self, converter):
        md = "> [!IMPORTANT]\n> This is important."
        result = converter.convert(md)
        assert "is-admonition" in result
        assert "is-admonition-important" in result
        assert "Important" in result
        assert "This is important." in result

    def test_note(self, converter):
        md = "> [!NOTE]\n> A note."
        result = converter.convert(md)
        assert "is-admonition-note" in result
        assert "Note</p>" in result

    def test_tip(self, converter):
        md = "> [!TIP]\n> A tip."
        result = converter.convert(md)
        assert "is-admonition-tip" in result
        assert "Tip</p>" in result

    def test_warning(self, converter):
        md = "> [!WARNING]\n> Be careful."
        result = converter.convert(md)
        assert "is-admonition-warning" in result
        assert "Warning</p>" in result

    def test_caution(self, converter):
        md = "> [!CAUTION]\n> Danger zone."
        result = converter.convert(md)
        assert "is-admonition-caution" in result
        assert "Caution</p>" in result

    def test_admonition_with_multiple_paragraphs(self, converter):
        md = "> [!NOTE]\n>\n> First paragraph.\n>\n> Second paragraph."
        result = converter.convert(md)
        assert "is-admonition-note" in result
        assert "First paragraph." in result
        assert "Second paragraph." in result

    def test_admonition_case_insensitive(self, converter):
        md = "> [!important]\n> Text."
        result = converter.convert(md)
        assert "is-admonition-important" in result

    def test_regular_blockquote_unchanged(self, converter):
        result = converter.convert("> Just a regular quote.")
        assert "is-admonition" not in result
        assert "wp:quote" in result

    def test_admonition_preserves_inline_formatting(self, converter):
        md = "> [!TIP]\n> Use `code` and **bold** here."
        result = converter.convert(md)
        assert "is-admonition-tip" in result
        assert "<code>code</code>" in result
        assert "<strong>" in result

    def test_admonition_has_inline_border_color(self, converter):
        md = "> [!WARNING]\n> Watch out."
        result = converter.convert(md)
        assert 'style="border-left-color: #9a6700;"' in result

    def test_admonition_has_svg_icon(self, converter):
        md = "> [!NOTE]\n> Info here."
        result = converter.convert(md)
        assert "<svg" in result
        assert 'fill="#0969da"' in result

    def test_admonition_title_color_matches_type(self, converter):
        md = "> [!CAUTION]\n> Danger."
        result = converter.convert(md)
        assert 'color: #d1242f;' in result


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
