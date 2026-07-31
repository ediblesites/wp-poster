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
