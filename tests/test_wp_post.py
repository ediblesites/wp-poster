"""Tests for wp-post.py — WordPressPost class and standalone functions."""

import base64
import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest
import requests
import yaml

wp_post = sys.modules["wp_post"]
WordPressPost = wp_post.WordPressPost
resolve_format = wp_post.resolve_format
find_network_config = wp_post.find_network_config
find_translation_siblings = wp_post.find_translation_siblings
write_msls_links = wp_post.write_msls_links
init_network_config = wp_post.init_network_config
resolve_site_identity = wp_post.resolve_site_identity
find_site_for_file = wp_post.find_site_for_file
resolve_locale_for_file = wp_post.resolve_locale_for_file
normalize_yaml_dates = wp_post.normalize_yaml_dates


def _msls_eval_echo(returncode=0):
    """Build a subprocess.run side_effect that simulates a wp-cli MSLS eval.

    The real combined eval writes the base64 payload then echoes back the
    stored option via wp_json_encode. This fake decodes that same payload from
    the command and returns it as stdout, so a successful write reads back as
    exactly what was written (read-back verification passes).
    """
    def _run(cmd, *args, **kwargs):
        script = cmd[3]
        m = re.search(r'base64_decode\("([^"]+)"\)', script)
        stdout = base64.b64decode(m.group(1)).decode() if m else ""
        return MagicMock(returncode=returncode, stdout=stdout, stderr="")
    return _run


# ===========================================================================
# 1. Missing title validation  (highest priority)
# ===========================================================================

class TestMissingTitle:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_post_missing_title_returns_none(self, mock_get, mock_post, wp, md_file):
        path = md_file({"status": "draft"}, "body text")
        result = wp.post_to_wordpress(path, raw=True)
        assert result is None
        mock_post.assert_not_called()

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_post_empty_frontmatter_returns_none(self, mock_get, mock_post, wp, md_file):
        path = md_file({}, "body text")
        result = wp.post_to_wordpress(path, raw=True)
        assert result is None
        mock_post.assert_not_called()

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_post_no_frontmatter_returns_none(self, mock_get, mock_post, wp, md_file):
        path = md_file(None, "just body, no frontmatter")
        result = wp.post_to_wordpress(path, raw=True)
        assert result is None
        mock_post.assert_not_called()


# ===========================================================================
# 2. resolve_format (pure function)
# ===========================================================================

class TestResolveFormat:
    def test_cli_raw_wins(self):
        assert resolve_format(True, True, {"format": "markdown"}, {"default_format": "markdown"}) == "raw"

    def test_cli_raw_over_frontmatter(self):
        assert resolve_format(False, True, {"format": "markdown"}, {}) == "raw"

    def test_cli_markdown_over_frontmatter(self):
        assert resolve_format(True, False, {"format": "raw"}, {}) == "markdown"

    def test_frontmatter_raw(self):
        assert resolve_format(False, False, {"format": "raw"}, {}) == "raw"

    def test_frontmatter_markdown(self):
        assert resolve_format(False, False, {"format": "markdown"}, {}) == "markdown"

    def test_config_default_format(self):
        assert resolve_format(False, False, {}, {"default_format": "markdown"}) == "markdown"

    def test_config_raw(self):
        assert resolve_format(False, False, {}, {"default_format": "raw"}) == "raw"

    def test_default_is_raw(self):
        assert resolve_format(False, False, {}, {}) == "raw"


# ===========================================================================
# 3. File parsing
# ===========================================================================

class TestParseFrontmatterOnly:
    def test_with_frontmatter(self, wp, md_file):
        path = md_file({"title": "Hello", "status": "draft"}, "body")
        fm = wp.parse_frontmatter_only(path)
        assert fm["title"] == "Hello"
        assert fm["status"] == "draft"

    def test_without_frontmatter(self, wp, md_file):
        path = md_file(None, "just body")
        assert wp.parse_frontmatter_only(path) == {}

    def test_empty_frontmatter(self, wp, md_file):
        path = md_file({}, "body")
        # yaml.safe_load('') returns None, code coerces to {}
        assert wp.parse_frontmatter_only(path) == {}


class TestNormalizeYamlDates:
    """normalize_yaml_dates coerces datetime.date / datetime.datetime to ISO strings."""

    def test_top_level_date(self):
        import datetime
        out = normalize_yaml_dates({"date": datetime.date(2026, 6, 7)})
        assert out == {"date": "2026-06-07"}

    def test_datetime_keeps_time(self):
        import datetime
        out = normalize_yaml_dates({"date": datetime.datetime(2026, 6, 7, 9, 30, 0)})
        assert out == {"date": "2026-06-07T09:30:00"}

    def test_nested_in_meta(self):
        import datetime
        out = normalize_yaml_dates({"meta": {"pricing_verified": datetime.date(2026, 6, 7)}})
        assert out == {"meta": {"pricing_verified": "2026-06-07"}}

    def test_inside_list(self):
        import datetime
        out = normalize_yaml_dates({"meta": {"checks": [datetime.date(2026, 6, 7), "x"]}})
        assert out == {"meta": {"checks": ["2026-06-07", "x"]}}

    def test_non_dates_unchanged(self):
        out = normalize_yaml_dates({"a": 1, "b": "two", "c": [1, 2], "d": None})
        assert out == {"a": 1, "b": "two", "c": [1, 2], "d": None}

    def test_none_passthrough(self):
        assert normalize_yaml_dates(None) is None


class TestUnquotedDatesAreSerializable:
    """Unquoted YAML dates anywhere in frontmatter survive json.dumps (issue #9)."""

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_unquoted_date_in_meta(self, mock_get, mock_post, wp, tmp_path, mock_response):
        # Write raw frontmatter with an unquoted ISO date in a meta field.
        content = (
            "---\n"
            "title: T\n"
            "date: 2026-06-07\n"
            "meta:\n"
            "  pricing_verified: 2026-06-07\n"
            "---\n"
            "body"
        )
        path = tmp_path / "post.md"
        path.write_text(content, encoding="utf-8")
        mock_post.return_value = mock_response(201, {
            "id": 1, "link": "https://example.com/?p=1",
            "title": {"rendered": "T"},
        })

        wp.post_to_wordpress(str(path), raw=True)
        post_data = mock_post.call_args[1]["json"]

        # The payload must be JSON-serializable (the original crash).
        json.dumps(post_data)
        # The post date gains a time component, which WordPress requires and
        # rejects the bare date without (issue #19). Arbitrary meta dates are
        # left exactly as written - they are the author's data, not a
        # WordPress-validated field.
        assert post_data["date"] == "2026-06-07T00:00:00"
        assert post_data["meta"]["pricing_verified"] == "2026-06-07"


class TestParseRawFile:
    def test_with_frontmatter(self, wp, md_file):
        path = md_file({"title": "T"}, "raw body")
        fm, content = wp.parse_raw_file(path)
        assert fm["title"] == "T"
        assert content == "raw body"

    def test_without_frontmatter(self, wp, md_file):
        path = md_file(None, "just body")
        fm, content = wp.parse_raw_file(path)
        assert fm == {}
        assert content == "just body"


# ===========================================================================
# 4. post_to_wordpress — success / failure paths
# ===========================================================================

def _wp_api_router(post_url, categories=None, tags=None, users=None):
    """Return a side_effect callable that routes based on URL for requests.get."""
    def _router(url, **kwargs):
        resp = MagicMock()
        if "/categories" in url:
            resp.status_code = 200
            resp.json.return_value = categories or []
            return resp
        if "/tags" in url:
            resp.status_code = 200
            resp.json.return_value = tags or []
            return resp
        if "/users" in url:
            resp.status_code = 200
            resp.json.return_value = users or []
            return resp
        resp.status_code = 404
        return resp
    return _router


class TestPostSuccess:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_basic_publish(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "My Post"}, "hello world")
        mock_post.return_value = mock_response(201, {
            "id": 10,
            "link": "https://example.com/?p=10",
            "title": {"rendered": "My Post"},
        })
        result = wp.post_to_wordpress(path, raw=True)
        assert result["success"] is True
        assert result["id"] == 10
        assert result["url"] == "https://example.com/?p=10"
        # Verify correct endpoint
        call_args = mock_post.call_args
        assert "/wp-json/wp/v2/posts" in call_args[0][0]

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_draft_mode(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "Draft"}, "body")
        mock_post.return_value = mock_response(201, {
            "id": 11, "link": "https://example.com/?p=11",
            "title": {"rendered": "Draft"},
        })
        wp.post_to_wordpress(path, draft=True, raw=True)
        post_data = mock_post.call_args[1]["json"]
        assert post_data["status"] == "draft"

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_page_post_type(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "About", "post_type": "page"}, "body")
        mock_post.return_value = mock_response(201, {
            "id": 12, "link": "https://example.com/about",
            "title": {"rendered": "About"},
        })
        wp.post_to_wordpress(path, raw=True)
        assert "/pages" in mock_post.call_args[0][0]

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_custom_post_type(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "Product", "post_type": "products"}, "body")
        mock_post.return_value = mock_response(201, {
            "id": 13, "link": "https://example.com/products/1",
            "title": {"rendered": "Product"},
        })
        wp.post_to_wordpress(path, raw=True)
        assert "/products" in mock_post.call_args[0][0]

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_update_existing_post(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "Updated", "id": 99}, "body")
        mock_post.return_value = mock_response(200, {
            "id": 99, "link": "https://example.com/?p=99",
            "title": {"rendered": "Updated"},
        })
        result = wp.post_to_wordpress(path, raw=True)
        assert result["success"] is True
        assert "/posts/99" in mock_post.call_args[0][0]

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_null_id_takes_create_branch(self, mock_get, mock_post, wp, md_file, mock_response):
        # Bare `id:` in YAML loads as None. Must route to create, not
        # POST /posts/None → 404. Regression for wp-poster issue #15.
        path = md_file({"title": "Fresh", "id": None}, "body")
        mock_post.return_value = mock_response(201, {
            "id": 42, "link": "https://example.com/?p=42",
            "title": {"rendered": "Fresh"},
        })
        result = wp.post_to_wordpress(path, raw=True)
        assert result["success"] is True
        assert result["id"] == 42
        called_url = mock_post.call_args[0][0]
        assert called_url.endswith("/wp-json/wp/v2/posts")
        assert "None" not in called_url


