"""Tests for callouts.py - configuration, colour resolution, and rendering."""

import pytest

import callouts


class TestColorResolution:
    def test_slug_becomes_preset_reference(self):
        assert callouts.color_attr("primary") == "var:preset|color|primary"

    def test_slug_becomes_css_var(self):
        assert callouts.color_css("primary") == "var(--wp--preset--color--primary)"

    def test_hex_passes_through_as_attribute(self):
        assert callouts.color_attr("#cf2e2e") == "#cf2e2e"

    def test_hex_passes_through_as_css(self):
        assert callouts.color_css("#cf2e2e") == "#cf2e2e"

    def test_short_hex_is_hex(self):
        assert callouts.color_attr("#abc") == "#abc"

    def test_eight_digit_hex_is_hex(self):
        assert callouts.color_css("#cf2e2eff") == "#cf2e2eff"

    def test_hyphenated_slug_is_not_hex(self):
        assert callouts.color_attr("border-light") == "var:preset|color|border-light"


class TestMergeConfig:
    def test_no_user_config_returns_defaults(self):
        merged = callouts.merge_config(None)
        assert merged["background"] == callouts.DEFAULT_CONFIG["background"]
        assert set(merged["types"]) == set(callouts.CALLOUT_TYPES)

    def test_partial_override_leaves_other_fields(self):
        merged = callouts.merge_config({"types": {"note": {"label": "Hinweis"}}})
        assert merged["types"]["note"]["label"] == "Hinweis"
        assert merged["types"]["note"]["color"] == callouts.DEFAULT_CONFIG["types"]["note"]["color"]

    def test_partial_override_leaves_other_types(self):
        merged = callouts.merge_config({"types": {"note": {"label": "Hinweis"}}})
        assert merged["types"]["tip"]["label"] == callouts.DEFAULT_CONFIG["types"]["tip"]["label"]

    def test_background_override(self):
        merged = callouts.merge_config({"background": "#eeeeee"})
        assert merged["background"] == "#eeeeee"

    def test_unknown_type_warns_and_is_ignored(self):
        warnings = []
        merged = callouts.merge_config(
            {"types": {"sidebar": {"label": "Sidebar"}}}, warn=warnings.append
        )
        assert "sidebar" not in merged["types"]
        assert len(warnings) == 1
        assert "sidebar" in warnings[0]

    def test_type_name_matching_is_case_insensitive(self):
        merged = callouts.merge_config({"types": {"NOTE": {"label": "Nota"}}})
        assert merged["types"]["note"]["label"] == "Nota"

    def test_defaults_are_not_mutated_by_merge(self):
        merged = callouts.merge_config({"types": {"note": {"label": "Changed"}}})
        merged["types"]["note"]["label"] = "Changed again"
        assert callouts.DEFAULT_CONFIG["types"]["note"]["label"] == "Note"


class TestMalformedConfig:
    """Config is hand-edited JSON, so every field may be the wrong type.

    The global constraint is that no callout failure may fail a publish,
    which means merge_config must never raise.
    """

    def test_non_dict_config_warns_and_uses_defaults(self):
        warnings = []
        merged = callouts.merge_config("garbage", warn=warnings.append)
        assert merged["background"] == callouts.DEFAULT_CONFIG["background"]
        assert len(warnings) == 1

    def test_null_background_falls_back_to_default(self):
        merged = callouts.merge_config({"background": None})
        assert merged["background"] == callouts.DEFAULT_CONFIG["background"]

    def test_empty_background_falls_back_to_default(self):
        merged = callouts.merge_config({"background": "   "})
        assert merged["background"] == callouts.DEFAULT_CONFIG["background"]

    def test_non_dict_types_warns_and_is_ignored(self):
        warnings = []
        merged = callouts.merge_config({"types": "note"}, warn=warnings.append)
        assert set(merged["types"]) == set(callouts.CALLOUT_TYPES)
        assert len(warnings) == 1

    def test_null_type_override_warns_and_is_skipped(self):
        warnings = []
        merged = callouts.merge_config({"types": {"note": None}}, warn=warnings.append)
        assert merged["types"]["note"]["label"] == "Note"
        assert len(warnings) == 1

    def test_non_string_color_falls_back_to_default(self):
        merged = callouts.merge_config({"types": {"note": {"color": 42}}})
        assert merged["types"]["note"]["color"] == "primary"

    def test_non_string_icon_falls_back_to_builtin(self):
        merged = callouts.merge_config({"types": {"note": {"icon": 42}}})
        assert callouts.icon_html("note", merged).startswith("<svg")

    def test_no_config_shape_raises(self):
        for hostile in (None, {}, [], 0, "x", {"types": None}, {"types": {"note": []}},
                        {"background": 1, "padding": None}):
            merged = callouts.merge_config(hostile, warn=lambda m: None)
            assert set(merged["types"]) == set(callouts.CALLOUT_TYPES), hostile


