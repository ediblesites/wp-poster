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
        assert merged["types"]["note"]["color"] == "#0969da"

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
        # summary has no cross-site convention, so it keeps the theme slug.
        result = convert("> [!SUMMARY]\n> - A point.")
        assert '"color":"var:preset|color|primary"' in result
        assert "border-left-color:var(--wp--preset--color--primary)" in result

    def test_gfm_types_default_to_the_conventional_hues(self):
        # A palette slug cannot carry hue meaning, so the five GFM types
        # ship GitHub's colours instead. Readers already know amber warns
        # and red stops; a theme's `primary` says nothing about severity.
        for name, hue in (
            ("note", "#0969da"),
            ("tip", "#1a7f37"),
            ("important", "#8250df"),
            ("warning", "#9a6700"),
            ("caution", "#d1242f"),
        ):
            result = convert(f"> [!{name.upper()}]\n> Body.")
            assert f"border-left-color:{hue}" in result, name
            assert f'"color":"{hue}"' in result, name
            assert "var:preset|color|" not in result, name

    def test_non_gfm_types_keep_the_theme_accent(self):
        for md in ("> [!SUMMARY]\n> - A point.", "> [!FAQ]\n> **Q?**\n> A."):
            result = convert(md)
            assert "border-left-color:var(--wp--preset--color--primary)" in result, md

    def test_background_stays_on_the_theme_for_hue_typed_callouts(self):
        # Only the accent carries the hue; the box still picks up the
        # site's tint so callouts do not read as imported GitHub chrome.
        result = convert("> [!CAUTION]\n> Danger.")
        assert '"backgroundColor":"tertiary"' in result
        assert "has-tertiary-background-color has-background" in result

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

    def test_bold_line_without_blank_line_above_stays_in_the_answer(self):
        body = (
            "**Real question?**\n"
            "**Note:**\n"
            "This is important context inside the answer.\n"
        )
        preamble, pairs = callouts._split_faq(body)
        assert len(pairs) == 1
        assert pairs[0][0] == "Real question?"
        assert "**Note:**" in pairs[0][1]
        assert "This is important context inside the answer." in pairs[0][1]

    def test_question_at_start_of_body_is_detected(self):
        body = "**Only question?**\nOnly answer.\n"
        preamble, pairs = callouts._split_faq(body)
        assert len(pairs) == 1
        assert pairs[0][0] == "Only question?"

    def test_empty_answer_is_skipped_and_warns(self):
        body = "**Empty question?**\n\n**Real question?**\nAn answer.\n"
        warnings = []
        preamble, pairs = callouts._split_faq(body, warn=warnings.append)
        assert len(pairs) == 1
        assert pairs[0][0] == "Real question?"
        assert len(warnings) == 1
        assert "no answer" in warnings[0].lower()


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

    def test_bold_line_glued_to_answer_does_not_start_a_new_accordion(self):
        md = (
            "> [!FAQ]\n"
            "> **Real question?**\n"
            "> **Note:**\n"
            "> This is important context inside the answer.\n"
        )
        result = convert(md)
        assert result.count("<!-- wp:details -->") == 1
        assert "<summary><h3 style=\"display:inline;margin:0\">Note:</h3></summary>" not in result
        assert "This is important context inside the answer." in result

    def test_two_question_faq_with_blank_line_between_still_works(self):
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

    def test_question_with_empty_answer_is_skipped_and_warns(self, capsys):
        md = (
            "> [!FAQ]\n"
            "> **Empty question?**\n"
            ">\n"
            "> **Real question?**\n"
            "> An answer.\n"
        )
        result = convert(md)
        assert result.count("<!-- wp:details -->") == 1
        assert "Empty question?" not in result
        assert "Real question?" in result
        assert "no answer" in capsys.readouterr().err.lower()


FULL_BOOKMARK = {
    "title": "My Other Post",
    "link": "https://example.com/my-other-post/",
    "excerpt": "A short excerpt.",
    "image_url": "https://example.com/thumb.jpg",
    "image_id": 123,
}

NO_IMAGE_BOOKMARK = dict(FULL_BOOKMARK, image_url=None, image_id=None)