class TestPostCategories:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_existing_categories_resolved(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T", "categories": ["Tech"]}, "body")
        mock_get.side_effect = _wp_api_router(
            "https://example.com",
            categories=[{"name": "Tech", "slug": "tech", "id": 5}],
        )
        mock_post.return_value = mock_response(201, {
            "id": 1, "link": "https://example.com/?p=1",
            "title": {"rendered": "T"},
        })
        wp.post_to_wordpress(path, raw=True)
        post_data = mock_post.call_args[1]["json"]
        assert post_data["categories"] == [5]

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_new_category_created(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T", "categories": ["NewCat"]}, "body")
        mock_get.side_effect = _wp_api_router("https://example.com", categories=[])

        # requests.post is called twice: once to create category, once to create post
        mock_post.side_effect = [
            mock_response(201, {"id": 77}),  # create_category
            mock_response(201, {
                "id": 1, "link": "https://example.com/?p=1",
                "title": {"rendered": "T"},
            }),
        ]
        wp.post_to_wordpress(path, raw=True)
        # The category creation call
        cat_call = mock_post.call_args_list[0]
        assert "/categories" in cat_call[0][0]
        assert cat_call[1]["json"]["name"] == "NewCat"


class TestPostTags:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_existing_tags_resolved(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T", "tags": ["python"]}, "body")
        mock_get.side_effect = _wp_api_router(
            "https://example.com",
            tags=[{"name": "python", "slug": "python", "id": 3}],
        )
        mock_post.return_value = mock_response(201, {
            "id": 1, "link": "https://example.com/?p=1",
            "title": {"rendered": "T"},
        })
        wp.post_to_wordpress(path, raw=True)
        post_data = mock_post.call_args[1]["json"]
        assert post_data["tags"] == [3]

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_new_tag_created(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T", "tags": ["newtag"]}, "body")
        mock_get.side_effect = _wp_api_router("https://example.com", tags=[])
        mock_post.side_effect = [
            mock_response(201, {"id": 88}),  # create_tag
            mock_response(201, {
                "id": 1, "link": "https://example.com/?p=1",
                "title": {"rendered": "T"},
            }),
        ]
        wp.post_to_wordpress(path, raw=True)
        tag_call = mock_post.call_args_list[0]
        assert "/tags" in tag_call[0][0]


class TestPostAuthor:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_author_from_frontmatter(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T", "author": "editor"}, "body")
        mock_get.side_effect = _wp_api_router(
            "https://example.com",
            users=[{"slug": "editor", "name": "Editor", "id": 7}],
        )
        mock_post.return_value = mock_response(201, {
            "id": 1, "link": "https://example.com/?p=1",
            "title": {"rendered": "T"},
        })
        wp.post_to_wordpress(path, raw=True)
        post_data = mock_post.call_args[1]["json"]
        assert post_data["author"] == 7

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_author_from_context(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T"}, "body")
        mock_get.side_effect = _wp_api_router(
            "https://example.com",
            users=[{"slug": "ctx_author", "name": "Ctx", "id": 9}],
        )
        mock_post.return_value = mock_response(201, {
            "id": 1, "link": "https://example.com/?p=1",
            "title": {"rendered": "T"},
        })
        wp.post_to_wordpress(path, raw=True, author_context="ctx_author")
        post_data = mock_post.call_args[1]["json"]
        assert post_data["author"] == 9

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_author_not_found(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T", "author": "ghost"}, "body")
        mock_get.side_effect = _wp_api_router("https://example.com", users=[])
        mock_post.return_value = mock_response(201, {
            "id": 1, "link": "https://example.com/?p=1",
            "title": {"rendered": "T"},
        })
        wp.post_to_wordpress(path, raw=True)
        post_data = mock_post.call_args[1]["json"]
        assert "author" not in post_data


class TestPostMeta:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_meta_fields(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T", "meta": {"key1": "val1"}}, "body")
        mock_post.return_value = mock_response(201, {
            "id": 1, "link": "https://example.com/?p=1",
            "title": {"rendered": "T"},
        })
        wp.post_to_wordpress(path, raw=True)
        post_data = mock_post.call_args[1]["json"]
        assert post_data["meta"] == {"key1": "val1"}

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_acf_fields(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T", "acf": {"field_1": "abc"}}, "body")
        mock_post.return_value = mock_response(201, {
            "id": 1, "link": "https://example.com/?p=1",
            "title": {"rendered": "T"},
        })
        wp.post_to_wordpress(path, raw=True)
        post_data = mock_post.call_args[1]["json"]
        assert post_data["acf"] == {"field_1": "abc"}


class TestPostFeaturedImage:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_featured_image_uploaded(self, mock_get, mock_post, wp, md_file, mock_response, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0fake-jpg-data")
        path = md_file({"title": "T", "featured_image": str(img)}, "body")
        mock_post.side_effect = [
            # upload_media_from_file
            mock_response(201, {"id": 50, "source_url": "https://example.com/photo.jpg"}),
            # create post
            mock_response(201, {
                "id": 1, "link": "https://example.com/?p=1",
                "title": {"rendered": "T"},
            }),
        ]
        wp.post_to_wordpress(path, raw=True)
        post_data = mock_post.call_args[1]["json"]
        assert post_data["featured_media"] == 50

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_featured_image_null_is_ignored(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T", "featured_image": None}, "body")
        mock_post.side_effect = [
            mock_response(201, {
                "id": 1, "link": "https://example.com/?p=1",
                "title": {"rendered": "T"},
            }),
        ]
        result = wp.post_to_wordpress(path, raw=True)
        assert result["success"] is True
        post_data = mock_post.call_args[1]["json"]
        assert "featured_media" not in post_data


class TestPostRankMath:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_rankmath_meta_sent(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({
            "title": "T",
            "rankmath": {"title": "SEO Title", "description": "SEO desc", "focus_keyword": "kw"},
        }, "body")
        mock_post.side_effect = [
            # create post
            mock_response(201, {
                "id": 20, "link": "https://example.com/?p=20",
                "title": {"rendered": "T"},
            }),
            # rankmath update
            mock_response(200),
        ]
        result = wp.post_to_wordpress(path, raw=True)
        assert result["success"] is True
        # Second call should be the rankmath API
        rm_call = mock_post.call_args_list[1]
        assert "rankmath" in rm_call[0][0]
        payload = rm_call[1]["json"]
        assert payload["meta"]["rank_math_title"] == "SEO Title"
        assert payload["meta"]["rank_math_description"] == "SEO desc"
        assert payload["meta"]["rank_math_focus_keyword"] == "kw"


def _rankmath_payload(mock_post):
    """Return the JSON payload of the Rank Math updateMeta call, or None."""
    for c in mock_post.call_args_list:
        if c[0] and "rankmath" in c[0][0]:
            return c[1]["json"]
    return None


class TestExcerptRankMathReconcile:
    """Issue #13: an excerpt change must not leave rank_math_description stale.

    When no explicit rankmath.description is given, a non-empty excerpt is
    pushed as rank_math_description so the live meta description tracks local
    state; an explicit rankmath.description always wins; an empty/absent excerpt
    leaves the override untouched.
    """

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_excerpt_only_pushes_rank_math_description(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T", "excerpt": "New excerpt text"}, "body")
        mock_post.side_effect = [
            mock_response(201, {"id": 5, "link": "https://example.com/?p=5", "title": {"rendered": "T"}}),
            mock_response(200),  # rankmath updateMeta
        ]
        wp.post_to_wordpress(path, raw=True)
        rm = _rankmath_payload(mock_post)
        assert rm is not None
        assert rm["meta"]["rank_math_description"] == "New excerpt text"

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_explicit_rankmath_description_wins(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({
            "title": "T",
            "excerpt": "Excerpt text",
            "rankmath": {"description": "Explicit SEO desc"},
        }, "body")
        mock_post.side_effect = [
            mock_response(201, {"id": 6, "link": "https://example.com/?p=6", "title": {"rendered": "T"}}),
            mock_response(200),
        ]
        wp.post_to_wordpress(path, raw=True)
        rm = _rankmath_payload(mock_post)
        assert rm["meta"]["rank_math_description"] == "Explicit SEO desc"

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_excerpt_injected_without_disturbing_other_rankmath_keys(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({
            "title": "T",
            "excerpt": "Excerpt text",
            "rankmath": {"title": "SEO Title"},
        }, "body")
        mock_post.side_effect = [
            mock_response(201, {"id": 7, "link": "https://example.com/?p=7", "title": {"rendered": "T"}}),
            mock_response(200),
        ]
        wp.post_to_wordpress(path, raw=True)
        rm = _rankmath_payload(mock_post)
        assert rm["meta"]["rank_math_title"] == "SEO Title"
        assert rm["meta"]["rank_math_description"] == "Excerpt text"

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_no_excerpt_no_rankmath_makes_no_updatemeta_call(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T"}, "body")
        # Only the create-post call is allowed; a rankmath call would exhaust this.
        mock_post.side_effect = [
            mock_response(201, {"id": 8, "link": "https://example.com/?p=8", "title": {"rendered": "T"}}),
        ]
        wp.post_to_wordpress(path, raw=True)
        assert _rankmath_payload(mock_post) is None

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_empty_excerpt_leaves_description_untouched(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T", "excerpt": "   "}, "body")
        mock_post.side_effect = [
            mock_response(201, {"id": 9, "link": "https://example.com/?p=9", "title": {"rendered": "T"}}),
        ]
        wp.post_to_wordpress(path, raw=True)
        assert _rankmath_payload(mock_post) is None


class TestPostFailure:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_error_response(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T"}, "body")
        mock_post.return_value = mock_response(403, text="Forbidden")
        result = wp.post_to_wordpress(path, raw=True)
        assert result["success"] is False
        assert result["status_code"] == 403


class TestPostCustomTaxonomies:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_custom_taxonomy_resolved(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "T", "taxonomies": {"genre": ["fiction"]}}, "body")

        def get_router(url, **kwargs):
            resp = MagicMock()
            if "/taxonomies/genre" in url:
                resp.status_code = 200
                resp.json.return_value = {"rest_base": "genre"}
                return resp
            if "/genre" in url:
                resp.status_code = 200
                resp.json.return_value = [{"name": "fiction", "slug": "fiction", "id": 33}]
                return resp
            resp.status_code = 404
            return resp

        mock_get.side_effect = get_router
        mock_post.return_value = mock_response(201, {
            "id": 1, "link": "https://example.com/?p=1",
            "title": {"rendered": "T"},
        })
        wp.post_to_wordpress(path, raw=True)
        post_data = mock_post.call_args[1]["json"]
        assert post_data["genre"] == [33]


# ===========================================================================
# 5. Helper methods
# ===========================================================================

class TestGetUserId:
    def test_int_passthrough(self, wp):
        assert wp.get_user_id(42) == 42

    def test_numeric_string(self, wp):
        assert wp.get_user_id("7") == 7

    @patch("wp_post.requests.get")
    def test_username_lookup(self, mock_get, wp, mock_response):
        mock_get.return_value = mock_response(200, [
            {"slug": "admin", "name": "Admin", "id": 1}
        ])
        assert wp.get_user_id("admin") == 1

    @patch("wp_post.requests.get")
    def test_username_not_found(self, mock_get, wp, mock_response):
        mock_get.return_value = mock_response(200, [])
        assert wp.get_user_id("nobody") is None


class TestGetCategories:
    @patch("wp_post.requests.get")
    def test_success(self, mock_get, wp, mock_response):
        mock_get.return_value = mock_response(200, [
            {"name": "Tech", "slug": "tech", "id": 1},
            {"name": "News", "slug": "news", "id": 2},
        ])
        cats = wp.get_categories()
        assert cats["Tech"] == 1
        assert cats["tech"] == 1
        assert cats["News"] == 2

    @patch("wp_post.requests.get")
    def test_failure(self, mock_get, wp, mock_response):
        mock_get.return_value = mock_response(500)
        assert wp.get_categories() == {}


class TestGetTags:
    @patch("wp_post.requests.get")
    def test_success(self, mock_get, wp, mock_response):
        mock_get.return_value = mock_response(200, [
            {"name": "python", "slug": "python", "id": 10},
        ])
        tags = wp.get_tags()
        assert tags["python"] == 10
        assert tags["python"] == 10

    @patch("wp_post.requests.get")
    def test_failure(self, mock_get, wp, mock_response):
        mock_get.return_value = mock_response(500)
        assert wp.get_tags() == {}


class TestCreateCategory:
    @patch("wp_post.requests.post")
    def test_success(self, mock_post, wp, mock_response):
        mock_post.return_value = mock_response(201, {"id": 55})
        assert wp.create_category("NewCat") == 55

    @patch("wp_post.requests.post")
    def test_failure(self, mock_post, wp, mock_response):
        mock_post.return_value = mock_response(400)
        assert wp.create_category("Bad") is None


class TestCreateTag:
    @patch("wp_post.requests.post")
    def test_success(self, mock_post, wp, mock_response):
        mock_post.return_value = mock_response(201, {"id": 66})
        assert wp.create_tag("newtag") == 66

    @patch("wp_post.requests.post")
    def test_failure(self, mock_post, wp, mock_response):
        mock_post.return_value = mock_response(400)
        assert wp.create_tag("bad") is None


class TestUpdateRankmathMeta:
    @patch("wp_post.requests.post")
    def test_key_mapping(self, mock_post, wp, mock_response):
        mock_post.return_value = mock_response(200)
        wp.update_rankmath_meta(1, {
            "title": "SEO Title",
            "description": "SEO Desc",
            "focus_keyword": "kw",
        })
        payload = mock_post.call_args[1]["json"]
        assert payload["meta"]["rank_math_title"] == "SEO Title"
        assert payload["meta"]["rank_math_description"] == "SEO Desc"
        assert payload["meta"]["rank_math_focus_keyword"] == "kw"
        assert payload["objectID"] == 1

    @patch("wp_post.requests.post")
    def test_full_key_passthrough(self, mock_post, wp, mock_response):
        mock_post.return_value = mock_response(200)
        wp.update_rankmath_meta(1, {"rank_math_robots": "noindex"})
        payload = mock_post.call_args[1]["json"]
        assert payload["meta"]["rank_math_robots"] == "noindex"

    @patch("wp_post.requests.post")
    def test_empty_dict_no_request(self, mock_post, wp):
        wp.update_rankmath_meta(1, {})
        mock_post.assert_not_called()


# ===========================================================================
# 6. Writeback frontmatter (id/slug after create)
# ===========================================================================

class TestWritebackFrontmatter:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_writes_id_and_slug_on_create(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "New Post", "slug": "new-post"}, "body text")
        mock_post.return_value = mock_response(201, {
            "id": 42, "link": "https://example.com/new-post/",
            "title": {"rendered": "New Post"},
        })
        result = wp.post_to_wordpress(path, raw=True)
        assert result["success"] is True

        # Re-read the file and check frontmatter
        fm = wp.parse_frontmatter_only(path)
        assert fm["id"] == 42
        assert fm["slug"] == "new-post"
        assert fm["title"] == "New Post"

        # Body preserved
        with open(path, 'r') as f:
            content = f.read()
        assert "body text" in content

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_no_writeback_on_update(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "Existing", "id": 99, "slug": "existing"}, "body")
        mock_post.return_value = mock_response(200, {
            "id": 99, "link": "https://example.com/existing/",
            "title": {"rendered": "Existing"},
        })
        # Read original content
        with open(path, 'r') as f:
            original = f.read()

        wp.post_to_wordpress(path, raw=True)

        # File should be unchanged
        with open(path, 'r') as f:
            assert f.read() == original

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_slug_updated_on_conflict(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file({"title": "My Post", "slug": "my-post"}, "body")
        mock_post.return_value = mock_response(201, {
            "id": 55, "link": "https://example.com/my-post-2/",
            "title": {"rendered": "My Post"},
        })
        wp.post_to_wordpress(path, raw=True)

        fm = wp.parse_frontmatter_only(path)
        assert fm["id"] == 55
        assert fm["slug"] == "my-post-2"


# ===========================================================================
# 7. Network / MSLS translation support
# ===========================================================================

def _scaffold_network(tmp_path, sites, translation_sets=None):
    """Helper to create a network project structure for testing.

    sites: list of dicts with keys: key, site_url, locale, blog_id
    translation_sets: list of dicts with keys: site_key, filename, frontmatter
    """
    # Root config
    network_sites = {}
    for site in sites:
        site_dir = tmp_path / site['key']
        content_dir = site_dir / 'content'
        content_dir.mkdir(parents=True, exist_ok=True)

        # Per-site config
        site_config = {
            'site_url': site['site_url'],
            'username': 'admin',
            'app_password': 'pass',
            'locale': site['locale'],
            'blog_id': site['blog_id'],
        }
        with open(site_dir / '.wp-poster.json', 'w') as f:
            json.dump(site_config, f)

        network_sites[site['key']] = {
            'content_path': f"{site['key']}/content/",
        }

    root_config = {
        'network': {
            'wp_cli_alias': '@testsite',
            'sites': network_sites,
        }
    }
    with open(tmp_path / '.wp-poster.json', 'w') as f:
        json.dump(root_config, f)

    # Create translation set files
    if translation_sets:
        for ts in translation_sets:
            content_dir = tmp_path / ts['site_key'] / 'content'
            filepath = content_dir / ts.get('filename', 'index.md')
            filepath.parent.mkdir(parents=True, exist_ok=True)
            parts = ['---', yaml.dump(ts['frontmatter'], default_flow_style=False).rstrip(), '---', 'Content']
            filepath.write_text('\n'.join(parts), encoding='utf-8')

    return tmp_path


def _scaffold_network_map(tmp_path, sites, translation_sets=None):
    """Network project where site identity (site_url/locale/blog_id) lives in
    the network.sites map and there are NO per-site .wp-poster.json files.
    Shared credentials live at the root. Mirrors the consolidated single-config
    layout (ediblesites/wp-poster#6).
    """
    network_sites = {}
    for site in sites:
        content_dir = tmp_path / site['key'] / 'content'
        content_dir.mkdir(parents=True, exist_ok=True)
        network_sites[site['key']] = {
            'content_path': f"{site['key']}/content/",
            'site_url': site['site_url'],
            'locale': site['locale'],
            'blog_id': site['blog_id'],
        }

    root_config = {
        'username': 'claude',
        'app_password': 'pass',
        'network': {
            'wp_cli_alias': '@testsite',
            'sites': network_sites,
        },
    }
    with open(tmp_path / '.wp-poster.json', 'w') as f:
        json.dump(root_config, f)

    if translation_sets:
        for ts in translation_sets:
            content_dir = tmp_path / ts['site_key'] / 'content'
            filepath = content_dir / ts.get('filename', 'index.md')
            filepath.parent.mkdir(parents=True, exist_ok=True)
            parts = ['---', yaml.dump(ts['frontmatter'], default_flow_style=False).rstrip(), '---', 'Content']
            filepath.write_text('\n'.join(parts), encoding='utf-8')

    return tmp_path


class TestResolveSiteIdentity:
    def test_reads_identity_from_map(self, tmp_path):
        sites = [{'key': 'es', 'site_url': 'https://example.com/es', 'locale': 'es_ES', 'blog_id': 2}]
        root = _scaffold_network_map(tmp_path, sites)
        with open(root / '.wp-poster.json') as f:
            net = json.load(f)
        site_info = net['network']['sites']['es']

        ident = resolve_site_identity(str(root), 'es', site_info)
        assert ident == {'site_url': 'https://example.com/es', 'locale': 'es_ES', 'blog_id': 2}

    def test_falls_back_to_per_site_file(self, tmp_path):
        # Old layout: map carries only content_path; identity in per-site file.
        sites = [{'key': 'es', 'site_url': 'https://example.com/es', 'locale': 'es_ES', 'blog_id': 2}]
        root = _scaffold_network(tmp_path, sites)
        with open(root / '.wp-poster.json') as f:
            net = json.load(f)
        site_info = net['network']['sites']['es']  # only content_path

        ident = resolve_site_identity(str(root), 'es', site_info)
        assert ident['site_url'] == 'https://example.com/es'
        assert ident['locale'] == 'es_ES'
        assert ident['blog_id'] == 2

    def test_map_partial_filled_from_file(self, tmp_path):
        # Map supplies site_url+locale; blog_id only in the per-site file.
        sites = [{'key': 'es', 'site_url': 'https://file/es', 'locale': 'es_ES', 'blog_id': 2}]
        root = _scaffold_network(tmp_path, sites)
        cfg_path = root / '.wp-poster.json'
        net = json.loads(cfg_path.read_text())
        net['network']['sites']['es'].update({'site_url': 'https://map/es', 'locale': 'es_ES'})
        cfg_path.write_text(json.dumps(net))
        site_info = net['network']['sites']['es']

        ident = resolve_site_identity(str(root), 'es', site_info)
        assert ident['site_url'] == 'https://map/es'  # map wins
        assert ident['blog_id'] == 2                   # filled from file


class TestFindSiteForFile:
    def test_matches_site_by_path(self, tmp_path):
        sites = [
            {'key': 'en', 'site_url': 'https://e', 'locale': 'en_US', 'blog_id': 1},
            {'key': 'es', 'site_url': 'https://e/es', 'locale': 'es_ES', 'blog_id': 2},
        ]
        root = _scaffold_network_map(tmp_path, sites)
        with open(root / '.wp-poster.json') as f:
            net = json.load(f)
        target = tmp_path / 'es' / 'content' / 'privacy' / 'index.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('x')

        key, info = find_site_for_file(str(root), net, str(target))
        assert key == 'es'
        assert info['blog_id'] == 2

    def test_returns_none_outside_any_site(self, tmp_path):
        sites = [{'key': 'en', 'site_url': 'https://e', 'locale': 'en_US', 'blog_id': 1}]
        root = _scaffold_network_map(tmp_path, sites)
        with open(root / '.wp-poster.json') as f:
            net = json.load(f)
        outside = tmp_path / 'other' / 'x.md'
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text('x')

        key, info = find_site_for_file(str(root), net, str(outside))
        assert key is None
        assert info is None


class TestFindTranslationSiblingsMapMode:
    def test_finds_siblings_from_map_without_per_site_files(self, tmp_path):
        sites = [
            {'key': 'en', 'site_url': 'https://e', 'locale': 'en_US', 'blog_id': 1},
            {'key': 'es', 'site_url': 'https://e/es', 'locale': 'es_ES', 'blog_id': 2},
        ]
        ts = [{'site_key': 'es', 'frontmatter': {'title': 'Acerca', 'id': 266, 'translation_set': 'about'}}]
        root = _scaffold_network_map(tmp_path, sites, ts)
        assert not (tmp_path / 'es' / '.wp-poster.json').exists()  # no per-site config
        with open(root / '.wp-poster.json') as f:
            net = json.load(f)

        siblings = find_translation_siblings(str(root), net, 'about', 'en_US')
        assert len(siblings) == 1
        assert siblings[0]['locale'] == 'es_ES'
        assert siblings[0]['blog_id'] == 2
        assert siblings[0]['post_id'] == 266


class TestFindNetworkConfig:
    def test_finds_network_config_above_file(self, tmp_path):
        sites = [{'key': 'en', 'site_url': 'https://example.com', 'locale': 'en_US', 'blog_id': 1}]
        root = _scaffold_network(tmp_path, sites)
        test_file = root / 'en' / 'content' / 'test.md'
        test_file.write_text('---\ntitle: T\n---\nbody')

        project_root, config = find_network_config(str(test_file))
        assert project_root == str(root)
        assert 'network' in config
        assert config['network']['wp_cli_alias'] == '@testsite'

    def test_returns_none_when_no_network_config(self, tmp_path):
        test_file = tmp_path / 'orphan.md'
        test_file.write_text('---\ntitle: T\n---\nbody')

        project_root, config = find_network_config(str(test_file))
        assert project_root is None
        assert config is None

    def test_skips_config_without_network_key(self, tmp_path):
        # Write a .wp-poster.json without 'network' key
        config_path = tmp_path / '.wp-poster.json'
        with open(config_path, 'w') as f:
            json.dump({'site_url': 'https://example.com'}, f)

        test_file = tmp_path / 'test.md'
        test_file.write_text('---\ntitle: T\n---\nbody')

        project_root, config = find_network_config(str(test_file))
        assert project_root is None
        assert config is None


class TestFindTranslationSiblings:
    def test_finds_siblings_with_matching_set_and_id(self, tmp_path):
        sites = [
            {'key': 'en', 'site_url': 'https://en.example.com', 'locale': 'en_US', 'blog_id': 1},
            {'key': 'es', 'site_url': 'https://es.example.com', 'locale': 'es_ES', 'blog_id': 2},
        ]
        ts = [
            {'site_key': 'es', 'frontmatter': {'title': 'Sobre', 'id': 100, 'translation_set': 'about'}},
        ]
        root = _scaffold_network(tmp_path, sites, ts)
        with open(root / '.wp-poster.json') as f:
            network_config = json.load(f)

        siblings = find_translation_siblings(str(root), network_config, 'about', 'en_US')
        assert len(siblings) == 1
        assert siblings[0]['locale'] == 'es_ES'
        assert siblings[0]['blog_id'] == 2
        assert siblings[0]['post_id'] == 100

    def test_excludes_siblings_without_id(self, tmp_path):
        sites = [
            {'key': 'en', 'site_url': 'https://en.example.com', 'locale': 'en_US', 'blog_id': 1},
            {'key': 'es', 'site_url': 'https://es.example.com', 'locale': 'es_ES', 'blog_id': 2},
        ]
        ts = [
            {'site_key': 'es', 'frontmatter': {'title': 'Sobre', 'translation_set': 'about'}},  # no id
        ]
        root = _scaffold_network(tmp_path, sites, ts)
        with open(root / '.wp-poster.json') as f:
            network_config = json.load(f)

        siblings = find_translation_siblings(str(root), network_config, 'about', 'en_US')
        assert len(siblings) == 0

    def test_excludes_current_locale(self, tmp_path):
        sites = [
            {'key': 'en', 'site_url': 'https://en.example.com', 'locale': 'en_US', 'blog_id': 1},
            {'key': 'es', 'site_url': 'https://es.example.com', 'locale': 'es_ES', 'blog_id': 2},
        ]
        ts = [
            {'site_key': 'en', 'frontmatter': {'title': 'About', 'id': 50, 'translation_set': 'about'}},
            {'site_key': 'es', 'frontmatter': {'title': 'Sobre', 'id': 100, 'translation_set': 'about'}},
        ]
        root = _scaffold_network(tmp_path, sites, ts)
        with open(root / '.wp-poster.json') as f:
            network_config = json.load(f)

        # Exclude en_US — should only find es_ES
        siblings = find_translation_siblings(str(root), network_config, 'about', 'en_US')
        assert len(siblings) == 1
        assert siblings[0]['locale'] == 'es_ES'

    def test_returns_empty_when_no_siblings(self, tmp_path):
        sites = [
            {'key': 'en', 'site_url': 'https://en.example.com', 'locale': 'en_US', 'blog_id': 1},
            {'key': 'es', 'site_url': 'https://es.example.com', 'locale': 'es_ES', 'blog_id': 2},
        ]
        root = _scaffold_network(tmp_path, sites)
        with open(root / '.wp-poster.json') as f:
            network_config = json.load(f)

        siblings = find_translation_siblings(str(root), network_config, 'about', 'en_US')
        assert len(siblings) == 0

    def test_ignores_different_translation_set(self, tmp_path):
        sites = [
            {'key': 'en', 'site_url': 'https://en.example.com', 'locale': 'en_US', 'blog_id': 1},
            {'key': 'es', 'site_url': 'https://es.example.com', 'locale': 'es_ES', 'blog_id': 2},
        ]
        ts = [
            {'site_key': 'es', 'frontmatter': {'title': 'Contact', 'id': 200, 'translation_set': 'contact'}},
        ]
        root = _scaffold_network(tmp_path, sites, ts)
        with open(root / '.wp-poster.json') as f:
            network_config = json.load(f)

        siblings = find_translation_siblings(str(root), network_config, 'about', 'en_US')
        assert len(siblings) == 0


def _decode_msls_payload(script):
    """Decode the base64 option payload out of an MSLS eval command string."""
    b64 = re.search(r'base64_decode\("([^"]+)"\)', script).group(1)
    return json.loads(base64.b64decode(b64).decode())


class TestWriteMslsLinks:
    @patch("wp_post.subprocess.run")
    def test_two_member_set(self, mock_run):
        mock_run.side_effect = _msls_eval_echo()
        current = {'locale': 'en_US', 'blog_id': 1, 'post_id': 10}
        siblings = [{'locale': 'es_ES', 'blog_id': 2, 'post_id': 20}]

        write_msls_links('@test', current, siblings)

        assert mock_run.call_count == 2
        # Check that both members get an option written (payload is base64-encoded)
        calls = mock_run.call_args_list
        cmd0 = calls[0][0][0][3]  # first call's eval script
        cmd1 = calls[1][0][0][3]

        # en member should get es sibling
        assert 'msls_10' in cmd0
        assert _decode_msls_payload(cmd0) == {'es_ES': 20}
        # es member should get en sibling
        assert 'msls_20' in cmd1
        assert _decode_msls_payload(cmd1) == {'en_US': 10}

    @patch("wp_post.subprocess.run")
    def test_three_member_set(self, mock_run):
        mock_run.side_effect = _msls_eval_echo()
        current = {'locale': 'en_US', 'blog_id': 1, 'post_id': 10}
        siblings = [
            {'locale': 'es_ES', 'blog_id': 2, 'post_id': 20},
            {'locale': 'de_DE', 'blog_id': 3, 'post_id': 30},
        ]

        write_msls_links('@test', current, siblings)

        assert mock_run.call_count == 3
        # Each member should list the other two
        for i, member in enumerate([current] + siblings):
            cmd = mock_run.call_args_list[i][0][0][3]
            assert f'msls_{member["post_id"]}' in cmd

    @patch("wp_post.subprocess.run")
    def test_mesh_includes_all_members(self, mock_run):
        mock_run.side_effect = _msls_eval_echo()
        current = {'locale': 'en_US', 'blog_id': 1, 'post_id': 10}
        siblings = [{'locale': 'es_ES', 'blog_id': 2, 'post_id': 20}]

        write_msls_links('@test', current, siblings)

        # Verify the wp eval commands use correct blog switching
        calls = mock_run.call_args_list
        assert 'switch_to_blog(1)' in calls[0][0][0][3]
        assert 'switch_to_blog(2)' in calls[1][0][0][3]


class TestMslsIntegration:
    @patch("wp_post.subprocess.run")
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_msls_linking_on_create_with_translation_set(self, mock_get, mock_post, mock_subproc, tmp_path, mock_response):
        sites = [
            {'key': 'en', 'site_url': 'https://en.example.com', 'locale': 'en_US', 'blog_id': 1},
            {'key': 'es', 'site_url': 'https://es.example.com', 'locale': 'es_ES', 'blog_id': 2},
        ]
        ts = [
            {'site_key': 'es', 'frontmatter': {'title': 'Sobre', 'id': 100, 'translation_set': 'about'}},
        ]
        root = _scaffold_network(tmp_path, sites, ts)

        # Create the new post file (no id = new post)
        new_post = root / 'en' / 'content' / 'index.md'
        new_post.write_text('---\ntitle: About\ntranslation_set: about\n---\nContent', encoding='utf-8')

        wp = WordPressPost('https://en.example.com', 'admin', 'pass')
        mock_subproc.side_effect = _msls_eval_echo()
        mock_post.return_value = mock_response(201, {
            'id': 50, 'link': 'https://en.example.com/about/', 'title': {'rendered': 'About'},
        })

        result = wp.post_to_wordpress(str(new_post), raw=True)
        assert result['success'] is True

        # subprocess.run should have been called for MSLS linking
        assert mock_subproc.call_count == 2

    @patch("wp_post.subprocess.run")
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_msls_linking_reasserts_on_update(self, mock_get, mock_post, mock_subproc, tmp_path, mock_response):
        """MSLS links are re-asserted on update too (issue #12), so a failed or
        drifted link write self-heals on the next publish - no manual fix."""
        sites = [
            {'key': 'en', 'site_url': 'https://en.example.com', 'locale': 'en_US', 'blog_id': 1},
            {'key': 'es', 'site_url': 'https://es.example.com', 'locale': 'es_ES', 'blog_id': 2},
        ]
        ts = [
            {'site_key': 'es', 'frontmatter': {'title': 'Sobre', 'id': 100, 'translation_set': 'about'}},
        ]
        root = _scaffold_network(tmp_path, sites, ts)

        # Post with id = update
        update_post = root / 'en' / 'content' / 'index.md'
        update_post.write_text('---\ntitle: About\nid: 50\ntranslation_set: about\n---\nContent', encoding='utf-8')

        wp = WordPressPost('https://en.example.com', 'admin', 'pass')
        mock_subproc.side_effect = _msls_eval_echo()
        mock_post.return_value = mock_response(200, {
            'id': 50, 'link': 'https://en.example.com/about/', 'title': {'rendered': 'About'},
        })

        result = wp.post_to_wordpress(str(update_post), raw=True)

        assert result['success'] is True
        # Linking ran on update (2 members), not skipped
        assert mock_subproc.call_count == 2

    @patch("wp_post.subprocess.run")
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_no_msls_linking_without_translation_set(self, mock_get, mock_post, mock_subproc, tmp_path, mock_response):
        sites = [
            {'key': 'en', 'site_url': 'https://en.example.com', 'locale': 'en_US', 'blog_id': 1},
        ]
        root = _scaffold_network(tmp_path, sites)

        new_post = root / 'en' / 'content' / 'index.md'
        new_post.write_text('---\ntitle: About\n---\nContent', encoding='utf-8')

        wp = WordPressPost('https://en.example.com', 'admin', 'pass')
        mock_post.return_value = mock_response(201, {
            'id': 50, 'link': 'https://en.example.com/about/', 'title': {'rendered': 'About'},
        })

        wp.post_to_wordpress(str(new_post), raw=True)
        mock_subproc.assert_not_called()

    @patch("wp_post.subprocess.run")
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_no_msls_linking_when_no_network_config(self, mock_get, mock_post, mock_subproc, tmp_path, mock_response):
        # Just a standalone file, no network config
        post_file = tmp_path / 'test.md'
        post_file.write_text('---\ntitle: About\ntranslation_set: about\n---\nContent', encoding='utf-8')

        wp = WordPressPost('https://example.com', 'admin', 'pass')
        mock_post.return_value = mock_response(201, {
            'id': 50, 'link': 'https://example.com/about/', 'title': {'rendered': 'About'},
        })

        wp.post_to_wordpress(str(post_file), raw=True)
        mock_subproc.assert_not_called()

    @patch("wp_post.subprocess.run")
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_no_msls_linking_when_no_siblings_have_ids(self, mock_get, mock_post, mock_subproc, tmp_path, mock_response):
        sites = [
            {'key': 'en', 'site_url': 'https://en.example.com', 'locale': 'en_US', 'blog_id': 1},
            {'key': 'es', 'site_url': 'https://es.example.com', 'locale': 'es_ES', 'blog_id': 2},
        ]
        ts = [
            # Sibling exists but has no id (unpublished)
            {'site_key': 'es', 'frontmatter': {'title': 'Sobre', 'translation_set': 'about'}},
        ]
        root = _scaffold_network(tmp_path, sites, ts)

        new_post = root / 'en' / 'content' / 'index.md'
        new_post.write_text('---\ntitle: About\ntranslation_set: about\n---\nContent', encoding='utf-8')

        wp = WordPressPost('https://en.example.com', 'admin', 'pass')
        mock_post.return_value = mock_response(201, {
            'id': 50, 'link': 'https://en.example.com/about/', 'title': {'rendered': 'About'},
        })

        wp.post_to_wordpress(str(new_post), raw=True)
        mock_subproc.assert_not_called()


class TestInitNetworkConfig:
    @patch("wp_post.requests.get")
    @patch("wp_post.subprocess.run")
    @patch("wp_post.getpass.getpass")
    @patch("wp_post.input")
    def test_scaffolds_correct_structure(self, mock_input, mock_getpass, mock_subproc, mock_get, tmp_path, mock_response):
        mock_input.side_effect = [
            '@testsite',    # WP-CLI alias
            'admin',        # username
            'en',           # en subdirectory
            'es',           # es subdirectory
        ]
        mock_getpass.return_value = 'test-pass'

        # wp site list
        site_list_result = MagicMock()
        site_list_result.returncode = 0
        site_list_result.stdout = json.dumps([
            {'blog_id': '1', 'url': 'https://en.example.com'},
            {'blog_id': '2', 'url': 'https://es.example.com'},
        ])

        # wp eval for locales
        locale_en = MagicMock()
        locale_en.returncode = 0
        locale_en.stdout = 'en_US'
        locale_es = MagicMock()
        locale_es.returncode = 0
        locale_es.stdout = 'es_ES'

        mock_subproc.side_effect = [site_list_result, locale_en, locale_es]

        # Connection test
        mock_get.return_value = mock_response(200, {'name': 'Admin'})

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = init_network_config()
        finally:
            os.chdir(original_cwd)

        assert result is True

        # Single consolidated root config: shared creds + full site identity map
        with open(tmp_path / '.wp-poster.json') as f:
            root_config = json.load(f)
        assert root_config['username'] == 'admin'
        assert root_config['app_password'] == 'test-pass'
        assert root_config['network']['wp_cli_alias'] == '@testsite'

        en_site = root_config['network']['sites']['en']
        assert en_site['content_path'] == 'en/content/'
        assert en_site['site_url'] == 'https://en.example.com'
        assert en_site['locale'] == 'en_US'
        assert en_site['blog_id'] == 1

        es_site = root_config['network']['sites']['es']
        assert es_site['locale'] == 'es_ES'
        assert es_site['blog_id'] == 2

        # No per-site config files are written in the consolidated layout
        assert not (tmp_path / 'en' / '.wp-poster.json').exists()
        assert not (tmp_path / 'es' / '.wp-poster.json').exists()

        # Content directories exist
        assert (tmp_path / 'en' / 'content').is_dir()
        assert (tmp_path / 'es' / 'content').is_dir()

    @patch("wp_post.requests.get")
    @patch("wp_post.subprocess.run")
    @patch("wp_post.getpass.getpass")
    @patch("wp_post.input")
    def test_does_not_overwrite_existing_site_config(self, mock_input, mock_getpass, mock_subproc, mock_get, tmp_path, mock_response):
        # Pre-create en directory with existing config
        en_dir = tmp_path / 'en'
        en_dir.mkdir()
        existing_config = {'site_url': 'https://original.com', 'custom': 'value'}
        with open(en_dir / '.wp-poster.json', 'w') as f:
            json.dump(existing_config, f)

        mock_input.side_effect = ['@testsite', 'admin', 'en']
        mock_getpass.return_value = 'test-pass'

        site_list_result = MagicMock()
        site_list_result.returncode = 0
        site_list_result.stdout = json.dumps([
            {'blog_id': '1', 'url': 'https://en.example.com'},
        ])
        locale_en = MagicMock()
        locale_en.returncode = 0
        locale_en.stdout = 'en_US'
        mock_subproc.side_effect = [site_list_result, locale_en]
        mock_get.return_value = mock_response(200, {'name': 'Admin'})

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            init_network_config()
        finally:
            os.chdir(original_cwd)

        # Existing config should be preserved
        with open(en_dir / '.wp-poster.json') as f:
            config = json.load(f)
        assert config['site_url'] == 'https://original.com'
        assert config['custom'] == 'value'


# ===========================================================================
# Image dedup against the WordPress media library (article-scoped)
# ===========================================================================
#
# Dedup is gated on the per-publish article scope set by post_to_wordpress.
# The scope (derived from the markdown file's parent directory) prefixes the
# WP target filename so each article's images live in their own slug namespace.
# Without a scope (direct upload_media calls outside of a publish), dedup is
# intentionally a pass-through: filename-only dedup is unsafe across articles
# because basenames like hero.webp / body-1.webp commonly collide. See
# ediblesites/wp-poster#5 for the regression that motivates this design.

class TestImageDedup:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_scoped_dedup_hit_skips_upload(self, mock_get, mock_post, wp, mock_response, tmp_path):
        """When the media library already has a matching scoped attachment, reuse it and skip POST."""
        wp._current_article_scope = "my-article"
        img = tmp_path / "hero.webp"
        img.write_bytes(b"webp-bytes")
        mock_get.return_value = mock_response(200, [
            {"id": 42, "slug": "my-article-hero",
             "source_url": "https://example.com/wp-content/uploads/2026/04/my-article-hero.webp"},
        ])

        media_id = wp.upload_media(str(img))

        assert media_id == 42
        mock_post.assert_not_called()
        get_call = mock_get.call_args
        assert "/wp-json/wp/v2/media" in get_call[0][0]
        assert get_call[1]["params"]["slug"] == "my-article-hero"

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_scoped_dedup_miss_proceeds_with_upload(self, mock_get, mock_post, wp, mock_response, tmp_path):
        """Empty slug query should fall through and POST a new attachment with the scoped filename."""
        wp._current_article_scope = "my-article"
        img = tmp_path / "fresh.webp"
        img.write_bytes(b"fresh-bytes")
        mock_get.return_value = mock_response(200, [])
        mock_post.return_value = mock_response(201, {
            "id": 99,
            "source_url": "https://example.com/wp-content/uploads/2026/04/my-article-fresh.webp",
        })

        media_id = wp.upload_media(str(img))

        assert media_id == 99
        mock_post.assert_called_once()
        # Content-Disposition must use the scoped filename (so WP stores it scoped)
        cd_header = mock_post.call_args[1]["headers"]["Content-Disposition"]
        assert 'filename="my-article-fresh.webp"' in cd_header

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_scoped_dedup_filename_mismatch_proceeds_with_upload(
        self, mock_get, mock_post, wp, mock_response, tmp_path
    ):
        """Scoped slug match with a different file extension must NOT be treated as a hit."""
        wp._current_article_scope = "my-article"
        img = tmp_path / "shared.jpg"
        img.write_bytes(b"jpeg")
        mock_get.return_value = mock_response(200, [
            {"id": 7, "slug": "my-article-shared",
             "source_url": "https://example.com/wp-content/uploads/2026/04/my-article-shared.png"},
        ])
        mock_post.return_value = mock_response(201, {
            "id": 88,
            "source_url": "https://example.com/wp-content/uploads/2026/04/my-article-shared.jpg",
        })

        media_id = wp.upload_media(str(img))

        assert media_id == 88
        mock_post.assert_called_once()

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_in_run_cache_dedups_repeated_calls(self, mock_get, mock_post, wp, mock_response, tmp_path):
        """Calling upload_media twice for the same source should query/upload at most once."""
        wp._current_article_scope = "my-article"
        img = tmp_path / "once.jpg"
        img.write_bytes(b"once")
        mock_get.return_value = mock_response(200, [])
        mock_post.return_value = mock_response(201, {
            "id": 11,
            "source_url": "https://example.com/wp-content/uploads/2026/04/my-article-once.jpg",
        })

        first = wp.upload_media(str(img))
        get_count_after_first = mock_get.call_count
        post_count_after_first = mock_post.call_count

        second = wp.upload_media(str(img))

        assert first == 11
        assert second == 11
        assert mock_get.call_count == get_count_after_first
        assert mock_post.call_count == post_count_after_first

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_no_scope_skips_dedup_query(self, mock_get, mock_post, wp, mock_response, tmp_path):
        """Without an article scope, upload_media must NOT query the media library
        (filename-only dedup is unsafe across articles). It must just upload."""
        wp._current_article_scope = None
        img = tmp_path / "loose.jpg"
        img.write_bytes(b"loose")
        mock_post.return_value = mock_response(201, {
            "id": 200,
            "source_url": "https://example.com/wp-content/uploads/2026/04/loose.jpg",
        })

        media_id = wp.upload_media(str(img))

        assert media_id == 200
        mock_post.assert_called_once()
        # No GET to /media (no dedup lookup) - the safety property
        for call in mock_get.call_args_list:
            assert "/wp-json/wp/v2/media" not in call[0][0]

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_orphan_canonical_does_not_alias_scoped_upload(
        self, mock_get, mock_post, wp, mock_response, tmp_path
    ):
        """Regression test for ediblesites/wp-poster#5.

        The library has an orphan canonical attachment at slug "hero" (id 584)
        from whichever article was published first long ago. A new article
        publishing its own hero.webp must NOT be aliased to that orphan -
        wp-post must query by the scoped slug "fresh-article-hero" which
        returns empty, then upload a fresh scoped attachment.
        """
        wp._current_article_scope = "fresh-article"
        img = tmp_path / "hero.webp"
        img.write_bytes(b"fresh-content")

        def routed_get(url, **kwargs):
            slug = kwargs.get("params", {}).get("slug", "")
            resp = MagicMock()
            resp.status_code = 200
            if slug == "hero":
                # The orphan canonical that the OLD code would have matched
                resp.json.return_value = [{
                    "id": 584, "slug": "hero",
                    "source_url": "https://example.com/wp-content/uploads/hero.webp",
                }]
            else:
                resp.json.return_value = []
            return resp
        mock_get.side_effect = routed_get
        mock_post.return_value = mock_response(201, {
            "id": 9999,
            "source_url": "https://example.com/wp-content/uploads/fresh-article-hero.webp",
        })

        media_id = wp.upload_media(str(img))

        # Critical: must NOT be aliased to the orphan id 584
        assert media_id == 9999
        assert media_id != 584
        # The query must have been the scoped slug, not the bare basename
        assert mock_get.call_args[1]["params"]["slug"] == "fresh-article-hero"
        # And the POST went out with the scoped Content-Disposition filename
        cd_header = mock_post.call_args[1]["headers"]["Content-Disposition"]
        assert 'filename="fresh-article-hero.webp"' in cd_header

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_featured_image_dedup_on_republish(
        self, mock_get, mock_post, wp, md_file, mock_response, tmp_path
    ):
        """post_to_wordpress with a featured_image that already exists in the
        scoped media library should reuse the existing attachment id and never
        POST to /media."""
        img = tmp_path / "hero.jpg"
        img.write_bytes(b"hero")
        path = md_file({"title": "Re-published", "featured_image": str(img)}, "body")

        # Compute the scope wp-post will derive from this filepath at publish time
        expected_scope = wp._article_scope_for(path)
        scoped_slug = f"{expected_scope}-hero"

        mock_get.return_value = mock_response(200, [
            {"id": 555, "slug": scoped_slug,
             "source_url": f"https://example.com/wp-content/uploads/2026/04/{scoped_slug}.jpg"},
        ])
        mock_post.return_value = mock_response(201, {
            "id": 1, "link": "https://example.com/?p=1",
            "title": {"rendered": "Re-published"},
        })

        result = wp.post_to_wordpress(path, raw=True)

        assert result["success"] is True
        # Exactly one POST: the post creation. Zero media POSTs.
        assert mock_post.call_count == 1
        post_call = mock_post.call_args
        assert "/wp-json/wp/v2/posts" in post_call[0][0]
        assert post_call[1]["json"]["featured_media"] == 555

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_article_scope_cleared_after_publish(
        self, mock_get, mock_post, wp, md_file, mock_response, tmp_path
    ):
        """post_to_wordpress sets the scope; after the call returns the scope
        must be cleared so subsequent direct upload_media calls don't reuse
        a stale scope from a prior publish."""
        path = md_file({"title": "T"}, "body")
        mock_post.return_value = mock_response(201, {
            "id": 1, "link": "https://example.com/?p=1",
            "title": {"rendered": "T"},
        })

        wp.post_to_wordpress(path, raw=True)

        assert wp._current_article_scope is None


# ===========================================================================
# Malformed embedded Gutenberg blocks abort the post cleanly
# ===========================================================================

class TestMalformedEmbeddedGutenberg:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_unclosed_block_returns_none_no_post(self, mock_get, mock_post, wp, md_file, capsys):
        body = "Intro.\n\n<!-- wp:cover -->\n<div>oops</div>"
        path = md_file({"title": "T"}, body)
        result = wp.post_to_wordpress(path)
        assert result is None
        mock_post.assert_not_called()
        out = capsys.readouterr().out
        assert "Error" in out
        assert "wp:cover" in out
        # Line number is file-relative: ---, title: T, ---, Intro., blank
        # put the opener at file line 6 (not body line 3).
        assert "line 6" in out


# ===========================================================================
# Same-host inline images are reused, not re-downloaded/re-uploaded (issue #10)
# ===========================================================================
#
# When an inline image URL already points at the target WordPress instance,
# upload_media must resolve the existing attachment instead of downloading the
# bytes and POSTing a duplicate. Resolution is by exact source_url match so a
# same-basename image at a different upload path is not falsely aliased. If no
# attachment matches, it falls back to the normal download+upload path.

class TestSameHostMediaReuse:
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_same_host_url_reuses_existing_attachment(self, mock_get, mock_post, wp, mock_response):
        """A same-host inline image URL is resolved to its attachment - no upload."""
        url = "https://example.com/wp-content/uploads/2024/01/hero.webp"
        mock_get.return_value = mock_response(200, [
            {"id": 77, "slug": "hero", "source_url": url},
        ])

        media_id = wp.upload_media(url)

        assert media_id == 77
        mock_post.assert_not_called()
        # The attachment's own source_url is cached for content rewriting
        assert wp._media_source_cache[url] == (77, url)

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_same_host_url_no_match_falls_back_to_upload(self, mock_get, mock_post, wp, mock_response):
        """If no attachment matches the same-host URL, download + upload as normal."""
        url = "https://example.com/wp-content/uploads/2024/01/ghost.webp"

        def _get(get_url, **kwargs):
            if "/wp-json/wp/v2/media" in get_url:
                return mock_response(200, [])  # resolver query: nothing matches
            dl = mock_response(200)            # image download
            dl.content = b"img-bytes"
            dl.headers = {"content-type": "image/webp"}
            return dl

        mock_get.side_effect = _get
        mock_post.return_value = mock_response(201, {
            "id": 99,
            "source_url": "https://example.com/wp-content/uploads/2024/01/ghost.webp",
        })

        media_id = wp.upload_media(url)

        assert media_id == 99
        mock_post.assert_called_once()

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_same_host_basename_collision_at_other_path_not_reused(
        self, mock_get, mock_post, wp, mock_response
    ):
        """A same-basename attachment at a different upload path must NOT be reused;
        exact source_url match is required, so this falls back to upload."""
        url = "https://example.com/wp-content/uploads/2026/05/hero.webp"

        def _get(get_url, **kwargs):
            if "/wp-json/wp/v2/media" in get_url:
                # slug matches but source_url is a different upload path
                return mock_response(200, [
                    {"id": 5, "slug": "hero",
                     "source_url": "https://example.com/wp-content/uploads/2020/01/hero.webp"},
                ])
            dl = mock_response(200)
            dl.content = b"img-bytes"
            dl.headers = {"content-type": "image/webp"}
            return dl

        mock_get.side_effect = _get
        mock_post.return_value = mock_response(201, {
            "id": 61,
            "source_url": "https://example.com/wp-content/uploads/2026/05/hero.webp",
        })

        media_id = wp.upload_media(url)

        assert media_id == 61
        mock_post.assert_called_once()

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_cross_host_url_is_downloaded_and_uploaded(self, mock_get, mock_post, wp, mock_response):
        """A cross-host image URL still downloads + uploads, with no resolver query."""
        url = "https://cdn.other.com/img/hero.webp"
        dl = mock_response(200)
        dl.content = b"img-bytes"
        dl.headers = {"content-type": "image/webp"}
        mock_get.return_value = dl
        mock_post.return_value = mock_response(201, {
            "id": 5, "source_url": "https://example.com/hero.webp",
        })

        media_id = wp.upload_media(url)

        assert media_id == 5
        mock_post.assert_called_once()
        # No resolver/dedup query for a foreign host
        for c in mock_get.call_args_list:
            assert "/wp-json/wp/v2/media" not in c[0][0]


# ===========================================================================
# MSLS link write result handling (issue #11)
# ===========================================================================
#
# write_msls_links used to discard the subprocess result, so a failed MSLS
# write (non-zero exit, missing wp-cli, timeout) was either swallowed as
# success or crashed the whole publish. It now returns a per-member status
# list and the caller surfaces failures instead of printing a blanket success.

class TestWriteMslsLinksResult:
    @patch("wp_post.subprocess.run")
    def test_returns_ok_status_for_each_member(self, mock_run):
        # Each eval writes then echoes back the stored value; read-back matches.
        mock_run.side_effect = _msls_eval_echo()
        current = {"locale": "en_US", "blog_id": 1, "post_id": 10}
        siblings = [{"locale": "es_ES", "blog_id": 2, "post_id": 20}]

        results = write_msls_links("@test", current, siblings)

        assert {r["locale"] for r in results} == {"en_US", "es_ES"}
        assert all(r["ok"] for r in results)
        assert all(r["error"] is None for r in results)

    @patch("wp_post.subprocess.run")
    def test_payload_is_base64_encoded(self, mock_run):
        """The option payload is passed base64-encoded (not raw single-quoted
        PHP), so special characters cannot break the eval."""
        mock_run.side_effect = _msls_eval_echo()
        current = {"locale": "en_US", "blog_id": 1, "post_id": 10}
        siblings = [{"locale": "es_ES", "blog_id": 2, "post_id": 20}]

        write_msls_links("@test", current, siblings)

        en_script = mock_run.call_args_list[0][0][0][3]
        assert "base64_decode(" in en_script
        # The raw JSON payload must not appear in the command verbatim
        assert '"es_ES": 20' not in en_script
        b64 = re.search(r'base64_decode\("([^"]+)"\)', en_script).group(1)
        assert json.loads(base64.b64decode(b64).decode()) == {"es_ES": 20}

    @patch("wp_post.time.sleep")
    @patch("wp_post.subprocess.run")
    def test_nonzero_returncode_marks_member_failed(self, mock_run, mock_sleep):
        # en member succeeds; es member's wp eval exits non-zero on every attempt
        def _run(cmd, *a, **k):
            script = cmd[3]
            if "msls_20" in script:
                return MagicMock(returncode=1, stdout="", stderr="Error: Site 2 not found")
            m = re.search(r'base64_decode\("([^"]+)"\)', script)
            return MagicMock(returncode=0, stdout=base64.b64decode(m.group(1)).decode(), stderr="")
        mock_run.side_effect = _run
        current = {"locale": "en_US", "blog_id": 1, "post_id": 10}
        siblings = [{"locale": "es_ES", "blog_id": 2, "post_id": 20}]

        results = write_msls_links("@test", current, siblings)

        by_locale = {r["locale"]: r for r in results}
        assert by_locale["en_US"]["ok"] is True
        assert by_locale["es_ES"]["ok"] is False
        assert "Site 2 not found" in by_locale["es_ES"]["error"]
        # en linked once; es retried up to 3 attempts before giving up
        assert mock_run.call_count == 1 + 3

    @patch("wp_post.time.sleep")
    @patch("wp_post.subprocess.run")
    def test_readback_mismatch_marks_member_failed(self, mock_run, mock_sleep):
        """Exit 0 but the stored value doesn't match what we wrote -> failure."""
        # Always exit 0 but echo back the wrong map for the es member
        def _run(cmd, *a, **k):
            script = cmd[3]
            if "msls_20" in script:
                return MagicMock(returncode=0, stdout="{}", stderr="")
            m = re.search(r'base64_decode\("([^"]+)"\)', script)
            return MagicMock(returncode=0, stdout=base64.b64decode(m.group(1)).decode(), stderr="")
        mock_run.side_effect = _run
        current = {"locale": "en_US", "blog_id": 1, "post_id": 10}
        siblings = [{"locale": "es_ES", "blog_id": 2, "post_id": 20}]

        results = write_msls_links("@test", current, siblings)

        by_locale = {r["locale"]: r for r in results}
        assert by_locale["en_US"]["ok"] is True
        assert by_locale["es_ES"]["ok"] is False
        assert "mismatch" in by_locale["es_ES"]["error"].lower()

    @patch("wp_post.time.sleep")
    @patch("wp_post.subprocess.run")
    def test_retry_recovers_after_transient_failure(self, mock_run, mock_sleep):
        """A member that fails once then succeeds is reported ok (self-heals)."""
        state = {"es_failed_once": False}

        def _run(cmd, *a, **k):
            script = cmd[3]
            m = re.search(r'base64_decode\("([^"]+)"\)', script)
            payload = base64.b64decode(m.group(1)).decode()
            if "msls_20" in script and not state["es_failed_once"]:
                state["es_failed_once"] = True
                return MagicMock(returncode=1, stdout="", stderr="transient blip")
            return MagicMock(returncode=0, stdout=payload, stderr="")
        mock_run.side_effect = _run
        current = {"locale": "en_US", "blog_id": 1, "post_id": 10}
        siblings = [{"locale": "es_ES", "blog_id": 2, "post_id": 20}]

        results = write_msls_links("@test", current, siblings)

        assert all(r["ok"] for r in results)
        # Backoff slept at least once before the successful retry
        assert mock_sleep.call_count >= 1

    @patch("wp_post.time.sleep")
    @patch("wp_post.subprocess.run")
    def test_missing_wp_cli_fails_fast_without_retry(self, mock_run, mock_sleep):
        mock_run.side_effect = FileNotFoundError("wp")
        current = {"locale": "en_US", "blog_id": 1, "post_id": 10}
        siblings = [{"locale": "es_ES", "blog_id": 2, "post_id": 20}]

        # Must not raise - the failure is captured per member
        results = write_msls_links("@test", current, siblings)

        assert all(r["ok"] is False for r in results)
        assert all("wp-cli" in r["error"].lower() for r in results)
        # Fail fast: one attempt per member, no retries (can't self-heal in-run)
        assert mock_run.call_count == 2
        mock_sleep.assert_not_called()

    @patch("wp_post.time.sleep")
    @patch("wp_post.subprocess.run")
    def test_timeout_is_retried_then_reported(self, mock_run, mock_sleep):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="wp", timeout=15)
        current = {"locale": "en_US", "blog_id": 1, "post_id": 10}
        siblings = [{"locale": "es_ES", "blog_id": 2, "post_id": 20}]

        results = write_msls_links("@test", current, siblings)

        assert all(r["ok"] is False for r in results)
        assert all("time" in r["error"].lower() for r in results)
        # Each member retried up to 3 attempts
        assert mock_run.call_count == 2 * 3


class TestMslsFailureSurfacing:
    @patch("wp_post.time.sleep")
    @patch("wp_post.subprocess.run")
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_failure_not_reported_as_success(
        self, mock_get, mock_post, mock_subproc, mock_sleep, tmp_path, mock_response, capsys
    ):
        """A non-zero MSLS write must not print the success line, and the failure
        must be surfaced on the publish result (post still succeeds - it is live)."""
        sites = [
            {"key": "en", "site_url": "https://en.example.com", "locale": "en_US", "blog_id": 1},
            {"key": "es", "site_url": "https://es.example.com", "locale": "es_ES", "blog_id": 2},
        ]
        ts = [{"site_key": "es", "frontmatter": {"title": "Sobre", "id": 100, "translation_set": "about"}}]
        root = _scaffold_network(tmp_path, sites, ts)
        new_post = root / "en" / "content" / "index.md"
        new_post.write_text("---\ntitle: About\ntranslation_set: about\n---\nContent", encoding="utf-8")

        wp = WordPressPost("https://en.example.com", "admin", "pass")
        mock_post.return_value = mock_response(201, {
            "id": 50, "link": "https://en.example.com/about/", "title": {"rendered": "About"},
        })
        mock_subproc.return_value = MagicMock(returncode=1, stdout="", stderr="boom")

        result = wp.post_to_wordpress(str(new_post), raw=True)
        out = capsys.readouterr().out

        # Post itself still succeeded (already created in WP)
        assert result["success"] is True
        # But the MSLS failure is surfaced, not masked as success
        assert "✓ MSLS translation links written" not in out
        assert result.get("msls_failures")

    @patch("wp_post.subprocess.run")
    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_success_still_reports_clean(
        self, mock_get, mock_post, mock_subproc, tmp_path, mock_response, capsys
    ):
        """The happy path is unchanged: all members succeed -> success line, no failures."""
        sites = [
            {"key": "en", "site_url": "https://en.example.com", "locale": "en_US", "blog_id": 1},
            {"key": "es", "site_url": "https://es.example.com", "locale": "es_ES", "blog_id": 2},
        ]
        ts = [{"site_key": "es", "frontmatter": {"title": "Sobre", "id": 100, "translation_set": "about"}}]
        root = _scaffold_network(tmp_path, sites, ts)
        new_post = root / "en" / "content" / "index.md"
        new_post.write_text("---\ntitle: About\ntranslation_set: about\n---\nContent", encoding="utf-8")

        wp = WordPressPost("https://en.example.com", "admin", "pass")
        mock_post.return_value = mock_response(201, {
            "id": 50, "link": "https://en.example.com/about/", "title": {"rendered": "About"},
        })
        mock_subproc.side_effect = _msls_eval_echo()

        result = wp.post_to_wordpress(str(new_post), raw=True)
        out = capsys.readouterr().out

        assert result["success"] is True
        assert "✓ MSLS translation links written" in out
        assert not result.get("msls_failures")


class TestMainMslsExit:
    """main() must reflect MSLS failures in its machine-readable output and exit
    code - the surface that stayed silent in the incident (issue #11)."""

    @patch.object(wp_post.WordPressPost, "post_to_wordpress")
    @patch("wp_post.load_config")
    def test_msls_failure_exits_nonzero_and_reports(
        self, mock_load_config, mock_post_to_wp, tmp_path, capsys
    ):
        f = tmp_path / "post.md"
        f.write_text("---\ntitle: T\n---\nbody", encoding="utf-8")
        mock_load_config.return_value = {
            "site_url": "https://example.com", "username": "u", "app_password": "p",
        }
        mock_post_to_wp.return_value = {
            "success": True, "id": 50, "url": "https://example.com/p/", "title": "T",
            "msls_failures": [{"locale": "es_ES", "post_id": 20, "ok": False, "error": "boom"}],
        }

        with patch("sys.argv", ["wp-post", "--site-url", "https://example.com",
                                 "--username", "u", "--app-password", "p", str(f)]):
            with pytest.raises(SystemExit) as exc:
                wp_post.main()

        assert exc.value.code == 1
        payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert payload.get("msls_failures")

    @patch.object(wp_post.WordPressPost, "post_to_wordpress")
    @patch("wp_post.load_config")
    def test_clean_publish_exits_zero(
        self, mock_load_config, mock_post_to_wp, tmp_path, capsys
    ):
        f = tmp_path / "post.md"
        f.write_text("---\ntitle: T\n---\nbody", encoding="utf-8")
        mock_load_config.return_value = {
            "site_url": "https://example.com", "username": "u", "app_password": "p",
        }
        mock_post_to_wp.return_value = {
            "success": True, "id": 50, "url": "https://example.com/p/", "title": "T",
        }

        with patch("sys.argv", ["wp-post", "--site-url", "https://example.com",
                                 "--username", "u", "--app-password", "p", str(f)]):
            # Clean success falls through main() without sys.exit -> returns None
            wp_post.main()

        payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert payload["success"] is True
        assert "msls_failures" not in payload


# ===========================================================================
# Cache purging: config discovery and transport
# ===========================================================================

read_frontmatter = wp_post.read_frontmatter
find_config_for_purge = wp_post.find_config_for_purge
resolve_wp_cli_transport = wp_post.resolve_wp_cli_transport
PurgeConfigError = wp_post.PurgeConfigError


_PURGE_SITES = [
    {'key': 'en', 'site_url': 'https://e.com', 'locale': 'en_US', 'blog_id': 1},
    {'key': 'de', 'site_url': 'https://e.com/de', 'locale': 'de_DE', 'blog_id': 3},
]


class TestReadFrontmatter:
    def test_reads_frontmatter(self, tmp_path):
        f = tmp_path / 'a.md'
        f.write_text('---\ntitle: T\nid: 412\n---\nbody', encoding='utf-8')
        assert read_frontmatter(str(f)) == {'title': 'T', 'id': 412}

    def test_returns_empty_without_frontmatter(self, tmp_path):
        f = tmp_path / 'a.md'
        f.write_text('just body', encoding='utf-8')
        assert read_frontmatter(str(f)) == {}

    def test_parse_frontmatter_only_still_works(self, wp, tmp_path):
        f = tmp_path / 'a.md'
        f.write_text('---\ntitle: T\n---\nbody', encoding='utf-8')
        assert wp.parse_frontmatter_only(str(f)) == {'title': 'T'}


class TestFindConfigForPurge:
    def test_finds_config_beside_the_file_not_the_cwd(self, tmp_path, monkeypatch):
        """Regression: config must be anchored at the target file.

        load_config() walks up from the CWD, so an absolute --file path from
        another project would otherwise purge whichever site the shell is
        sitting in.
        """
        project = tmp_path / 'project'
        (project / 'content').mkdir(parents=True)
        (project / '.wp-poster.json').write_text(
            json.dumps({'site_url': 'https://right.com', 'wp_cli_alias': '@right'}))
        target = project / 'content' / 'post.md'
        target.write_text('---\ntitle: T\nid: 5\n---\nbody', encoding='utf-8')

        decoy = tmp_path / 'decoy'
        decoy.mkdir()
        (decoy / '.wp-poster.json').write_text(json.dumps({'site_url': 'https://wrong.com'}))
        monkeypatch.chdir(decoy)

        config, config_path, project_root = find_config_for_purge(str(target))
        assert config['site_url'] == 'https://right.com'
        assert config_path == str(project / '.wp-poster.json')
        assert project_root is None

    def test_network_config_sets_project_root(self, tmp_path):
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        target = root / 'de' / 'content' / 'p.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('---\ntitle: T\nid: 1\n---\nbody', encoding='utf-8')

        config, config_path, project_root = find_config_for_purge(str(target))
        assert 'network' in config
        assert project_root == str(root)

    def test_network_config_wins_over_nearer_per_site_config(self, tmp_path):
        """Legacy layout: a per-site config must not shadow the network map."""
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        (root / 'de' / '.wp-poster.json').write_text(
            json.dumps({'site_url': 'https://e.com/de', 'locale': 'de_DE', 'blog_id': 3}))
        target = root / 'de' / 'content' / 'p.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('---\ntitle: T\nid: 1\n---\nbody', encoding='utf-8')

        config, _path, project_root = find_config_for_purge(str(target))
        assert 'network' in config
        assert project_root == str(root)

    def test_accepts_a_directory_anchor(self, tmp_path):
        (tmp_path / '.wp-poster.json').write_text(json.dumps({'site_url': 'https://x.com'}))
        config, _path, project_root = find_config_for_purge(str(tmp_path))
        assert config['site_url'] == 'https://x.com'
        assert project_root is None

    def test_no_config_anywhere_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wp_post, '_global_config_paths', lambda: [])
        with pytest.raises(PurgeConfigError) as exc:
            find_config_for_purge(str(tmp_path / 'nothing' / 'here.md'))
        assert '.wp-poster.json' in str(exc.value)

    def test_global_network_config_sets_project_root(self, tmp_path, monkeypatch):
        """Regression: a global fallback config can itself have a 'network'
        key. project_root must then point at its directory, exactly as the
        walk-up branch does, or resolve_site_identity's os.path.join(None, ..)
        raises an uncaught TypeError later."""
        global_dir = tmp_path / 'global'
        global_dir.mkdir()
        global_config = global_dir / '.wp-poster.json'
        global_config.write_text(json.dumps({
            'network': {'wp_cli_alias': '@testsite', 'sites': {
                'en': {'content_path': 'en/content/', 'site_url': 'https://e.com',
                       'locale': 'en_US', 'blog_id': 1},
            }},
        }))
        monkeypatch.setattr(wp_post, '_global_config_paths', lambda: [global_config])

        anchor = tmp_path / 'elsewhere' / 'post.md'
        config, config_path, project_root = find_config_for_purge(str(anchor))
        assert 'network' in config
        assert config_path == str(global_config)
        assert project_root == str(global_dir)


class TestResolveWpCliTransport:
    PATH = '/p/.wp-poster.json'

    def test_network_alias(self):
        config = {'network': {'wp_cli_alias': '@payperfax', 'sites': {}}}
        assert resolve_wp_cli_transport(config, self.PATH) == ['wp', '@payperfax']

    def test_top_level_alias(self):
        assert resolve_wp_cli_transport({'wp_cli_alias': '@dashpadd'}, self.PATH) == ['wp', '@dashpadd']

    def test_ssh_target_becomes_ssh_flag(self):
        config = {'wp_cli_alias': 'dash/sites/dashpadd.com/files'}
        assert resolve_wp_cli_transport(config, self.PATH) == [
            'wp', '--ssh=dash/sites/dashpadd.com/files']

    def test_network_alias_wins_over_top_level(self):
        config = {'wp_cli_alias': 'ignored', 'network': {'wp_cli_alias': '@net', 'sites': {}}}
        assert resolve_wp_cli_transport(config, self.PATH) == ['wp', '@net']

    def test_missing_alias_names_the_config_file(self):
        with pytest.raises(PurgeConfigError) as exc:
            resolve_wp_cli_transport({'site_url': 'https://example.com'}, self.PATH)
        assert 'wp_cli_alias' in str(exc.value)
        assert self.PATH in str(exc.value)

    def test_non_string_alias_rejected(self):
        with pytest.raises(PurgeConfigError):
            resolve_wp_cli_transport({'wp_cli_alias': 123}, self.PATH)


class TestFindSiteForFileBoundaries:
    NET = {'network': {'sites': {
        'de': {'content_path': 'de/content/', 'site_url': 'https://e/de', 'blog_id': 3},
    }}}

    def test_sibling_directory_sharing_a_prefix_does_not_match(self):
        key, info = find_site_for_file('/project', self.NET, '/project/de/content-evil/post.md')
        assert key is None
        assert info is None

    def test_exact_content_root_still_matches(self):
        key, _info = find_site_for_file('/project', self.NET, '/project/de/content/post.md')
        assert key == 'de'

    def test_nested_path_still_matches(self):
        key, _info = find_site_for_file('/project', self.NET, '/project/de/content/a/b/post.md')
        assert key == 'de'


# ===========================================================================
# Cache purging: scope resolution
# ===========================================================================

resolve_purge_targets = wp_post.resolve_purge_targets


def _purge_network(tmp_path):
    """Scaffold a 2-site network and return (project_root, config)."""
    root = _scaffold_network_map(tmp_path, _PURGE_SITES)
    with open(root / '.wp-poster.json') as f:
        return str(root), json.load(f)


class TestResolvePurgeTargetsNetwork:
    def test_network_scope_returns_every_site(self, tmp_path):
        root, config = _purge_network(tmp_path)
        targets = resolve_purge_targets('network', None, config, root)
        assert [t['label'] for t in targets] == ['en', 'de']
        assert [t['site_url'] for t in targets] == ['https://e.com', 'https://e.com/de']
        assert all(t['post_id'] is None for t in targets)

    def test_site_scope_returns_one_site(self, tmp_path):
        root, config = _purge_network(tmp_path)
        targets = resolve_purge_targets('site', 'de', config, root)
        assert targets == [{'label': 'de', 'site_url': 'https://e.com/de', 'post_id': None}]

    def test_unknown_site_key_lists_valid_keys(self, tmp_path):
        root, config = _purge_network(tmp_path)
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('site', 'zz', config, root)
        assert 'de' in str(exc.value) and 'en' in str(exc.value)

    def test_site_scope_without_key_on_network_raises(self, tmp_path):
        root, config = _purge_network(tmp_path)
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('site', '', config, root)
        assert 'requires a site key' in str(exc.value)

    def test_file_scope_resolves_blog_from_path(self, tmp_path):
        root, config = _purge_network(tmp_path)
        target_file = tmp_path / 'de' / 'content' / 'post' / 'index.md'
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text('---\ntitle: T\nid: 412\n---\nbody', encoding='utf-8')

        targets = resolve_purge_targets('file', str(target_file), config, root)
        assert targets == [{'label': 'de #412', 'site_url': 'https://e.com/de', 'post_id': 412}]

    def test_file_outside_every_content_path_raises(self, tmp_path):
        root, config = _purge_network(tmp_path)
        stray = tmp_path / 'elsewhere' / 'index.md'
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_text('---\ntitle: T\nid: 9\n---\nbody', encoding='utf-8')

        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('file', str(stray), config, root)
        assert 'content_path' in str(exc.value)


class TestResolvePurgeTargetsUnpublished:
    def test_missing_id_raises(self, tmp_path):
        root, config = _purge_network(tmp_path)
        f = tmp_path / 'de' / 'content' / 'x.md'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('---\ntitle: T\n---\nbody', encoding='utf-8')
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('file', str(f), config, root)
        assert 'not been published' in str(exc.value)

    def test_null_id_raises(self, tmp_path):
        root, config = _purge_network(tmp_path)
        f = tmp_path / 'de' / 'content' / 'x.md'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('---\ntitle: T\nid: null\n---\nbody', encoding='utf-8')
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('file', str(f), config, root)
        assert 'not been published' in str(exc.value)

    def test_missing_file_raises_purge_error_not_oserror(self, tmp_path):
        """A nonexistent --file must not escape as a traceback."""
        root, config = _purge_network(tmp_path)
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('file', str(tmp_path / 'de' / 'content' / 'nope.md'), config, root)
        assert 'Could not read' in str(exc.value)

    def test_malformed_yaml_raises_purge_error(self, tmp_path):
        root, config = _purge_network(tmp_path)
        f = tmp_path / 'de' / 'content' / 'bad.md'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('---\ntitle: "unterminated\n  bad: [\n---\nbody', encoding='utf-8')
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('file', str(f), config, root)
        assert 'Could not read' in str(exc.value)


class TestResolvePurgeTargetsSingleSite:
    SINGLE = {'site_url': 'https://dashpadd.com', 'wp_cli_alias': 'dash/sites/dashpadd.com/files'}

    def test_site_scope_uses_top_level_site_url(self):
        targets = resolve_purge_targets('site', '', self.SINGLE, None)
        assert targets == [{'label': 'https://dashpadd.com',
                            'site_url': 'https://dashpadd.com', 'post_id': None}]

    def test_file_scope_uses_top_level_site_url(self, tmp_path):
        f = tmp_path / 'a.md'
        f.write_text('---\ntitle: T\nid: 77\n---\nbody', encoding='utf-8')
        targets = resolve_purge_targets('file', str(f), self.SINGLE, None)
        assert targets == [{'label': '#77', 'site_url': 'https://dashpadd.com', 'post_id': 77}]

    def test_network_scope_rejected(self):
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('network', None, self.SINGLE, None, '/p/.wp-poster.json')
        assert '/p/.wp-poster.json' in str(exc.value)

    def test_missing_site_url_raises(self):
        with pytest.raises(PurgeConfigError):
            resolve_purge_targets('site', '', {'wp_cli_alias': '@x'}, None)


class TestResolvePurgeTargetsValidation:
    def test_incomplete_network_entry_raises_before_any_command(self, tmp_path):
        """resolve_site_identity yields site_url=None for an incomplete entry.

        Patches subprocess.run to prove the failure happens before any wp-cli
        call would be spawned, and asserts the config_path itself (not just
        the word 'site_url') is in the message.
        """
        config = {'network': {'wp_cli_alias': '@x', 'sites': {
            'de': {'content_path': 'de/content/'},   # no site_url / locale / blog_id
        }}}
        config_path = str(tmp_path / '.wp-poster.json')
        with patch('wp_post.subprocess.run') as mock_run:
            with pytest.raises(PurgeConfigError) as exc:
                resolve_purge_targets('site', 'de', config, str(tmp_path), config_path)
            mock_run.assert_not_called()
        assert 'site_url' in str(exc.value)
        assert config_path in str(exc.value)

    def test_non_http_site_url_rejected(self, tmp_path):
        config = {'network': {'wp_cli_alias': '@x', 'sites': {
            'de': {'content_path': 'de/content/', 'site_url': 'ftp://e.com', 'blog_id': 3},
        }}}
        config_path = str(tmp_path / '.wp-poster.json')
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('site', 'de', config, str(tmp_path), config_path)
        assert 'site_url' in str(exc.value)
        assert config_path in str(exc.value)

    def test_non_integer_post_id_rejected(self, tmp_path):
        f = tmp_path / 'a.md'
        f.write_text('---\ntitle: T\nid: "not-a-number"\n---\nbody', encoding='utf-8')
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('file', str(f), {'site_url': 'https://x.com'}, None)
        assert 'post id' in str(exc.value)

    def test_boolean_post_id_rejected(self, tmp_path):
        """id: true is truthy (passes the 'not been published' check) but is
        not an integer - isinstance(True, int) is True in Python, so this is
        the branch most likely to regress silently if the bool guard is lost.
        """
        f = tmp_path / 'a.md'
        f.write_text('---\ntitle: T\nid: true\n---\nbody', encoding='utf-8')
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('file', str(f), {'site_url': 'https://x.com'}, None)
        assert 'post id' in str(exc.value)

    def test_negative_post_id_rejected(self, tmp_path):
        f = tmp_path / 'a.md'
        f.write_text('---\ntitle: T\nid: -5\n---\nbody', encoding='utf-8')
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('file', str(f), {'site_url': 'https://x.com'}, None)
        assert 'post id' in str(exc.value)

    def test_zero_post_id_rejected_as_unpublished_not_as_bad_id(self, tmp_path):
        """id: 0 is falsy, so it is caught by the 'not been published' check
        before it ever reaches the post-id validation - it never reads as a
        bad id, it reads as no id at all.
        """
        f = tmp_path / 'a.md'
        f.write_text('---\ntitle: T\nid: 0\n---\nbody', encoding='utf-8')
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('file', str(f), {'site_url': 'https://x.com'}, None)
        assert 'not been published' in str(exc.value)

    def test_missing_content_path_reported_via_file_scope(self, tmp_path):
        """A network.sites entry missing content_path must not escape as a
        bare KeyError from find_site_for_file - it must be reported before
        any subprocess, naming the config.
        """
        config = {'network': {'wp_cli_alias': '@x', 'sites': {
            'de': {'site_url': 'https://e.com/de', 'blog_id': 3},  # no content_path
        }}}
        config_path = str(tmp_path / '.wp-poster.json')
        f = tmp_path / 'x.md'
        f.write_text('---\ntitle: T\nid: 5\n---\nbody', encoding='utf-8')
        with patch('wp_post.subprocess.run') as mock_run:
            with pytest.raises(PurgeConfigError) as exc:
                resolve_purge_targets('file', str(f), config, str(tmp_path), config_path)
            mock_run.assert_not_called()
        assert 'content_path' in str(exc.value)
        assert config_path in str(exc.value)

    def test_null_content_path_reported_via_file_scope(self, tmp_path):
        """A network.sites entry with content_path: null must not escape as a
        bare TypeError from find_site_for_file's Path() construction.
        """
        config = {'network': {'wp_cli_alias': '@x', 'sites': {
            'de': {'content_path': None, 'site_url': 'https://e.com/de', 'blog_id': 3},
        }}}
        config_path = str(tmp_path / '.wp-poster.json')
        f = tmp_path / 'x.md'
        f.write_text('---\ntitle: T\nid: 5\n---\nbody', encoding='utf-8')
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('file', str(f), config, str(tmp_path), config_path)
        assert 'content_path' in str(exc.value)
        assert config_path in str(exc.value)

    def test_site_scope_missing_key_names_the_source(self, tmp_path):
        config = {'network': {'wp_cli_alias': '@x', 'sites': {
            'de': {'content_path': 'de/content/', 'site_url': 'https://e.com/de', 'blog_id': 3},
        }}}
        config_path = str(tmp_path / '.wp-poster.json')
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('site', '', config, str(tmp_path), config_path)
        assert config_path in str(exc.value)

    def test_site_scope_unknown_key_names_the_source(self, tmp_path):
        config = {'network': {'wp_cli_alias': '@x', 'sites': {
            'de': {'content_path': 'de/content/', 'site_url': 'https://e.com/de', 'blog_id': 3},
        }}}
        config_path = str(tmp_path / '.wp-poster.json')
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('site', 'zz', config, str(tmp_path), config_path)
        assert config_path in str(exc.value)

    def test_bad_post_id_message_names_the_offending_file(self, tmp_path):
        """The post-id validation error must locate the actual markdown file,
        not just the config that supplied the site_url.
        """
        f = tmp_path / 'a.md'
        f.write_text('---\ntitle: T\nid: -5\n---\nbody', encoding='utf-8')
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('file', str(f), {'site_url': 'https://x.com'}, None, '/p/.wp-poster.json')
        assert str(f) in str(exc.value)
        assert '/p/.wp-poster.json' in str(exc.value)


# ===========================================================================
# Cache purging: command construction and execution
# ===========================================================================

build_purge_command = wp_post.build_purge_command
spinupwp_purge = wp_post.spinupwp_purge

_TRANSPORT = ['wp', '@payperfax']
_SITE_TARGET = {'label': 'de', 'site_url': 'https://e.com/de', 'post_id': None}
_POST_TARGET = {'label': 'de #412', 'site_url': 'https://e.com/de', 'post_id': 412}


class TestBuildPurgeCommand:
    def test_site_command(self):
        assert build_purge_command(_TRANSPORT, _SITE_TARGET) == [
            'wp', '@payperfax', 'spinupwp', 'cache', 'purge-site',
            '--url=https://e.com/de',
        ]

    def test_post_command(self):
        assert build_purge_command(_TRANSPORT, _POST_TARGET) == [
            'wp', '@payperfax', 'spinupwp', 'cache', 'purge-post', '412',
            '--url=https://e.com/de',
        ]

    def test_ssh_transport_is_preserved(self):
        transport = ['wp', '--ssh=dash/sites/dashpadd.com/files']
        assert build_purge_command(transport, _SITE_TARGET)[:2] == transport


class TestSpinupwpPurge:
    @patch('wp_post.subprocess.run')
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='Success.', stderr='')
        assert spinupwp_purge(_TRANSPORT, _SITE_TARGET) == (True, None)

    @patch('wp_post.subprocess.run')
    def test_nonzero_exit_reports_stderr(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout='', stderr='no such blog')
        ok, error = spinupwp_purge(_TRANSPORT, _SITE_TARGET)
        assert ok is False
        assert 'no such blog' in error

    @patch('wp_post.subprocess.run', side_effect=FileNotFoundError)
    def test_wp_cli_missing(self, mock_run):
        ok, error = spinupwp_purge(_TRANSPORT, _SITE_TARGET)
        assert ok is False
        assert 'wp-cli not found' in error

    @patch('wp_post.subprocess.run',
           side_effect=wp_post.subprocess.TimeoutExpired(cmd='wp', timeout=30))
    def test_timeout(self, mock_run):
        ok, error = spinupwp_purge(_TRANSPORT, _SITE_TARGET)
        assert ok is False
        assert 'timed out' in error

    @patch('wp_post.subprocess.run', side_effect=PermissionError("denied"))
    def test_other_oserror_is_returned_not_raised(self, mock_run):
        ok, error = spinupwp_purge(_TRANSPORT, _SITE_TARGET)
        assert ok is False
        assert 'denied' in error

    @patch('wp_post.subprocess.run')
    def test_runs_the_built_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')
        spinupwp_purge(_TRANSPORT, _POST_TARGET)
        assert mock_run.call_args[0][0] == build_purge_command(_TRANSPORT, _POST_TARGET)


# ===========================================================================
# Cache purging: orchestration
# ===========================================================================

handle_purge = wp_post.handle_purge


class _PurgeArgs:
    """Stand-in for the argparse Namespace handle_purge consumes."""
    def __init__(self, purge_file=None, purge_site=None, purge_network=False,
                 test=False, verbose=False):
        self.purge_file = purge_file
        self.purge_site = purge_site
        self.purge_network = purge_network
        self.test = test
        self.verbose = verbose


class TestHandlePurge:
    @patch('wp_post.spinupwp_purge', return_value=(True, None))
    def test_network_purges_every_site_and_exits_zero(self, mock_purge, tmp_path, monkeypatch):
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        monkeypatch.chdir(root)

        assert handle_purge(_PurgeArgs(purge_network=True)) == 0
        assert mock_purge.call_count == 2
        urls = [c[0][1]['site_url'] for c in mock_purge.call_args_list]
        assert urls == ['https://e.com', 'https://e.com/de']

    @patch('wp_post.spinupwp_purge', side_effect=[(False, 'boom'), (True, None)])
    def test_one_failure_does_not_abort_the_rest(self, mock_purge, tmp_path, monkeypatch):
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        monkeypatch.chdir(root)

        assert handle_purge(_PurgeArgs(purge_network=True)) == 1
        assert mock_purge.call_count == 2

    @patch('wp_post.spinupwp_purge', return_value=(True, None))
    def test_file_scope_purges_the_post(self, mock_purge, tmp_path, monkeypatch):
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        f = root / 'de' / 'content' / 'p' / 'index.md'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('---\ntitle: T\nid: 412\n---\nbody', encoding='utf-8')
        monkeypatch.chdir(root)

        assert handle_purge(_PurgeArgs(purge_file=str(f))) == 0
        target = mock_purge.call_args[0][1]
        assert target == {'label': 'de #412', 'site_url': 'https://e.com/de', 'post_id': 412}

    @patch('wp_post.spinupwp_purge', return_value=(True, None))
    def test_file_scope_ignores_cwd_config(self, mock_purge, tmp_path, monkeypatch):
        """Regression: the target file's project, not the shell's, decides the site.

        The network root and the decoy must live in separate subtrees. If the
        decoy were nested inside the network root, walking up from it would
        still reach the network config (network-beats-nearest), so the decoy
        would never get a chance to win and the test would pass either way.
        """
        root = _scaffold_network_map(tmp_path / 'net', _PURGE_SITES)
        f = root / 'de' / 'content' / 'p' / 'index.md'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('---\ntitle: T\nid: 412\n---\nbody', encoding='utf-8')

        decoy = tmp_path / 'decoy'
        decoy.mkdir()
        (decoy / '.wp-poster.json').write_text(
            json.dumps({'site_url': 'https://wrong.com', 'wp_cli_alias': '@wrong'}))
        monkeypatch.chdir(decoy)

        assert handle_purge(_PurgeArgs(purge_file=str(f))) == 0
        assert mock_purge.call_args[0][1]['site_url'] == 'https://e.com/de'

    @patch('wp_post.subprocess.run')
    def test_end_to_end_command_reaches_subprocess(self, mock_run, tmp_path, monkeypatch):
        """The one orchestration test that goes through the real call chain."""
        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        monkeypatch.chdir(root)

        assert handle_purge(_PurgeArgs(purge_site='de')) == 0
        assert mock_run.call_args[0][0] == [
            'wp', '@testsite', 'spinupwp', 'cache', 'purge-site', '--url=https://e.com/de']

    @patch('wp_post.spinupwp_purge')
    def test_test_mode_runs_nothing(self, mock_purge, tmp_path, monkeypatch, capsys):
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        monkeypatch.chdir(root)

        assert handle_purge(_PurgeArgs(purge_network=True, test=True)) == 0
        mock_purge.assert_not_called()
        assert 'purge-site' in capsys.readouterr().out

    @patch('wp_post.spinupwp_purge')
    def test_config_error_exits_one_without_purging(self, mock_purge, tmp_path, monkeypatch):
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        f = root / 'de' / 'content' / 'unpublished.md'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('---\ntitle: T\n---\nbody', encoding='utf-8')
        monkeypatch.chdir(root)

        assert handle_purge(_PurgeArgs(purge_file=str(f))) == 1
        mock_purge.assert_not_called()

    def test_no_scope_selector_exits_one(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert handle_purge(_PurgeArgs()) == 1

    @patch('wp_post.spinupwp_purge', return_value=(True, None))
    def test_two_scope_selectors_exit_one(self, mock_purge, tmp_path, monkeypatch):
        """Regression: with a config that could actually satisfy either scope,
        rejecting must come from the scope-count check itself, not from config
        resolution failing anyway. A bare tmp_path with no config would exit 1
        either way, masking a mutation that lets multiple scopes through."""
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        monkeypatch.chdir(root)

        assert handle_purge(_PurgeArgs(purge_site='de', purge_network=True)) == 1
        mock_purge.assert_not_called()

    @patch('wp_post.spinupwp_purge', return_value=(True, None))
    def test_bare_site_scope_purges_single_site_config(self, mock_purge, tmp_path, monkeypatch):
        """Regression: bare --site ('') must be distinguished from absent (None)
        via `is not None`, not truthiness - '' is falsy but is a valid, active
        scope selector meaning 'the configured site'. A truthiness check would
        silently treat this as no scope selected."""
        (tmp_path / '.wp-poster.json').write_text(json.dumps({
            'site_url': 'https://dashpadd.com',
            'wp_cli_alias': 'dash/sites/dashpadd.com/files',
        }))
        monkeypatch.chdir(tmp_path)

        assert handle_purge(_PurgeArgs(purge_site='')) == 0
        assert mock_purge.call_count == 1
        assert mock_purge.call_args[0][1]['site_url'] == 'https://dashpadd.com'


class TestPurgeArgparseWiring:
    def test_dash_dash_file_does_not_collide_with_positional(self):
        """Regression: --file without an explicit dest silently nulls the value."""
        args = wp_post.build_arg_parser().parse_args(['--purge', '--file', 'x.md'])
        assert args.purge_file == 'x.md'
        assert args.file is None

    def test_positional_file_still_parses(self):
        args = wp_post.build_arg_parser().parse_args(['post.md'])
        assert args.file == 'post.md'
        assert args.purge_file is None

    def test_bare_site_flag_is_empty_string(self):
        assert wp_post.build_arg_parser().parse_args(['--purge', '--site']).purge_site == ''

    def test_site_flag_with_key(self):
        assert wp_post.build_arg_parser().parse_args(['--purge', '--site', 'de']).purge_site == 'de'


class TestMainPurgeDispatch:
    @patch('wp_post.handle_purge', return_value=3)
    def test_main_dispatches_and_propagates_exit_code(self, mock_handle, monkeypatch):
        monkeypatch.setattr(sys, 'argv', ['wp-post', '--purge', '--network'])
        with pytest.raises(SystemExit) as exc:
            wp_post.main()
        assert exc.value.code == 3
        assert mock_handle.called

    def test_site_selector_without_purge_flag_errors_instead_of_posting(self, monkeypatch, capsys):
        """Regression: --site now exact-matches the new purge flag, shadowing
        what used to be an unambiguous abbreviation of --site-url. Silently
        discarding the override and posting to the config's site would be a
        wrong-target publish; it must fail loudly instead.

        Asserts the actual message, not just exit code 1: without the guard,
        main() falls through to the file-existence check and exits 1 for
        "File 'post.md' not found" - same exit code, wrong reason."""
        monkeypatch.setattr(sys, 'argv', ['wp-post', '--site', 'https://override.com', 'post.md'])
        with pytest.raises(SystemExit) as exc:
            wp_post.main()
        assert exc.value.code == 1
        assert "only valid with --purge" in capsys.readouterr().err

    def test_network_selector_without_purge_flag_errors_instead_of_posting(self, monkeypatch, capsys):
        """Regression: --network post.md --test used to silently ignore
        --network and run a normal post in test mode."""
        monkeypatch.setattr(sys, 'argv', ['wp-post', '--network', 'post.md', '--test'])
        with pytest.raises(SystemExit) as exc:
            wp_post.main()
        assert exc.value.code == 1
        assert "only valid with --purge" in capsys.readouterr().err

    def test_file_selector_without_purge_flag_errors(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, 'argv', ['wp-post', '--file', 'post.md'])
        with pytest.raises(SystemExit) as exc:
            wp_post.main()
        assert exc.value.code == 1
        assert "only valid with --purge" in capsys.readouterr().err


class TestBookmarkResolution:
    def _post_payload(self, **overrides):
        payload = {
            "title": {"rendered": "My Other Post"},
            "link": "https://example.com/my-other-post/",
            "excerpt": {"rendered": "<p>A short excerpt. [&hellip;]</p>"},
        }
        payload.update(overrides)
        return payload

    @patch('wp_post.requests.get')
    def test_resolves_slug_from_path(self, mock_get, wp, mock_response):
        mock_get.return_value = mock_response(200, [self._post_payload()])
        data = wp._resolve_bookmark("/my-other-post/")
        assert data["title"] == "My Other Post"
        assert data["link"] == "https://example.com/my-other-post/"
        assert mock_get.call_args.kwargs["params"]["slug"] == "my-other-post"

    @patch('wp_post.requests.get')
    def test_resolves_slug_from_full_url(self, mock_get, wp, mock_response):
        mock_get.return_value = mock_response(200, [self._post_payload()])
        wp._resolve_bookmark("https://example.com/my-other-post/")
        assert mock_get.call_args.kwargs["params"]["slug"] == "my-other-post"

    @patch('wp_post.requests.get')
    def test_excerpt_is_stripped_of_html_and_more_marker(self, mock_get, wp, mock_response):
        mock_get.return_value = mock_response(200, [self._post_payload()])
        data = wp._resolve_bookmark("my-other-post")
        assert data["excerpt"] == "A short excerpt."

    @patch('wp_post.requests.get')
    def test_featured_image_is_read_from_embed(self, mock_get, wp, mock_response):
        payload = self._post_payload(
            featured_media=123,
            _embedded={"wp:featuredmedia": [{"id": 123, "source_url": "https://example.com/t.jpg"}]},
        )
        mock_get.return_value = mock_response(200, [payload])
        data = wp._resolve_bookmark("my-other-post")
        assert data["image_url"] == "https://example.com/t.jpg"
        assert data["image_id"] == 123

    @patch('wp_post.requests.get')
    def test_falls_back_to_pages_when_no_post_matches(self, mock_get, wp, mock_response):
        mock_get.side_effect = [
            mock_response(200, []),
            mock_response(200, [self._post_payload()]),
        ]
        data = wp._resolve_bookmark("my-other-post")
        assert data["title"] == "My Other Post"
        assert mock_get.call_count == 2
        assert "/pages" in mock_get.call_args_list[1].args[0]

    @patch('wp_post.requests.get')
    def test_returns_none_when_nothing_matches(self, mock_get, wp, mock_response):
        mock_get.return_value = mock_response(200, [])
        assert wp._resolve_bookmark("nope") is None

    @patch('wp_post.requests.get')
    def test_result_is_cached_per_instance(self, mock_get, wp, mock_response):
        mock_get.return_value = mock_response(200, [self._post_payload()])
        wp._resolve_bookmark("my-other-post")
        wp._resolve_bookmark("my-other-post")
        assert mock_get.call_count == 1

    @patch('wp_post.requests.get')
    def test_network_error_returns_none(self, mock_get, wp):
        mock_get.side_effect = requests.RequestException("down")
        assert wp._resolve_bookmark("my-other-post") is None

    @patch('wp_post.requests.get')
    def test_dict_body_falls_back_to_pages_and_warns(self, mock_get, wp, mock_response, capsys):
        mock_get.side_effect = [
            mock_response(200, {"code": "rest_no_route"}),
            mock_response(200, [self._post_payload()]),
        ]
        data = wp._resolve_bookmark("my-other-post")
        assert data["title"] == "My Other Post"
        assert mock_get.call_count == 2
        assert "my-other-post" in capsys.readouterr().err

    @patch('wp_post.requests.get')
    def test_string_body_falls_back_to_pages_and_warns(self, mock_get, wp, mock_response, capsys):
        mock_get.side_effect = [
            mock_response(200, "not a list"),
            mock_response(200, [self._post_payload()]),
        ]
        data = wp._resolve_bookmark("my-other-post")
        assert data["title"] == "My Other Post"
        assert mock_get.call_count == 2
        assert capsys.readouterr().err != ""

    @patch('wp_post.requests.get')
    def test_list_of_non_dict_falls_back_to_pages_and_warns(self, mock_get, wp, mock_response, capsys):
        mock_get.side_effect = [
            mock_response(200, [None]),
            mock_response(200, [self._post_payload()]),
        ]
        data = wp._resolve_bookmark("my-other-post")
        assert data["title"] == "My Other Post"
        assert mock_get.call_count == 2
        assert capsys.readouterr().err != ""

    @patch('wp_post.requests.get')
    def test_empty_list_falls_back_to_pages_without_warning(self, mock_get, wp, mock_response, capsys):
        mock_get.side_effect = [
            mock_response(200, []),
            mock_response(200, [self._post_payload()]),
        ]
        data = wp._resolve_bookmark("my-other-post")
        assert data["title"] == "My Other Post"
        assert capsys.readouterr().err == ""

    @patch('wp_post.requests.get')
    def test_malformed_body_on_both_endpoints_returns_none_without_raising(self, mock_get, wp, mock_response, capsys):
        mock_get.return_value = mock_response(200, {"code": "rest_no_route"})
        assert wp._resolve_bookmark("my-other-post") is None
        assert mock_get.call_count == 2
        assert capsys.readouterr().err != ""

    @patch('wp_post.requests.get')
    def test_malformed_result_is_still_cached(self, mock_get, wp, mock_response):
        mock_get.return_value = mock_response(200, {"code": "rest_no_route"})
        wp._resolve_bookmark("my-other-post")
        wp._resolve_bookmark("my-other-post")
        assert mock_get.call_count == 2

    @patch('wp_post.requests.get')
    def test_title_wrong_type_warns_but_still_produces_a_card(self, mock_get, wp, mock_response, capsys):
        payload = self._post_payload(title="Just a string")
        mock_get.return_value = mock_response(200, [payload])
        data = wp._resolve_bookmark("my-other-post")
        data_again = wp._resolve_bookmark("my-other-post")
        assert data is not None
        assert data["title"] == ""
        assert data == data_again
        assert mock_get.call_count == 1
        assert capsys.readouterr().err != ""

    @patch('wp_post.requests.get')
    def test_excerpt_none_warns_but_still_produces_a_card(self, mock_get, wp, mock_response, capsys):
        payload = self._post_payload(excerpt=None)
        mock_get.return_value = mock_response(200, [payload])
        data = wp._resolve_bookmark("my-other-post")
        data_again = wp._resolve_bookmark("my-other-post")
        assert data is not None
        assert data["excerpt"] == ""
        assert data == data_again
        assert mock_get.call_count == 1
        assert capsys.readouterr().err != ""

    @patch('wp_post.requests.get')
    def test_embedded_list_warns_but_still_produces_a_card(self, mock_get, wp, mock_response, capsys):
        payload = self._post_payload(_embedded=["not", "a", "dict"])
        mock_get.return_value = mock_response(200, [payload])
        data = wp._resolve_bookmark("my-other-post")
        data_again = wp._resolve_bookmark("my-other-post")
        assert data is not None
        assert data["image_url"] is None
        assert data == data_again
        assert mock_get.call_count == 1
        assert capsys.readouterr().err != ""

    @patch('wp_post.requests.get')
    def test_featuredmedia_dict_warns_but_still_produces_a_card(self, mock_get, wp, mock_response, capsys):
        payload = self._post_payload(
            _embedded={"wp:featuredmedia": {"id": 1, "source_url": "https://example.com/t.jpg"}}
        )
        mock_get.return_value = mock_response(200, [payload])
        data = wp._resolve_bookmark("my-other-post")
        data_again = wp._resolve_bookmark("my-other-post")
        assert data is not None
        assert data["image_url"] is None
        assert data == data_again
        assert mock_get.call_count == 1
        assert capsys.readouterr().err != ""

    @patch('wp_post.requests.get')
    def test_missing_excerpt_and_embedded_still_produces_a_usable_card(self, mock_get, wp, mock_response, capsys):
        payload = {
            "title": {"rendered": "My Other Post"},
            "link": "https://example.com/my-other-post/",
        }
        mock_get.return_value = mock_response(200, [payload])
        data = wp._resolve_bookmark("my-other-post")
        assert data["title"] == "My Other Post"
        assert data["excerpt"] == ""
        assert data["image_url"] is None
        assert data["image_id"] is None
        assert capsys.readouterr().err == ""


class TestCalloutWiring:
    def test_resolver_is_passed_to_the_converter(self, wp, md_file):
        path = md_file({"title": "T"}, "> [!BOOKMARK]\n> /x/")
        with patch.object(wp, '_resolve_bookmark', return_value=None) as resolver:
            wp.parse_markdown_file(path)
        resolver.assert_called_once_with("/x/")

    def test_resolution_disabled_makes_no_lookup(self, md_file):
        offline = wp_post.WordPressPost(
            "https://example.com", "u", "p", resolve_bookmarks=False
        )
        path = md_file({"title": "T"}, "> [!BOOKMARK]\n> /x/")
        with patch.object(offline, '_resolve_bookmark') as resolver:
            _, content = offline.parse_markdown_file(path)
        resolver.assert_not_called()
        assert '<a href="/x/">' in content

    def test_callout_config_reaches_the_converter(self, md_file):
        poster = wp_post.WordPressPost(
            "https://example.com", "u", "p",
            callout_config={"types": {"note": {"color": "primary"}}},
        )
        path = md_file({"title": "T"}, "> [!NOTE]\n> Body.")
        _, content = poster.parse_markdown_file(path)
        assert "var:preset|color|primary" in content


class TestSvgStrippingDetection:
    def test_warns_when_svg_missing_from_response(self, wp, capsys):
        sent = '<p><svg viewBox="0 0 16 16"></svg>Note</p>'
        post = {"content": {"rendered": "<p>Note</p>"}}
        assert wp._warn_if_svg_stripped(sent, post) is True
        assert "unfiltered_html" in capsys.readouterr().err

    def test_quiet_when_svg_survives(self, wp, capsys):
        sent = '<p><svg viewBox="0 0 16 16"></svg>Note</p>'
        post = {"content": {"rendered": '<p><svg viewBox="0 0 16 16"></svg>Note</p>'}}
        assert wp._warn_if_svg_stripped(sent, post) is False
        assert capsys.readouterr().err == ""

    def test_quiet_when_nothing_was_sent_with_svg(self, wp, capsys):
        post = {"content": {"rendered": "<p>Note</p>"}}
        assert wp._warn_if_svg_stripped("<p>Note</p>", post) is False
        assert capsys.readouterr().err == ""

    def test_quiet_when_rendered_content_is_absent(self, wp, capsys):
        sent = '<p><svg></svg>Note</p>'
        assert wp._warn_if_svg_stripped(sent, {}) is False
        assert wp._warn_if_svg_stripped(sent, {"content": {"rendered": ""}}) is False
        assert capsys.readouterr().err == ""


class TestNormalizePostDate:
    """WordPress rejects a bare date; it needs a time component (issue #19)."""

    def test_bare_date_gains_midnight(self):
        assert wp_post.normalize_post_date("2026-06-07") == "2026-06-07T00:00:00"

    def test_loose_iso_is_zero_padded(self):
        assert wp_post.normalize_post_date("2026-6-7") == "2026-06-07T00:00:00"

    def test_compact_date_is_expanded(self):
        assert wp_post.normalize_post_date("20260607") == "2026-06-07T00:00:00"

    def test_integer_compact_date(self):
        # YAML parses an unquoted 20260607 as an int, not a string.
        assert wp_post.normalize_post_date(20260607) == "2026-06-07T00:00:00"

    def test_datetime_with_t_is_untouched(self):
        assert wp_post.normalize_post_date("2026-06-07T09:30:00") == "2026-06-07T09:30:00"

    def test_datetime_with_space_is_untouched(self):
        # WordPress accepts a space separator, so don't rewrite it.
        assert wp_post.normalize_post_date("2026-06-07 09:30:00") == "2026-06-07 09:30:00"

    def test_timezone_offset_is_untouched(self):
        value = "2026-06-07T09:30:00+02:00"
        assert wp_post.normalize_post_date(value) == value

    def test_ambiguous_slash_format_passes_through_with_a_warning(self):
        warnings = []
        # 07/06/2026 is 7 June or 6 July depending on the reader, so guessing
        # would silently move the post by a month.
        assert wp_post.normalize_post_date("07/06/2026", warn=warnings.append) == "07/06/2026"
        assert len(warnings) == 1
        assert "YYYY-MM-DD" in warnings[0]

    def test_impossible_calendar_date_warns(self):
        warnings = []
        assert wp_post.normalize_post_date("2026-02-30", warn=warnings.append) == "2026-02-30"
        assert len(warnings) == 1

    def test_empty_value_is_left_alone(self):
        assert wp_post.normalize_post_date("") == ""


class TestTermLookupHandlesEntities:
    """REST returns names HTML-encoded; frontmatter carries plain text (issue #17)."""

    def _page(self, mock_response, items, total_pages=1):
        resp = mock_response(200, items)
        resp.headers = {"X-WP-TotalPages": str(total_pages)}
        return resp

    @patch('wp_post.requests.get')
    def test_encoded_name_is_matched_by_its_plain_text(self, mock_get, wp, mock_response):
        mock_get.return_value = self._page(mock_response, [
            {"id": 88, "name": "Security &amp; Compliance", "slug": "security-compliance"},
        ])
        cats = wp.get_categories()
        assert cats["Security & Compliance"] == 88
        assert cats["security-compliance"] == 88

    @patch('wp_post.requests.get')
    def test_pagination_is_followed(self, mock_get, wp, mock_response):
        mock_get.side_effect = [
            self._page(mock_response, [{"id": 1, "name": "One", "slug": "one"}], total_pages=2),
            self._page(mock_response, [{"id": 2, "name": "Two", "slug": "two"}], total_pages=2),
        ]
        cats = wp.get_categories()
        assert cats["One"] == 1 and cats["Two"] == 2

    @patch('wp_post.requests.get')
    def test_malformed_batch_does_not_raise(self, mock_get, wp, mock_response):
        mock_get.return_value = self._page(mock_response, {"code": "rest_no_route"})
        assert wp.get_categories() == {}


class TestTermCreationReusesExisting:
    @patch('wp_post.requests.post')
    def test_term_exists_returns_the_existing_id(self, mock_post, wp, mock_response):
        mock_post.return_value = mock_response(400, {
            "code": "term_exists",
            "message": "A term with the name provided already exists with this parent.",
            "data": {"status": 400, "term_id": 88},
        })
        assert wp.create_category("Security & Compliance") == 88

    @patch('wp_post.requests.post')
    def test_other_failures_warn_instead_of_vanishing(self, mock_post, wp, mock_response, capsys):
        mock_post.return_value = mock_response(403, {
            "code": "rest_cannot_create", "message": "Sorry, you are not allowed.",
        })
        assert wp.create_tag("Anything") is None
        err = capsys.readouterr().err
        assert "Could not assign tag 'Anything'" in err
        assert "not allowed" in err

    @patch('wp_post.requests.post')
    def test_success_returns_the_new_id(self, mock_post, wp, mock_response):
        mock_post.return_value = mock_response(201, {"id": 42})
        assert wp.create_category("Brand New") == 42


class TestBookmarkSlugCaseFolding:
    """WordPress lowercases slugs on creation, so targets must fold (#21)."""

    def test_title_capitalisation_is_folded(self, wp):
        assert wp._bookmark_slug("/My-Post/") == "my-post"

    def test_full_url_is_folded(self, wp):
        assert wp._bookmark_slug("https://example.com/My-Post/") == "my-post"

    def test_already_lowercase_is_unchanged(self, wp):
        assert wp._bookmark_slug("/my-post/") == "my-post"

    def test_percent_encoded_slug_is_left_alone(self, wp):
        # WordPress encodes non-Latin slugs with uppercase hex; folding
        # would turn a working lookup into a miss.
        assert wp._bookmark_slug("/%E3%81%82/") == "%E3%81%82"

    def test_empty_and_slash_only_targets(self, wp):
        assert wp._bookmark_slug("") is None
        assert wp._bookmark_slug("///") is None

    @patch('wp_post.requests.get')
    def test_uppercase_target_queries_the_folded_slug(self, mock_get, wp, mock_response):
        mock_get.return_value = mock_response(200, [{
            "title": {"rendered": "My Post"},
            "link": "https://example.com/my-post/",
            "excerpt": {"rendered": "<p>Excerpt.</p>"},
        }])
        data = wp._resolve_bookmark("/My-Post/")
        assert data["title"] == "My Post"
        assert mock_get.call_args.kwargs["params"]["slug"] == "my-post"
        assert mock_get.call_count == 1


class TestResolveLocaleForFile:
    def _network_project(self, tmp_path):
        (tmp_path / "content" / "de").mkdir(parents=True)
        (tmp_path / "content" / "en").mkdir(parents=True)
        (tmp_path / ".wp-poster.json").write_text(json.dumps({
            "network": {"sites": {
                "en": {"content_path": "content/en", "site_url": "https://e.com",
                       "locale": "en_US", "blog_id": 1},
                "de": {"content_path": "content/de", "site_url": "https://e.com/de",
                       "locale": "de_DE", "blog_id": 3},
            }}
        }))
        return tmp_path

    def test_file_under_a_site_takes_that_sites_locale(self, tmp_path):
        root = self._network_project(tmp_path)
        article = root / "content" / "de" / "artikel.md"
        article.write_text("# Titel\n")
        assert resolve_locale_for_file(str(article)) == "de_DE"

    def test_sibling_site_takes_its_own_locale(self, tmp_path):
        root = self._network_project(tmp_path)
        article = root / "content" / "en" / "article.md"
        article.write_text("# Title\n")
        assert resolve_locale_for_file(str(article)) == "en_US"

    def test_file_outside_every_content_path_is_none(self, tmp_path):
        root = self._network_project(tmp_path)
        stray = root / "notes.md"
        stray.write_text("# Notes\n")
        assert resolve_locale_for_file(str(stray)) is None

    def test_project_without_a_network_config_is_none(self, tmp_path):
        article = tmp_path / "post.md"
        article.write_text("# Title\n")
        assert resolve_locale_for_file(str(article)) is None

    def test_malformed_discovery_data_warns_and_falls_back(self, tmp_path, capsys):
        # Locale discovery runs unconditionally and under --test, so it must
        # degrade to English rather than abort a publish that used to work.
        # find_network_config json.loads without a guard; find_site_for_file
        # indexes site_info['content_path'] directly.
        (tmp_path / "content").mkdir()
        (tmp_path / ".wp-poster.json").write_text('{"network": {')
        article = tmp_path / "content" / "post.md"
        article.write_text("# Title\n")
        assert resolve_locale_for_file(str(article)) is None
        assert "site language" in capsys.readouterr().err


class TestPosterCarriesLocale:
    def test_locale_defaults_to_none(self):
        poster = WordPressPost("https://e.com", "u", "p")
        assert poster._locale is None

    def test_german_locale_produces_german_callout_labels(self, tmp_path):
        article = tmp_path / "artikel.md"
        article.write_text("---\ntitle: Titel\n---\n\n> [!WARNING]\n> Vorsicht.\n")
        poster = WordPressPost("https://e.com", "u", "p",
                               resolve_bookmarks=False, locale="de_DE")
        _, blocks = poster.parse_markdown_file(str(article))
        assert "Warnung</strong>" in blocks

    def test_no_locale_produces_english_callout_labels(self, tmp_path):
        article = tmp_path / "post.md"
        article.write_text("---\ntitle: Title\n---\n\n> [!WARNING]\n> Careful.\n")
        poster = WordPressPost("https://e.com", "u", "p", resolve_bookmarks=False)
        _, blocks = poster.parse_markdown_file(str(article))
        assert "Warning</strong>" in blocks


class TestTestModeLocale:
    def _german_project(self, tmp_path):
        (tmp_path / "content" / "de").mkdir(parents=True)
        (tmp_path / ".wp-poster.json").write_text(json.dumps({
            "network": {"sites": {
                "de": {"content_path": "content/de", "site_url": "https://e.com/de",
                       "locale": "de_DE", "blog_id": 3},
            }}
        }))
        article = tmp_path / "content" / "de" / "artikel.md"
        article.write_text("---\ntitle: Titel\n---\n\n> [!WARNING]\n> Vorsicht.\n")
        return article

    def test_test_mode_previews_the_sites_language(self, tmp_path, capsys):
        # Drives main() end to end: this is the only test that proves the
        # CLI wires the locale in. Constructing a WordPressPost by hand
        # here would pass even with the wiring deleted.
        article = self._german_project(tmp_path)
        argv = ["wp-post", str(article), "--test", "--markdown"]
        with patch.object(sys, "argv", argv):
            with pytest.raises(SystemExit) as exc:
                wp_post.main()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Warnung</strong>" in out
        assert "Warning</strong>" not in out

    def test_test_mode_outside_a_network_project_previews_english(self, tmp_path, capsys):
        article = tmp_path / "post.md"
        article.write_text("---\ntitle: Title\n---\n\n> [!WARNING]\n> Careful.\n")
        argv = ["wp-post", str(article), "--test", "--markdown"]
        with patch.object(sys, "argv", argv):
            with pytest.raises(SystemExit) as exc:
                wp_post.main()
        assert exc.value.code == 0
        assert "Warning</strong>" in capsys.readouterr().out


class TestPhpSerialize:
    """Pins the phpserialize contract wp-post relies on for schema meta."""

    def test_dict_round_trip(self):
        import phpserialize
        data = {"@type": "HowTo", "name": "Test"}
        serialised = phpserialize.dumps(data).decode("utf-8")
        assert serialised.startswith("a:2:")
        loaded = phpserialize.loads(serialised.encode("utf-8"), decode_strings=True)
        assert loaded == data

    def test_nested_list_serialises_as_php_indexed_array(self):
        # PHP has no distinct list type; Python lists serialise as PHP arrays
        # with integer keys 0..N-1. This is what Rank Math's unserialize() will
        # decode back into an indexed PHP array on the server side - exactly
        # what HowTo's `step` field expects. The Python round-trip via
        # phpserialize.loads returns those as numeric-keyed dicts (there is no
        # ambiguity in the serialised form to distinguish list from dict), so
        # we pin on the serialised string plus the round-tripped dict shape.
        import phpserialize
        data = {
            "@type": "HowTo",
            "step": [
                {"@type": "HowToStep", "text": "First"},
                {"@type": "HowToStep", "text": "Second"},
            ],
        }
        serialised = phpserialize.dumps(data).decode("utf-8")
        # step is an a:2 array with i:0 / i:1 numeric keys - indexed, not hash.
        assert 'a:2:{s:5:"@type";s:5:"HowTo";s:4:"step";a:2:{i:0;' in serialised
        assert '"First"' in serialised
        assert '"Second"' in serialised
        loaded = phpserialize.loads(serialised.encode("utf-8"), decode_strings=True)
        assert loaded == {
            "@type": "HowTo",
            "step": {
                0: {"@type": "HowToStep", "text": "First"},
                1: {"@type": "HowToStep", "text": "Second"},
            },
        }

    def test_unicode_survives(self):
        import phpserialize
        data = {"description": "So senden Sie ein PDF per Fax."}
        serialised = phpserialize.dumps(data).decode("utf-8")
        loaded = phpserialize.loads(serialised.encode("utf-8"), decode_strings=True)
        assert loaded == data


class TestUpdateRankmathSchemas:
    """Direct tests for the update_rankmath_schemas method (issue #24)."""

    @patch("wp_post.requests.post")
    def test_empty_dict_no_request(self, mock_post, wp):
        result = wp.update_rankmath_schemas(1, {})
        mock_post.assert_not_called()
        assert result is None

    @patch("wp_post.requests.post")
    def test_single_schema_written(self, mock_post, wp, mock_response):
        import phpserialize
        mock_post.return_value = mock_response(200)
        schema = {"@type": "HowTo", "name": "Test"}
        result = wp.update_rankmath_schemas(1, {"HowTo": schema})
        assert result is None
        assert mock_post.call_count == 1
        url = mock_post.call_args[0][0]
        assert url.endswith("/wp-json/rankmath/v1/updateMeta")
        payload = mock_post.call_args[1]["json"]
        assert payload["objectType"] == "post"
        assert payload["objectID"] == 1
        expected = phpserialize.dumps(schema).decode("utf-8")
        assert payload["meta"]["rank_math_schema_HowTo"] == expected

    @patch("wp_post.requests.post")
    def test_multiple_schemas_one_post(self, mock_post, wp, mock_response):
        mock_post.return_value = mock_response(200)
        result = wp.update_rankmath_schemas(1, {
            "HowTo": {"@type": "HowTo"},
            "Recipe": {"@type": "Recipe"},
        })
        assert result is None
        assert mock_post.call_count == 1
        payload = mock_post.call_args[1]["json"]
        assert "rank_math_schema_HowTo" in payload["meta"]
        assert "rank_math_schema_Recipe" in payload["meta"]

    @patch("wp_post.requests.post")
    def test_type_key_case_preserved(self, mock_post, wp, mock_response):
        mock_post.return_value = mock_response(200)
        wp.update_rankmath_schemas(1, {"HowTo": {"@type": "HowTo"}})
        payload = mock_post.call_args[1]["json"]
        assert "rank_math_schema_HowTo" in payload["meta"]
        assert "rank_math_schema_howto" not in payload["meta"]

    @patch("wp_post.requests.post")
    def test_http_failure_returns_failure_dict(self, mock_post, wp, mock_response):
        mock_post.return_value = mock_response(400, text="Bad Request")
        result = wp.update_rankmath_schemas(1, {"HowTo": {"@type": "HowTo"}})
        assert result is not None
        assert result["status_code"] == 400
        assert "Bad Request" in result["error"]
        assert result["types"] == ["HowTo"]

    @patch("wp_post.requests.post")
    def test_exception_returns_failure_dict(self, mock_post, wp):
        import requests as _requests
        mock_post.side_effect = _requests.RequestException("boom")
        result = wp.update_rankmath_schemas(1, {"HowTo": {"@type": "HowTo"}})
        assert result is not None
        assert "boom" in result["error"]
        assert result["types"] == ["HowTo"]
        assert "status_code" not in result
