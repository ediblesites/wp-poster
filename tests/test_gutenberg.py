"""Tests for gutenberg.py — GutenbergConverter."""

from gutenberg import GutenbergConverter


# ---------------------------------------------------------------------------
# Helper methods (pure functions)
# ---------------------------------------------------------------------------

class TestIsListItem:
    def test_unordered_dash(self, converter):
        assert converter._is_list_item("- item")

    def test_unordered_asterisk(self, converter):
        assert converter._is_list_item("* item")

    def test_unordered_plus(self, converter):
        assert converter._is_list_item("+ item")

    def test_ordered_dot(self, converter):
        assert converter._is_list_item("1. item")

    def test_ordered_paren(self, converter):
        assert converter._is_list_item("1) item")

    def test_indented(self, converter):
        assert converter._is_list_item("  - nested item")

    def test_plain_text(self, converter):
        assert not converter._is_list_item("just text")

    def test_empty_string(self, converter):
        assert not converter._is_list_item("")


class TestGetListType:
    def test_ordered(self, converter):
        assert converter._get_list_type("1. item") == "ordered"

    def test_unordered(self, converter):
        assert converter._get_list_type("- item") == "unordered"

    def test_ordered_paren(self, converter):
        assert converter._get_list_type("2) item") == "ordered"


class TestExtractListItemContent:
    def test_unordered(self, converter):
        assert converter._extract_list_item_content("- hello world") == "hello world"

    def test_ordered(self, converter):
        assert converter._extract_list_item_content("1. hello world") == "hello world"

    def test_indented(self, converter):
        assert converter._extract_list_item_content("  - nested") == "nested"


class TestGetIndentationLevel:
    def test_no_indent(self, converter):
        assert converter._get_indentation_level("hello") == 0

    def test_two_spaces(self, converter):
        assert converter._get_indentation_level("  hello") == 2

    def test_four_spaces(self, converter):
        assert converter._get_indentation_level("    hello") == 4


# ---------------------------------------------------------------------------
# Inline markdown
# ---------------------------------------------------------------------------

class TestInlineMarkdown:
    def test_bold(self, converter):
        result = converter._process_inline_markdown("**bold**")
        assert "<strong>bold</strong>" in result

    def test_italic(self, converter):
        result = converter._process_inline_markdown("*italic*")
        assert "<em>italic</em>" in result

    def test_bold_italic(self, converter):
        result = converter._process_inline_markdown("***both***")
        assert "<strong><em>both</em></strong>" in result

    def test_strikethrough(self, converter):
        result = converter._process_inline_markdown("~~deleted~~")
        assert "<del>deleted</del>" in result

    def test_inline_code(self, converter):
        result = converter._process_inline_markdown("use `foo()` here")
        assert "<code>foo()</code>" in result

    def test_inline_code_escapes_html(self, converter):
        result = converter._process_inline_markdown("`<div>`")
        assert "<code>&lt;div&gt;</code>" in result

    def test_link(self, converter):
        result = converter._process_inline_markdown("[click](https://example.com)")
        assert '<a href="https://example.com">click</a>' in result

    def test_line_break(self, converter):
        result = converter._process_inline_markdown("line1\nline2")
        assert "line1<br>line2" in result


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
        assert "<li>parent</li>" in result
        assert "<li>child</li>" in result


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