class TestBookmark:
    def test_with_image_uses_media_text(self):
        result = convert(
            "> [!BOOKMARK]\n> /my-other-post/",
            bookmark_resolver=lambda target: FULL_BOOKMARK,
        )
        assert "wp:media-text" in result
        assert 'class="wp-image-123 size-full"' in result
        assert "https://example.com/thumb.jpg" in result

    def test_media_text_wrapper_style_matches_the_mediawidth_attribute(self):
        # core/media-text's own save() derives the wrapper's
        # grid-template-columns style from the block's mediaWidth
        # attribute; Gutenberg's block validator re-derives the expected
        # markup from the attributes and rejects the block if the two
        # disagree, so the emitted percentage must match what's in the
        # block comment's "mediaWidth" value exactly.
        import json
        import re as _re

        result = convert(
            "> [!BOOKMARK]\n> /my-other-post/",
            bookmark_resolver=lambda target: FULL_BOOKMARK,
        )
        raw = _re.search(r"<!-- wp:media-text (\{.*?\}) -->", result).group(1)
        attrs = json.loads(raw)
        assert f'style="grid-template-columns:{attrs["mediaWidth"]}% auto"' in result

    def test_media_text_image_has_size_full_class(self):
        # core/media-text's save() adds "size-{mediaSizeSlug}" alongside
        # "wp-image-{id}" whenever an attachment id is present; the
        # block's mediaSizeSlug attribute is never set here, so core
        # defaults it to "full".
        result = convert(
            "> [!BOOKMARK]\n> /my-other-post/",
            bookmark_resolver=lambda target: FULL_BOOKMARK,
        )
        assert "size-full" in result

    def test_with_image_includes_title_excerpt_and_link(self):
        result = convert(
            "> [!BOOKMARK]\n> /my-other-post/",
            bookmark_resolver=lambda target: FULL_BOOKMARK,
        )
        assert '<a href="https://example.com/my-other-post/">My Other Post</a>' in result
        assert "A short excerpt." in result
        assert "Read next</strong>" in result

    def test_without_image_falls_back_to_group(self):
        result = convert(
            "> [!BOOKMARK]\n> /my-other-post/",
            bookmark_resolver=lambda target: NO_IMAGE_BOOKMARK,
        )
        assert "wp:media-text" not in result
        assert "is-callout-bookmark" in result
        assert "My Other Post" in result

    def test_resolver_receives_the_raw_target(self):
        seen = []

        def resolver(target):
            seen.append(target)
            return FULL_BOOKMARK

        convert("> [!BOOKMARK]\n> /my-other-post/", bookmark_resolver=resolver)
        assert seen == ["/my-other-post/"]

    def test_unresolved_target_warns_and_emits_link_card(self, capsys):
        result = convert(
            "> [!BOOKMARK]\n> /missing/",
            bookmark_resolver=lambda target: None,
        )
        assert "is-callout-bookmark" in result
        assert '<a href="/missing/">' in result
        assert "could not resolve" in capsys.readouterr().err.lower()

    def test_resolver_exception_warns_and_emits_link_card(self, capsys):
        def resolver(target):
            raise RuntimeError("network down")

        result = convert("> [!BOOKMARK]\n> /missing/", bookmark_resolver=resolver)
        assert '<a href="/missing/">' in result
        assert "network down" in capsys.readouterr().err

    def test_absent_resolver_emits_link_card_without_warning(self, capsys):
        result = convert("> [!BOOKMARK]\n> /my-other-post/")
        assert '<a href="/my-other-post/">' in result
        assert capsys.readouterr().err == ""

    def test_resolved_fields_are_escaped(self):
        hostile = dict(FULL_BOOKMARK, title="Five < Six", excerpt="A & B")
        result = convert(
            "> [!BOOKMARK]\n> /x/", bookmark_resolver=lambda target: hostile
        )
        assert "Five &lt; Six" in result
        assert "A &amp; B" in result


class TestBookmarkMalformedResolver:
    """A resolver is arbitrary user-supplied code; it may return anything.

    _render_bookmark's try/except only covers the *call* to the resolver,
    not what's done with a value it successfully returns. A truthy
    non-dict return (or a dict with None where a string is expected) must
    still degrade cleanly rather than crash the whole conversion - the
    same "no callout failure may fail a publish" constraint that governs
    the None/raises/absent paths.
    """

    def test_string_return_warns_and_emits_link_card(self, capsys):
        result = convert(
            "> [!BOOKMARK]\n> /x/", bookmark_resolver=lambda target: "not a dict"
        )
        assert "is-callout-bookmark" in result
        assert '<a href="/x/">' in result
        assert capsys.readouterr().err != ""

    def test_list_return_warns_and_emits_link_card(self, capsys):
        result = convert(
            "> [!BOOKMARK]\n> /x/", bookmark_resolver=lambda target: ["oops"]
        )
        assert "is-callout-bookmark" in result
        assert '<a href="/x/">' in result
        assert capsys.readouterr().err != ""

    def test_none_title_and_link_do_not_render_as_literal_none(self):
        hostile = dict(FULL_BOOKMARK, title=None, link=None)
        result = convert(
            "> [!BOOKMARK]\n> /x/", bookmark_resolver=lambda target: hostile
        )
        assert "None" not in result

    def test_empty_dict_return_renders_without_raising(self):
        result = convert(
            "> [!BOOKMARK]\n> /x/", bookmark_resolver=lambda target: {}
        )
        assert "is-callout-bookmark" in result


