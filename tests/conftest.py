"""Shared fixtures for wp-poster test suite."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Import wp-post.py (hyphenated filename) as "wp_post" so patches like
# @patch('wp_post.requests.get') resolve correctly.
# ---------------------------------------------------------------------------
_WP_POST_PATH = Path(__file__).resolve().parent.parent / "wp-post.py"

spec = importlib.util.spec_from_file_location("wp_post", _WP_POST_PATH)
wp_post = importlib.util.module_from_spec(spec)
sys.modules["wp_post"] = wp_post
spec.loader.exec_module(wp_post)

from gutenberg import GutenbergConverter  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def wp():
    """A WordPressPost instance pointed at a dummy site."""
    return wp_post.WordPressPost("https://example.com", "user", "pass")


@pytest.fixture
def converter():
    """A GutenbergConverter with a passthrough image handler."""
    return GutenbergConverter(image_handler=lambda url: (url, None))


@pytest.fixture
def md_file(tmp_path):
    """Factory that writes a temp markdown file from frontmatter dict + body string.

    Usage:
        path = md_file({"title": "Hello"}, "body text")
    """
    def _make(frontmatter: dict | None = None, body: str = ""):
        import yaml

        parts = []
        if frontmatter is not None:
            parts.append("---")
            parts.append(yaml.dump(frontmatter, default_flow_style=False).rstrip())
            parts.append("---")
        if body:
            parts.append(body)
        content = "\n".join(parts)
        filepath = tmp_path / "test_post.md"
        filepath.write_text(content, encoding="utf-8")
        return str(filepath)
    return _make


@pytest.fixture
def mock_response():
    """Factory returning a mock requests.Response with configurable status_code and json.

    Usage:
        resp = mock_response(201, {"id": 1, "link": "...", "title": {"rendered": "T"}})
    """
    def _make(status_code=200, json_data=None, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data if json_data is not None else {}
        resp.text = text
        return resp
    return _make