class TestIconHtml:
    def test_builtin_icon_is_svg_with_current_color(self):
        cfg = callouts.merge_config(None)
        html = callouts.icon_html("note", cfg)
        assert html.startswith("<svg")
        assert 'fill="currentColor"' in html

    def test_empty_icon_config_disables_icon(self):
        cfg = callouts.merge_config({"types": {"note": {"icon": ""}}})
        assert callouts.icon_html("note", cfg) == ""

    def test_custom_icon_string_is_used_verbatim(self):
        cfg = callouts.merge_config({"types": {"note": {"icon": "ℹ️"}}})
        assert callouts.icon_html("note", cfg) == "ℹ️"

    def test_every_type_has_a_builtin_icon(self):
        cfg = callouts.merge_config(None)
        for name in callouts.CALLOUT_TYPES:
            assert callouts.icon_html(name, cfg).startswith("<svg"), name


from gutenberg import GutenbergConverter


def convert(md, **kwargs):
    return GutenbergConverter(image_handler=lambda url: (url, None), **kwargs).convert(md)


class TestSimpleCallouts:
    def test_note_emits_a_group_not_a_quote(self):
        result = convert("> [!NOTE]\n> A note.")
        assert "wp:group" in result
        assert "wp:quote" not in result

    def test_note_carries_both_classes(self):
        result = convert("> [!NOTE]\n> A note.")
        assert 'class="wp-block-group is-callout is-callout-note' in result

    def test_note_label_and_body_present(self):
        result = convert("> [!NOTE]\n> A note.")
        assert "Note</strong>" in result
        assert "A note." in result

    def test_background_slug_becomes_class_and_attribute(self):
        result = convert("> [!NOTE]\n> A note.")
        assert '"backgroundColor":"tertiary"' in result
        assert "has-tertiary-background-color has-background" in result

    def test_accent_slug_becomes_preset_reference_and_css_var(self):
        result = convert("> [!NOTE]\n> A note.")
        assert '"color":"var:preset|color|primary"' in result
        assert "border-left-color:var(--wp--preset--color--primary)" in result

    def test_border_declares_a_style_so_it_is_visible(self):
        # border-style defaults to none, which zeroes border-width, so a
        # colour and width alone would render nothing at all.
        result = convert("> [!NOTE]\n> A note.")
        assert "border-left-style:solid" in result
        assert '"style":"solid"' in result

    def test_malformed_config_still_renders(self):
        result = convert("> [!NOTE]\n> Body.", callout_config={"types": {"note": None}})
        assert "is-callout-note" in result
        assert "Note</strong>" in result

    def test_hex_accent_config_emits_literal(self):
        cfg = {"types": {"caution": {"color": "#cf2e2e"}}}
        result = convert("> [!CAUTION]\n> Danger.", callout_config=cfg)
        assert "border-left-color:#cf2e2e" in result
        assert "var:preset|color|#cf2e2e" not in result

    def test_hex_background_config_emits_style_not_class(self):
        result = convert("> [!NOTE]\n> A note.", callout_config={"background": "#eeeeee"})
        assert "background-color:#eeeeee" in result
        assert "has-background" in result
        assert '"backgroundColor"' not in result

    def test_label_override_is_used(self):
        cfg = {"types": {"note": {"label": "Hinweis"}}}
        result = convert("> [!NOTE]\n> A note.", callout_config=cfg)
        assert "Hinweis</strong>" in result
        assert "Note</strong>" not in result

    def test_icon_is_svg_inheriting_current_color(self):
        result = convert("> [!TIP]\n> A tip.")
        assert 'fill="currentColor"' in result

    def test_all_five_gfm_types_still_recognised(self):
        for name in ("note", "tip", "important", "warning", "caution"):
            result = convert(f"> [!{name.upper()}]\n> Body.")
            assert f"is-callout-{name}" in result, name

    def test_summary_renders_a_list_as_a_list_block(self):
        md = "> [!SUMMARY]\n> - First point\n> - Second point"
        result = convert(md)
        assert "is-callout-summary" in result
        assert "wp:list" in result
        assert "First point" in result
        assert "Second point" in result

    def test_case_insensitive(self):
        assert "is-callout-important" in convert("> [!important]\n> Body.")

    def test_multiple_paragraphs_preserved(self):
        md = "> [!NOTE]\n>\n> First paragraph.\n>\n> Second paragraph."
        result = convert(md)
        assert "First paragraph." in result
        assert "Second paragraph." in result

    def test_inline_formatting_preserved(self):
        result = convert("> [!TIP]\n> Use `code` and **bold**.")
        assert "<code>code</code>" in result
        assert "<strong>bold</strong>" in result

    def test_regular_blockquote_untouched(self):
        result = convert("> Just a quote.")
        assert "is-callout" not in result
        assert "wp:quote" in result

    def test_block_attributes_are_valid_json(self):
        import json
        import re as _re

        result = convert("> [!NOTE]\n> A note.")
        raw = _re.search(r"<!-- wp:group (\{.*?\}) -->", result).group(1)
        attrs = json.loads(raw)
        assert attrs["className"] == "is-callout is-callout-note"
        assert attrs["style"]["border"]["left"]["width"] == "4px"
        assert attrs["style"]["border"]["left"]["style"] == "solid"


