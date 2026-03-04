"""Tests for wp-post.py — WordPressPost class and standalone functions."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest
import yaml

wp_post = sys.modules["wp_post"]
WordPressPost = wp_post.WordPressPost
resolve_format = wp_post.resolve_format
find_network_config = wp_post.find_network_config
find_translation_siblings = wp_post.find_translation_siblings
write_msls_links = wp_post.write_msls_links
init_network_config = wp_post.init_network_config


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
# 6. Network / MSLS translation support
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


class TestWriteMslsLinks:
    @patch("wp_post.subprocess.run")
    def test_two_member_set(self, mock_run):
        current = {'locale': 'en_US', 'blog_id': 1, 'post_id': 10}
        siblings = [{'locale': 'es_ES', 'blog_id': 2, 'post_id': 20}]

        write_msls_links('@test', current, siblings)

        assert mock_run.call_count == 2
        # Check that both members get an option written
        calls = mock_run.call_args_list
        cmd0 = calls[0][0][0]  # first call args
        cmd1 = calls[1][0][0]

        # en member should get es sibling
        assert 'msls_10' in cmd0[3]
        assert '"es_ES": 20' in cmd0[3]
        # es member should get en sibling
        assert 'msls_20' in cmd1[3]
        assert '"en_US": 10' in cmd1[3]

    @patch("wp_post.subprocess.run")
    def test_three_member_set(self, mock_run):
        current = {'locale': 'en_US', 'blog_id': 1, 'post_id': 10}
        siblings = [
            {'locale': 'es_ES', 'blog_id': 2, 'post_id': 20},
            {'locale': 'de_DE', 'blog_id': 3, 'post_id': 30},
        ]

        write_msls_links('@test', current, siblings)

        assert mock_run.call_count == 3
        # Each member should list the other two
        for i, member in enumerate([current] + siblings):
            cmd = mock_run.call_args_list[i][0][0]
            assert f'msls_{member["post_id"]}' in cmd[3]

    @patch("wp_post.subprocess.run")
    def test_mesh_includes_all_members(self, mock_run):
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
    def test_no_msls_linking_on_update(self, mock_get, mock_post, mock_subproc, tmp_path, mock_response):
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
        mock_post.return_value = mock_response(200, {
            'id': 50, 'link': 'https://en.example.com/about/', 'title': {'rendered': 'About'},
        })

        wp.post_to_wordpress(str(update_post), raw=True)
        mock_subproc.assert_not_called()

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

        # Check root config
        with open(tmp_path / '.wp-poster.json') as f:
            root_config = json.load(f)
        assert root_config['network']['wp_cli_alias'] == '@testsite'
        assert 'en' in root_config['network']['sites']
        assert 'es' in root_config['network']['sites']

        # Check per-site configs
        with open(tmp_path / 'en' / '.wp-poster.json') as f:
            en_config = json.load(f)
        assert en_config['site_url'] == 'https://en.example.com'
        assert en_config['locale'] == 'en_US'
        assert en_config['blog_id'] == 1

        with open(tmp_path / 'es' / '.wp-poster.json') as f:
            es_config = json.load(f)
        assert es_config['locale'] == 'es_ES'
        assert es_config['blog_id'] == 2

        # Check content directories exist
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