class TestBookmarkMalformedImageId:
    """image_id's contract is int | None, but a resolver may return
    anything. A non-int value must not reach json.dumps (a set or other
    arbitrary object raises TypeError there) or get embedded verbatim
    into the wp-image-{id} class (a JSON-safe but wrong-typed value, like
    a string or list, would otherwise render as garbage). Every case
    degrades to "no attachment association" - same as image_id being
    absent - rather than raising or corrupting the markup. No warning is
    expected: a wrong-typed image_id still produces a correct, usable
    card.
    """

    def _render(self, image_id):
        return convert(
            "> [!BOOKMARK]\n> /x/",
            bookmark_resolver=lambda target: dict(FULL_BOOKMARK, image_id=image_id),
        )

    def test_set_does_not_raise_and_omits_media_id(self):
        result = self._render({1, 2, 3})
        assert "wp:media-text" in result
        assert "mediaId" not in result
        assert "wp-image-" not in result

    def test_arbitrary_object_does_not_raise_and_omits_media_id(self):
        result = self._render(object())
        assert "wp:media-text" in result
        assert "mediaId" not in result
        assert "wp-image-" not in result

    def test_string_omits_media_id_and_class(self):
        result = self._render("123")
        assert "mediaId" not in result
        assert "wp-image-" not in result

    def test_float_omits_media_id_and_class(self):
        result = self._render(123.0)
        assert "mediaId" not in result
        assert "wp-image-" not in result

    def test_list_omits_media_id_and_class(self):
        result = self._render([123])
        assert "mediaId" not in result
        assert "wp-image-" not in result

    def test_bool_true_omits_media_id_and_class(self):
        # isinstance(True, int) is True in Python, so bool needs its own
        # exclusion or it would slip past a naive isinstance(x, int) check.
        result = self._render(True)
        assert "mediaId" not in result
        assert "wp-image-" not in result

    def test_genuine_int_still_produces_media_id_and_class(self):
        result = self._render(123)
        assert '"mediaId":123' in result
        assert 'class="wp-image-123 size-full"' in result


class _Boom:
    """A value whose __str__ raises, simulating a hostile resolver field."""

    def __str__(self):
        raise ValueError("str boom")


class _HostileDict(dict):
    """A dict subclass whose .get() raises.

    isinstance(data, dict) does not protect against this - it's a real
    dict by type, it just misbehaves when used.
    """

    def get(self, *args, **kwargs):
        raise RuntimeError("get boom")


class TestBookmarkCardBuildingNet:
    """The specific guards (rounds 1-2) cover the shape of the resolver's
    return value and its image_id. They can't cover every way a field
    might misbehave once consumed - a value whose __str__ raises, or a
    dict subclass whose own .get() raises. Rather than patch each such
    site individually, card-building itself is wrapped in a try/except
    that degrades to the plain link card, the same landing spot every
    other bookmark failure mode already uses.
    """

    def test_title_str_raises_warns_with_exception_text_and_falls_back(self, capsys):
        result = convert(
            "> [!BOOKMARK]\n> /x/",
            bookmark_resolver=lambda target: dict(FULL_BOOKMARK, title=_Boom()),
        )
        assert "is-callout-bookmark" in result
        assert '<a href="/x/">' in result
        assert "str boom" in capsys.readouterr().err

    def test_image_url_str_raises_warns_with_exception_text_and_falls_back(self, capsys):
        result = convert(
            "> [!BOOKMARK]\n> /x/",
            bookmark_resolver=lambda target: dict(FULL_BOOKMARK, image_url=_Boom()),
        )
        assert "is-callout-bookmark" in result
        assert '<a href="/x/">' in result
        assert "str boom" in capsys.readouterr().err

    def test_dict_subclass_with_hostile_get_warns_and_falls_back(self, capsys):
        result = convert(
            "> [!BOOKMARK]\n> /x/",
            bookmark_resolver=lambda target: _HostileDict(FULL_BOOKMARK),
        )
        assert "is-callout-bookmark" in result
        assert '<a href="/x/">' in result
        assert "get boom" in capsys.readouterr().err

    def test_well_formed_dict_still_produces_a_full_card(self):
        # The net must not fire, or degrade output, for the ordinary path.
        result = convert(
            "> [!BOOKMARK]\n> /my-other-post/",
            bookmark_resolver=lambda target: FULL_BOOKMARK,
        )
        assert "wp:media-text" in result
        assert "could not be built" not in result

    def test_non_dict_return_is_still_caught_by_the_round_1_guard(self, capsys):
        # Must warn with the round-1 message, not the net's - it should
        # never reach the try/except this test class is otherwise about.
        result = convert(
            "> [!BOOKMARK]\n> /x/", bookmark_resolver=lambda target: "not a dict"
        )
        err = capsys.readouterr().err.lower()
        assert "expected a dict" in err
        assert "could not be built" not in err

    def test_bad_image_id_is_still_caught_by_the_round_2_guard(self, capsys):
        # Must still produce a media-text card, not degrade to a link
        # card, and must not emit the net's warning.
        result = convert(
            "> [!BOOKMARK]\n> /x/",
            bookmark_resolver=lambda target: dict(FULL_BOOKMARK, image_id={1, 2, 3}),
        )
        assert "wp:media-text" in result
        assert "could not be built" not in capsys.readouterr().err.lower()