class TestFaqSplitting:
    def test_splits_two_pairs(self):
        body = "**First question?**\nFirst answer.\n\n**Second question?**\nSecond answer.\n"
        preamble, pairs = callouts._split_faq(body)
        assert preamble.strip() == ""
        assert len(pairs) == 2
        assert pairs[0][0] == "First question?"
        assert "First answer." in pairs[0][1]
        assert pairs[1][0] == "Second question?"

    def test_no_questions_returns_body_as_preamble(self):
        preamble, pairs = callouts._split_faq("Just prose.\n")
        assert pairs == []
        assert preamble.strip() == "Just prose."

    def test_text_before_first_question_is_preamble(self):
        body = "Intro line.\n\n**A question?**\nAn answer.\n"
        preamble, pairs = callouts._split_faq(body)
        assert "Intro line." in preamble
        assert len(pairs) == 1


class TestFaqRendering:
    def test_emits_details_block_per_pair(self):
        md = (
            "> [!FAQ]\n"
            "> **How long does setup take?**\n"
            "> About ten minutes.\n"
            ">\n"
            "> **Is there a free tier?**\n"
            "> Yes.\n"
        )
        result = convert(md)
        assert result.count("<!-- wp:details -->") == 2
        assert result.count("<!-- /wp:details -->") == 2

    def test_question_is_an_inline_h3_with_no_margin(self):
        md = "> [!FAQ]\n> **How long?**\n> Ten minutes.\n"
        result = convert(md)
        assert '<summary><h3 style="display:inline;margin:0">How long?</h3></summary>' in result

    def test_answer_is_a_paragraph_block(self):
        md = "> [!FAQ]\n> **How long?**\n> Ten minutes.\n"
        result = convert(md)
        assert "<!-- wp:paragraph -->\n<p>Ten minutes.</p>" in result

    def test_wrapped_in_the_callout_group(self):
        md = "> [!FAQ]\n> **How long?**\n> Ten minutes.\n"
        result = convert(md)
        assert "is-callout-faq" in result
        assert "Frequently asked questions</strong>" in result

    def test_answer_may_contain_a_list(self):
        md = "> [!FAQ]\n> **What is included?**\n> - First\n> - Second\n"
        result = convert(md)
        assert "wp:list" in result
        assert "First" in result
        assert "Second" in result

    def test_question_html_is_escaped(self):
        md = "> [!FAQ]\n> **Is 5 < 6?**\n> Yes.\n"
        result = convert(md)
        assert "5 &lt; 6?" in result

    def test_body_with_no_questions_warns_and_renders_as_content(self, capsys):
        result = convert("> [!FAQ]\n> Just prose, no questions.\n")
        assert "is-callout-faq" in result
        assert "Just prose, no questions." in result
        assert "wp:details" not in result
        assert "no questions" in capsys.readouterr().err.lower()
