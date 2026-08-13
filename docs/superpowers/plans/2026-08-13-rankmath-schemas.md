# Rank Math Schema Frontmatter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `wp-post` publishes JSON-LD rich-snippet schemas (HowTo, Recipe, Product, etc.) by writing PHP-serialised `rank_math_schema_<Type>` post_meta rows from a `rankmath.schemas` frontmatter block, via Rank Math's existing `updateMeta` REST endpoint.

**Architecture:** No site-side plugin. `wp-post.py` gains a new method `update_rankmath_schemas(post_id, schemas)` that PHP-serialises each schema dict with the `phpserialize` package and writes it as `rank_math_schema_<Type>` via a single POST to `/wp-json/rankmath/v1/updateMeta`. The `schemas` sub-key is `.pop`'d from the rankmath frontmatter block before the existing scalar-meta pass so it isn't coerced into a `rank_math_schemas` string. Upsert per type; no delete-orphan. Failure surfaces through the return payload as `schema_failure`, mirroring `msls_failures`.

**Tech Stack:** Python 3, `requests`, `phpserialize`, pytest.

**Spec:** GitHub issue [ediblesites/wp-poster#24](https://github.com/ediblesites/wp-poster/issues/24)

## Global Constraints

- Route: `POST {site_url}/wp-json/rankmath/v1/updateMeta`. Existing helper at `wp-post.py:894`; new schema writes use the same endpoint.
- Meta key format: `rank_math_schema_<Type>`. The `<Type>` is the frontmatter dict key verbatim (typically CamelCase: `HowTo`, `Recipe`, `Product`). WordPress meta keys are case-sensitive; the user's frontmatter case is preserved.
- Meta value: `phpserialize.dumps(schema_dict).decode('utf-8')`.
- `schemas` key present + populated dict = write; empty dict `{}` = no-op; absent = no-op. Gating on key presence at the frontmatter layer, on `bool(schemas_dict)` at the call site.
- No delete-orphan semantics. Removing a schema type is a manual wp-admin operation.
- Legacy keys warn + drop (do not map): `rich_snippet`, `snippet_howto_type`, `snippet_howto_name`, `snippet_howto_desc`. One-line per-key warning to stderr in the tool's existing `⚠ ...` format (see `wp-post.py:78`).
- Schema-write failure never fails the publish. Warn to stderr, surface the failure through the return dict as `schema_failure` (single dict, since it is one API call).
- Warning format: `print(f"⚠ {msg}", file=sys.stderr)`.
- Run tests with `python3 -m pytest` from the repo root. Baseline before this work: 418 passing.
- Work happens on a `rankmath-schemas` branch off `master`.
- Source file is `wp-post.py` at the repo root; there is no `src/` directory.
- The `/wp-post` skill is installed per-project by `install.sh` and copies (not symlinks) `skills/wp-post/` into `.claude/skills/wp-post/`. Documentation changes in `skills/wp-post/references/frontmatter.md` do not reach any installed copy until `install.sh` is re-run in that project.

---

### Task 1: Live verification of updateMeta contract

Gate for the rest of the plan. Rank Math's `updateMeta` route is documented as accepting Rank Math's shorthand meta keys (`rank_math_title`, `rank_math_description`, `rank_math_focus_keyword`). The plan assumes it also accepts arbitrary `rank_math_schema_<Type>` keys and stores them via `update_post_meta()`. If it whitelists, we cannot use `updateMeta` for schemas and have to fall back to `/updateSchemas` (which appends via `add_metadata()`, losing upsert per type and requiring a delete-first workaround).

This task is a manual live curl against a real Rank-Math-installed site. Do it before any code changes.

**Files:** none.

**Interfaces:** none.

- [ ] **Step 1: Pick a test post on a Rank-Math-installed site**

Any published post on a site where you have an Application Password for a user with `edit_post` on that post plus `onpage_snippet`. Note the post_id.

- [ ] **Step 2: POST a probe schema key to updateMeta**

Substitute `<SITE>`, `<USER>`, `<APP_PASS>`, `<POST_ID>`.

```bash
curl -s -u '<USER>:<APP_PASS>' \
  -H 'Content-Type: application/json' \
  -X POST 'https://<SITE>/wp-json/rankmath/v1/updateMeta' \
  -d '{
    "objectType": "post",
    "objectID": <POST_ID>,
    "meta": {
      "rank_math_schema_ProbeType": "a:1:{s:5:\"@type\";s:9:\"ProbeType\";}"
    }
  }'
```

Expected on success: `{"success":true}` or similar 200 response with no error field.

- [ ] **Step 3: Verify the row exists**

```bash
curl -s -u '<USER>:<APP_PASS>' \
  'https://<SITE>/wp-json/wp/v2/posts/<POST_ID>?context=edit' \
  | python3 -c 'import json,sys; p=json.load(sys.stdin); print(p.get("meta"))'
```

Or, if `rank_math_schema_*` isn't registered for REST exposure, SSH to the box and:

```bash
wp post meta get <POST_ID> rank_math_schema_ProbeType
```

Expected: the PHP-serialised value `a:1:{s:5:"@type";s:9:"ProbeType";}`.

- [ ] **Step 4: Clean up the probe row**

```bash
wp post meta delete <POST_ID> rank_math_schema_ProbeType
```

Or write an empty value back via the same curl.

- [ ] **Step 5: Record the outcome and proceed or escalate**

If steps 2 and 3 both succeeded: proceed to Task 2 as planned.

If step 2 returned an error or step 3 showed the row wasn't written: stop, escalate to the user. The rest of the plan needs to be redesigned around `/updateSchemas` (append-only) plus a delete-first strategy that requires SSH / wp-cli access, or a different write mechanism entirely. Do not proceed silently.

- [ ] **Step 6: Create the branch**

```bash
git checkout -b rankmath-schemas
```

No commit yet.

---

### Task 2: Add phpserialize dependency

Purely a dependency addition, with a smoke test that pins the round-trip behaviour we rely on (nested dicts, lists, unicode).

**Files:**
- Modify: `requirements.txt`
- Test: `tests/test_wp_post.py` (append new class)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `phpserialize` is importable from any module.
  - The plan relies on `phpserialize.dumps(dict).decode('utf-8')` producing a valid PHP-serialised string suitable as the `meta` value in an updateMeta payload.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wp_post.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_wp_post.py::TestPhpSerialize -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'phpserialize'`.

- [ ] **Step 3: Add phpserialize to requirements.txt**

Edit `requirements.txt` to add a line after the existing entries:

```
phpserialize>=1.3
```

The full file becomes:

```
requests>=2.31.0
PyYAML>=6.0
mistune>=3.2.0
pytest>=7.0
phpserialize>=1.3
```

- [ ] **Step 4: Install the new dependency**

```bash
pip install -r requirements.txt
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_wp_post.py::TestPhpSerialize -v`
Expected: 3 PASS.

- [ ] **Step 6: Run the full suite to make sure nothing else broke**

Run: `python3 -m pytest -q`
Expected: 421 passing (418 baseline + 3 new).

- [ ] **Step 7: Commit**

```bash
git add requirements.txt tests/test_wp_post.py
git commit -m "Add phpserialize dependency for Rank Math schema writes"
```

---

### Task 3: `update_rankmath_schemas` method

Add the new writer method in isolation, tested directly. Later tasks wire it into the publish flow.

**Files:**
- Modify: `wp-post.py` (add method inside `WordPressPost` class, near `update_rankmath_meta` at line 868)
- Test: `tests/test_wp_post.py` (append new class)

**Interfaces:**
- Consumes: nothing new; uses `self.site_url`, `self.auth`, `phpserialize.dumps`.
- Produces:
  - `WordPressPost.update_rankmath_schemas(post_id: int, schemas: dict, verbose: bool = False) -> dict | None`
  - Returns `None` on success or when `schemas` is empty (no-op).
  - Returns `{"status_code": int, "error": str, "types": list[str]}` on HTTP failure.
  - Returns `{"error": str, "types": list[str]}` on request exception (no status_code).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_post.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_wp_post.py::TestUpdateRankmathSchemas -v`
Expected: FAIL with `AttributeError: 'WordPressPost' object has no attribute 'update_rankmath_schemas'`.

- [ ] **Step 3: Add the method to WordPressPost**

Insert into `wp-post.py` immediately after `update_rankmath_meta` (which ends at line 912). Add `import phpserialize` at the top of the file, next to the existing `import requests` (around line 3-6).

```python
    def update_rankmath_schemas(self, post_id, schemas, verbose=False):
        """Write PHP-serialised rank_math_schema_<Type> meta via Rank Math updateMeta.

        Each key in `schemas` becomes a `rank_math_schema_<key>` post_meta row,
        with the value PHP-serialised so Rank Math's schema module reads it back
        into JSON-LD on render. Uses update_post_meta upsert semantics: an
        existing row for the same type is replaced. Types not listed in `schemas`
        are left alone; there is no delete-orphan pass (no REST route enumerates
        existing schema meta_ids). See issue #24.

        Args:
            post_id: WordPress post ID.
            schemas: {Type: dict} mapping. Empty dict is a no-op.

        Returns:
            None on success or when schemas is empty.
            On HTTP failure: {"status_code": int, "error": str, "types": [str]}.
            On request exception: {"error": str, "types": [str]}.
        """
        if not schemas:
            return None

        meta = {
            f"rank_math_schema_{type_name}": phpserialize.dumps(schema_body).decode("utf-8")
            for type_name, schema_body in schemas.items()
        }
        payload = {
            "objectType": "post",
            "objectID": post_id,
            "meta": meta,
        }
        url = f"{self.site_url}/wp-json/rankmath/v1/updateMeta"

        if verbose:
            print(f"[verbose] Rank Math schemas: POST {url}")
            print(f"[verbose] Types: {sorted(schemas.keys())}")

        types = sorted(schemas.keys())
        try:
            resp = requests.post(url, auth=self.auth, json=payload, timeout=15)
            if resp.status_code == 200:
                print(f"✓ Rank Math schemas written: {', '.join(types)}")
                return None
            print(
                f"⚠ Rank Math schema write failed: {resp.status_code} - {resp.text}",
                file=sys.stderr,
            )
            return {
                "status_code": resp.status_code,
                "error": resp.text,
                "types": types,
            }
        except requests.RequestException as e:
            print(f"⚠ Rank Math schema write error: {e}", file=sys.stderr)
            return {"error": str(e), "types": types}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_wp_post.py::TestUpdateRankmathSchemas -v`
Expected: 6 PASS.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 427 passing (421 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Add update_rankmath_schemas: write PHP-serialised schema meta via updateMeta"
```

---

### Task 4: Wire schema writes into the publish flow

Extract `schemas` from the rankmath frontmatter block before the existing scalar-meta pass, call `update_rankmath_schemas`, and surface any failure through the returned result dict.

**Files:**
- Modify: `wp-post.py:813-827` (the block that builds `rankmath_meta` and calls `update_rankmath_meta`)
- Modify: `wp-post.py:842-852` (the result-dict construction)
- Test: `tests/test_wp_post.py` (append new class in the `TestPostRankMath` region)

**Interfaces:**
- Consumes: `update_rankmath_schemas` from Task 3.
- Produces:
  - `frontmatter.rankmath.schemas` handled at publish time.
  - `result['schema_failure']` set when the schema write returns a failure dict.
  - `rank_math_schemas` never appears as a scalar meta key (proves the `.pop` works).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_post.py`:

```python
class TestRankmathSchemasFrontmatter:
    """rankmath.schemas frontmatter -> rank_math_schema_<Type> meta (issue #24)."""

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_absent_schemas_no_schema_call(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file(
            {"title": "T", "rankmath": {"title": "SEO"}},
            "body",
        )
        mock_post.side_effect = [
            mock_response(201, {"id": 30, "link": "https://example.com/?p=30",
                                "title": {"rendered": "T"}}),
            mock_response(200),  # scalar rankmath updateMeta
        ]
        result = wp.post_to_wordpress(path, raw=True)
        assert result["success"] is True
        # Exactly one rankmath call (scalar); no second schemas call.
        rm_calls = [c for c in mock_post.call_args_list if "rankmath" in c[0][0]]
        assert len(rm_calls) == 1
        assert "rank_math_schema_HowTo" not in rm_calls[0][1]["json"]["meta"]

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_empty_schemas_dict_no_schema_call(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file(
            {"title": "T", "rankmath": {"title": "SEO", "schemas": {}}},
            "body",
        )
        mock_post.side_effect = [
            mock_response(201, {"id": 31, "link": "https://example.com/?p=31",
                                "title": {"rendered": "T"}}),
            mock_response(200),
        ]
        result = wp.post_to_wordpress(path, raw=True)
        assert result["success"] is True
        rm_calls = [c for c in mock_post.call_args_list if "rankmath" in c[0][0]]
        assert len(rm_calls) == 1
        # Also: scalar call must not have leaked a rank_math_schemas key.
        assert "rank_math_schemas" not in rm_calls[0][1]["json"]["meta"]

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_populated_schemas_written_after_scalar_meta(self, mock_get, mock_post, wp, md_file, mock_response):
        import phpserialize
        howto = {"@type": "HowTo", "name": "How"}
        path = md_file(
            {"title": "T", "rankmath": {"title": "SEO", "schemas": {"HowTo": howto}}},
            "body",
        )
        mock_post.side_effect = [
            mock_response(201, {"id": 32, "link": "https://example.com/?p=32",
                                "title": {"rendered": "T"}}),
            mock_response(200),  # scalar
            mock_response(200),  # schemas
        ]
        result = wp.post_to_wordpress(path, raw=True)
        assert result["success"] is True
        assert "schema_failure" not in result
        rm_calls = [c for c in mock_post.call_args_list if "rankmath" in c[0][0]]
        assert len(rm_calls) == 2
        scalar_meta = rm_calls[0][1]["json"]["meta"]
        assert "rank_math_schemas" not in scalar_meta  # .pop worked
        schema_meta = rm_calls[1][1]["json"]["meta"]
        assert schema_meta["rank_math_schema_HowTo"] == \
               phpserialize.dumps(howto).decode("utf-8")

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_schemas_only_no_scalar_meta(self, mock_get, mock_post, wp, md_file, mock_response):
        """A schemas-only rankmath block still triggers the schema call, even
        though the scalar-meta call is skipped (no scalar keys left)."""
        path = md_file(
            {"title": "T", "rankmath": {"schemas": {"HowTo": {"@type": "HowTo"}}}},
            "body",
        )
        mock_post.side_effect = [
            mock_response(201, {"id": 33, "link": "https://example.com/?p=33",
                                "title": {"rendered": "T"}}),
            mock_response(200),  # schemas
        ]
        result = wp.post_to_wordpress(path, raw=True)
        assert result["success"] is True
        rm_calls = [c for c in mock_post.call_args_list if "rankmath" in c[0][0]]
        assert len(rm_calls) == 1
        assert "rank_math_schema_HowTo" in rm_calls[0][1]["json"]["meta"]

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_schema_failure_surfaced_via_result(self, mock_get, mock_post, wp, md_file, mock_response):
        path = md_file(
            {"title": "T", "rankmath": {"schemas": {"HowTo": {"@type": "HowTo"}}}},
            "body",
        )
        mock_post.side_effect = [
            mock_response(201, {"id": 34, "link": "https://example.com/?p=34",
                                "title": {"rendered": "T"}}),
            mock_response(400, text="rejected"),  # schemas call fails
        ]
        result = wp.post_to_wordpress(path, raw=True)
        # Publish still succeeds; schema failure surfaces separately.
        assert result["success"] is True
        assert "schema_failure" in result
        assert result["schema_failure"]["status_code"] == 400
        assert result["schema_failure"]["types"] == ["HowTo"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_wp_post.py::TestRankmathSchemasFrontmatter -v`
Expected: FAILs (schemas leaks into scalar meta call, no schema call is made, no `schema_failure` key on result).

- [ ] **Step 3: Rewrite the publish-flow block**

Replace `wp-post.py:813-827`:

```python
            # Handle Rank Math SEO meta via dedicated API.
            rankmath_meta = dict(frontmatter.get('rankmath', {}))
            # Reconcile rank_math_description to the excerpt so an excerpt change
            # can't leave a stale SEO description live (issue #13). An explicit
            # rankmath.description always wins; an empty/absent excerpt leaves
            # the override untouched. Under this tool's local-first model a
            # divergent wp-admin override is treated as drift and overwritten.
            excerpt = (frontmatter.get('excerpt') or '').strip()
            has_explicit_description = (
                'description' in rankmath_meta or 'rank_math_description' in rankmath_meta
            )
            if excerpt and not has_explicit_description:
                rankmath_meta['description'] = excerpt
            if rankmath_meta:
                self.update_rankmath_meta(post_id, rankmath_meta, verbose=verbose)
```

with:

```python
            # Handle Rank Math SEO meta via dedicated API.
            rankmath_meta = dict(frontmatter.get('rankmath', {}))
            # rankmath.schemas is a nested dict of PHP-serialised schema bodies;
            # pop it out before the scalar-meta pass so it isn't coerced into a
            # rank_math_schemas string. See issue #24.
            schemas = rankmath_meta.pop('schemas', None)
            # Reconcile rank_math_description to the excerpt so an excerpt change
            # can't leave a stale SEO description live (issue #13). An explicit
            # rankmath.description always wins; an empty/absent excerpt leaves
            # the override untouched. Under this tool's local-first model a
            # divergent wp-admin override is treated as drift and overwritten.
            excerpt = (frontmatter.get('excerpt') or '').strip()
            has_explicit_description = (
                'description' in rankmath_meta or 'rank_math_description' in rankmath_meta
            )
            if excerpt and not has_explicit_description:
                rankmath_meta['description'] = excerpt
            if rankmath_meta:
                self.update_rankmath_meta(post_id, rankmath_meta, verbose=verbose)
            # Schema write. Absent (None) or empty ({}) = no-op; populated dict
            # is written per-type via updateMeta. Failures do not fail the
            # publish; they surface through result['schema_failure'].
            schema_failure = None
            if schemas:
                schema_failure = self.update_rankmath_schemas(post_id, schemas, verbose=verbose)
```

- [ ] **Step 4: Wire the failure into the result dict**

Replace `wp-post.py:842-852` (before this task's changes, the range is `842-852`; after Step 3 the numbers have shifted, so locate by content):

Find the block:

```python
            result = {
                'success': True,
                'id': post_id,
                'url': post['link'],
                'title': post['title']['rendered']
            }
            # The post is already live; MSLS linking failures are surfaced
            # separately so they aren't masked as a clean success (issue #11).
            if msls_failures:
                result['msls_failures'] = msls_failures
            return result
```

Replace with:

```python
            result = {
                'success': True,
                'id': post_id,
                'url': post['link'],
                'title': post['title']['rendered']
            }
            # The post is already live; MSLS linking failures are surfaced
            # separately so they aren't masked as a clean success (issue #11).
            if msls_failures:
                result['msls_failures'] = msls_failures
            # Same reasoning for schema-write failures (issue #24).
            if schema_failure:
                result['schema_failure'] = schema_failure
            return result
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `python3 -m pytest tests/test_wp_post.py::TestRankmathSchemasFrontmatter -v`
Expected: 5 PASS.

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `python3 -m pytest -q`
Expected: 432 passing (427 + 5 new). Pay attention to existing `TestPostRankMath`, `TestExcerptRankMathReconcile`, `TestUpdateRankmathMeta` classes: none of them should have broken.

- [ ] **Step 7: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Publish rankmath.schemas frontmatter as rank_math_schema_* meta"
```

---

### Task 5: Warn and drop legacy rich-snippet keys

Emit a one-line stderr warning for each of the four named legacy keys and drop them from the outgoing rankmath meta so they don't reach `update_rankmath_meta`. Silent mapping onto the new endpoint would hide the migration, and a broader "unknown rankmath key" warning would trip on future Rank Math additions.

**Files:**
- Modify: `wp-post.py` in the block edited in Task 4 (after the `pop('schemas')`, before the excerpt reconciliation)
- Test: `tests/test_wp_post.py` (append new class)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - Legacy keys `rich_snippet`, `snippet_howto_type`, `snippet_howto_name`, `snippet_howto_desc` in `rankmath.*` are dropped from the outgoing scalar-meta payload.
  - Each dropped key prints one stderr line naming `rankmath.schemas` as the replacement.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_post.py`:

```python
class TestRankmathLegacyKeys:
    """rankmath.rich_snippet and rankmath.snippet_howto_* are dead in modern
    Rank Math; warn + drop, do not silently pass them through (issue #24)."""

    LEGACY_KEYS = [
        "rich_snippet",
        "snippet_howto_type",
        "snippet_howto_name",
        "snippet_howto_desc",
    ]

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_each_legacy_key_warns_and_drops(self, mock_get, mock_post, wp, md_file, mock_response, capsys):
        for key in self.LEGACY_KEYS:
            mock_post.reset_mock()
            path = md_file(
                {"title": "T", "rankmath": {"title": "SEO", key: "anything"}},
                "body",
            )
            mock_post.side_effect = [
                mock_response(201, {"id": 40, "link": "https://example.com/?p=40",
                                    "title": {"rendered": "T"}}),
                mock_response(200),  # scalar rankmath call
            ]
            wp.post_to_wordpress(path, raw=True)
            captured = capsys.readouterr()
            assert key in captured.err, f"expected stderr warning for {key}"
            assert "rankmath.schemas" in captured.err, \
                f"stderr for {key} should name rankmath.schemas as the replacement"
            rm = _rankmath_payload(mock_post)
            assert rm is not None
            assert key not in rm["meta"]
            # Full-key variant should never appear either.
            assert f"rank_math_{key}" not in rm["meta"]

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_only_legacy_keys_makes_no_scalar_call(self, mock_get, mock_post, wp, md_file, mock_response, capsys):
        """A rankmath block containing only legacy keys becomes empty after
        the drop, so no scalar-meta POST should be made."""
        path = md_file(
            {"title": "T", "rankmath": {"rich_snippet": "howto"}},
            "body",
        )
        mock_post.side_effect = [
            mock_response(201, {"id": 41, "link": "https://example.com/?p=41",
                                "title": {"rendered": "T"}}),
        ]
        wp.post_to_wordpress(path, raw=True)
        # Only the create-post call. If a scalar rankmath call fires, side_effect
        # will StopIteration.
        assert _rankmath_payload(mock_post) is None
        captured = capsys.readouterr()
        assert "rich_snippet" in captured.err

    @patch("wp_post.requests.post")
    @patch("wp_post.requests.get")
    def test_non_legacy_keys_untouched(self, mock_get, mock_post, wp, md_file, mock_response, capsys):
        """A rankmath block with an unknown (but not legacy-listed) key still
        gets that key passed through - no over-broad warning."""
        path = md_file(
            {"title": "T", "rankmath": {"title": "SEO", "rank_math_robots": "noindex"}},
            "body",
        )
        mock_post.side_effect = [
            mock_response(201, {"id": 42, "link": "https://example.com/?p=42",
                                "title": {"rendered": "T"}}),
            mock_response(200),
        ]
        wp.post_to_wordpress(path, raw=True)
        rm = _rankmath_payload(mock_post)
        assert rm["meta"].get("rank_math_robots") == "noindex"
        captured = capsys.readouterr()
        # No spurious "legacy" warning for a non-listed key.
        assert "rank_math_robots" not in captured.err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_wp_post.py::TestRankmathLegacyKeys -v`
Expected: FAILs (legacy keys currently pass through untouched, no warnings emitted).

- [ ] **Step 3: Add the warn-and-drop pass**

In `wp-post.py`, inside the block edited in Task 4, immediately after the `schemas = rankmath_meta.pop('schemas', None)` line, insert:

```python
            # Warn on legacy rich-snippet keys and drop them. These fields
            # were dead code as of Rank Math ~1.0.62; the shape they wrote
            # into is no longer read by the JSON-LD renderer. See issue #24.
            _LEGACY_RANKMATH_KEYS = (
                'rich_snippet',
                'snippet_howto_type',
                'snippet_howto_name',
                'snippet_howto_desc',
            )
            for legacy_key in _LEGACY_RANKMATH_KEYS:
                if legacy_key in rankmath_meta:
                    print(
                        f"⚠ rankmath.{legacy_key} is a dead Rank Math field; "
                        f"use rankmath.schemas instead. Dropping.",
                        file=sys.stderr,
                    )
                    rankmath_meta.pop(legacy_key)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_wp_post.py::TestRankmathLegacyKeys -v`
Expected: 3 PASS.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 435 passing (432 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Warn and drop legacy Rank Math rich-snippet frontmatter keys"
```

---

### Task 6: CLI surfaces schema failures

The `main()` function propagates `msls_failures` from the result dict into the JSON summary and exits non-zero. Do the same for `schema_failure` so automation can distinguish a fully-clean publish from one where schema meta didn't write.

**Files:**
- Modify: `wp-post.py:2496-2517` (the `main()` result-handling block)
- Test: `tests/test_wp_post.py` - append a sibling class `TestMainSchemaFailureExit` next to `TestMainMslsExit` (line 1957). Follow the same fixture pattern: `@patch.object(wp_post.WordPressPost, "post_to_wordpress")` + `@patch("wp_post.load_config")`; pass `--site-url`, `--username`, `--app-password` in `sys.argv`.

**Interfaces:**
- Consumes: `result['schema_failure']` from Task 4.
- Produces:
  - JSON summary printed by `main()` includes `schema_failure` when set.
  - `main()` exits non-zero when `schema_failure` is set, whether or not `msls_failures` is also set.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_post.py` immediately after `TestMainMslsExit` (which ends around line 2007):

```python
class TestMainSchemaFailureExit:
    """main() must reflect Rank Math schema-write failures in its machine-readable
    output and exit code, mirroring the msls_failures surface (issue #24)."""

    @patch.object(wp_post.WordPressPost, "post_to_wordpress")
    @patch("wp_post.load_config")
    def test_schema_failure_exits_nonzero_and_reports(
        self, mock_load_config, mock_post_to_wp, tmp_path, capsys
    ):
        f = tmp_path / "post.md"
        f.write_text("---\ntitle: T\n---\nbody", encoding="utf-8")
        mock_load_config.return_value = {
            "site_url": "https://example.com", "username": "u", "app_password": "p",
        }
        mock_post_to_wp.return_value = {
            "success": True, "id": 50, "url": "https://example.com/p/", "title": "T",
            "schema_failure": {
                "status_code": 400, "error": "rejected", "types": ["HowTo"],
            },
        }

        with patch("sys.argv", ["wp-post", "--site-url", "https://example.com",
                                 "--username", "u", "--app-password", "p", str(f)]):
            with pytest.raises(SystemExit) as exc:
                wp_post.main()

        assert exc.value.code == 1
        payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert payload["schema_failure"]["status_code"] == 400
        assert payload["schema_failure"]["types"] == ["HowTo"]

    @patch.object(wp_post.WordPressPost, "post_to_wordpress")
    @patch("wp_post.load_config")
    def test_clean_publish_has_no_schema_failure_key(
        self, mock_load_config, mock_post_to_wp, tmp_path, capsys
    ):
        f = tmp_path / "post.md"
        f.write_text("---\ntitle: T\n---\nbody", encoding="utf-8")
        mock_load_config.return_value = {
            "site_url": "https://example.com", "username": "u", "app_password": "p",
        }
        mock_post_to_wp.return_value = {
            "success": True, "id": 51, "url": "https://example.com/p/", "title": "T",
        }

        with patch("sys.argv", ["wp-post", "--site-url", "https://example.com",
                                 "--username", "u", "--app-password", "p", str(f)]):
            wp_post.main()

        payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert payload["success"] is True
        assert "schema_failure" not in payload

    @patch.object(wp_post.WordPressPost, "post_to_wordpress")
    @patch("wp_post.load_config")
    def test_both_msls_and_schema_failures_exit_nonzero(
        self, mock_load_config, mock_post_to_wp, tmp_path, capsys
    ):
        """A publish with BOTH kinds of failure surfaces both and exits 1 once."""
        f = tmp_path / "post.md"
        f.write_text("---\ntitle: T\n---\nbody", encoding="utf-8")
        mock_load_config.return_value = {
            "site_url": "https://example.com", "username": "u", "app_password": "p",
        }
        mock_post_to_wp.return_value = {
            "success": True, "id": 52, "url": "https://example.com/p/", "title": "T",
            "msls_failures": [{"locale": "es_ES", "post_id": 20, "ok": False, "error": "boom"}],
            "schema_failure": {"status_code": 400, "error": "rejected", "types": ["HowTo"]},
        }

        with patch("sys.argv", ["wp-post", "--site-url", "https://example.com",
                                 "--username", "u", "--app-password", "p", str(f)]):
            with pytest.raises(SystemExit) as exc:
                wp_post.main()

        assert exc.value.code == 1
        payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert payload.get("msls_failures")
        assert payload["schema_failure"]["types"] == ["HowTo"]
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest tests/test_wp_post.py::TestMainSchemaFailureExit -v`
Expected: FAILs (main() ignores `schema_failure`, exits 0, doesn't include it in output).

- [ ] **Step 3: Wire schema_failure into main()**

Replace `wp-post.py:2496-2517`:

```python
    if result['success']:
        summary = {
            'success': True,
            'id': result['id'],
            'title': result['title'],
            'url': result['url']
        }
        # The post is live, but MSLS translation links failed to write. Surface
        # it in the machine-readable output and exit non-zero so automation
        # notices instead of treating the publish as fully complete (issue #11).
        msls_failures = result.get('msls_failures')
        if msls_failures:
            summary['msls_failures'] = msls_failures
            print(json.dumps(summary))
            sys.exit(1)
        print(json.dumps(summary))
    else:
        print(json.dumps({
            'success': False,
            'error': result['error']
        }))
        sys.exit(1)
```

with:

```python
    if result['success']:
        summary = {
            'success': True,
            'id': result['id'],
            'title': result['title'],
            'url': result['url']
        }
        # The post is live, but a downstream write (MSLS translation links,
        # Rank Math schema meta) failed. Surface in the machine-readable
        # output and exit non-zero so automation notices instead of treating
        # the publish as fully complete (issues #11, #24).
        msls_failures = result.get('msls_failures')
        schema_failure = result.get('schema_failure')
        if msls_failures:
            summary['msls_failures'] = msls_failures
        if schema_failure:
            summary['schema_failure'] = schema_failure
        print(json.dumps(summary))
        if msls_failures or schema_failure:
            sys.exit(1)
    else:
        print(json.dumps({
            'success': False,
            'error': result['error']
        }))
        sys.exit(1)
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python3 -m pytest tests/test_wp_post.py::TestMainSchemaFailureExit -v`
Expected: 3 PASS.

- [ ] **Step 5: Run the full suite to check for regressions on msls_failures propagation**

Run: `python3 -m pytest -q`
Expected: 438 passing (435 + 3 new). Pay attention to the existing `msls_failures` main-level tests: they should still pass since the observable behaviour (JSON in stdout, exit non-zero) is unchanged.

- [ ] **Step 6: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Surface Rank Math schema write failures in main() JSON output"
```

---

### Task 7: Documentation

Update the two user-facing surfaces: the inline `--help` docstring in `wp-post.py` and the frontmatter reference in the wp-post skill. No code behaviour changes.

**Files:**
- Modify: `wp-post.py:2146-2148` (the `rankmath` frontmatter description in the inline help)
- Modify: `skills/wp-post/references/frontmatter.md:36-43` (the rankmath section)

**Interfaces:** none.

- [ ] **Step 1: Update the inline help docstring**

In `wp-post.py`, find the `rankmath` block in the help text (currently around lines 2146-2148):

```
  rankmath        Rank Math SEO meta with shorthand keys:
                    title, description, focus_keyword
                  Full rank_math_* keys also accepted
```

Replace with:

```
  rankmath        Rank Math SEO meta. Shorthand keys:
                    title, description, focus_keyword
                  Full rank_math_* keys also accepted.
                  rankmath.schemas: {Type: {...}} writes each schema body
                  as rank_math_schema_<Type> (PHP-serialised) for JSON-LD
                  rich snippets (HowTo, Recipe, Product, etc.). Upsert per
                  type; types not listed are left alone. Legacy
                  rich_snippet / snippet_howto_* keys are warned and dropped.
```

- [ ] **Step 2: Update the skill's frontmatter reference**

In `skills/wp-post/references/frontmatter.md`, find the rankmath block (around lines 36-43):

```yaml
rankmath:                      # Rank Math SEO plugin
  title: SEO Title             # shorthand → rank_math_title
  description: SEO desc        # shorthand → rank_math_description (wins over excerpt)
  focus_keyword: keyword       # shorthand → rank_math_focus_keyword
                               # full rank_math_* keys also accepted
# If rankmath.description is omitted, a non-empty `excerpt` is pushed as
# rank_math_description so the live <meta name="description"> tracks the excerpt
# instead of a stale override. An empty/absent excerpt leaves it untouched.
```

Replace with:

```yaml
rankmath:                      # Rank Math SEO plugin
  title: SEO Title             # shorthand → rank_math_title
  description: SEO desc        # shorthand → rank_math_description (wins over excerpt)
  focus_keyword: keyword       # shorthand → rank_math_focus_keyword
                               # full rank_math_* keys also accepted
  schemas:                     # optional: JSON-LD rich-snippet schemas
    HowTo:                     # key becomes rank_math_schema_HowTo
      "@type": HowTo
      name: 'How to do the thing'
      step:
        - {"@type": HowToStep, name: 'Step 1', text: '…'}
        - {"@type": HowToStep, name: 'Step 2', text: '…'}
# If rankmath.description is omitted, a non-empty `excerpt` is pushed as
# rank_math_description so the live <meta name="description"> tracks the excerpt
# instead of a stale override. An empty/absent excerpt leaves it untouched.
#
# rankmath.schemas: each key becomes a rank_math_schema_<Type> post_meta row
# holding the PHP-serialised schema body, which Rank Math reads back into the
# page's JSON-LD @graph on render. Upsert per type - a type not listed in a
# subsequent publish is NOT removed (there is no delete-orphan pass). Empty
# {} is a no-op; the key being absent leaves existing rows untouched.
```

- [ ] **Step 3: Also update the field-details table**

In the same file (around line 70), the row for `rankmath`:

```
| `rankmath`       | map           | no       | SEO meta; shorthand or full `rank_math_*` keys         |
```

Replace with:

```
| `rankmath`       | map           | no       | SEO meta; shorthand or full `rank_math_*` keys; `schemas: {Type: {…}}` writes JSON-LD rich-snippet schemas |
```

- [ ] **Step 4: Verify tests still pass**

Run: `python3 -m pytest -q`
Expected: 438 passing (no change; doc-only edits).

- [ ] **Step 5: Commit**

```bash
git add wp-post.py skills/wp-post/references/frontmatter.md
git commit -m "Document rankmath.schemas frontmatter shape and semantics"
```

- [ ] **Step 6: Note for the user - skill install**

The `/wp-post` skill is copied into each project by `install.sh`, not symlinked. This documentation change lives in `skills/wp-post/references/frontmatter.md` in the source repo but is NOT reflected in any already-installed copy of the skill until `install.sh` is re-run in that project. Mention this in the final report so the user knows to re-run `install.sh` in the content projects that use `rankmath.schemas`.

---

### Task 8: End-to-end live smoke test

The unit tests all mock `requests`. Before opening a PR, run one real publish against a Rank-Math-installed site with `rankmath.schemas` populated and confirm the JSON-LD renders.

**Files:** none.

**Interfaces:** none.

- [ ] **Step 1: Prepare a test article**

Pick or write a markdown file with a `rankmath.schemas` block:

```yaml
---
title: Schema smoke test
slug: schema-smoke-test
status: draft
rankmath:
  schemas:
    HowTo:
      "@type": HowTo
      name: 'Test HowTo'
      description: 'A schema smoke test.'
      step:
        - {"@type": HowToStep, name: 'Step one', text: 'Do the first thing.'}
        - {"@type": HowToStep, name: 'Step two', text: 'Do the second thing.'}
---

Body copy.
```

- [ ] **Step 2: Publish it**

```bash
python3 wp-post.py path/to/test-article.md --verbose
```

Expected stdout: `✓ Rank Math schemas written: HowTo` and a JSON summary with no `schema_failure` field.

- [ ] **Step 3: Verify the DB row**

Either via WP-CLI on the box:

```bash
wp post meta get <post_id> rank_math_schema_HowTo
```

Or via the WP REST admin API if the meta is registered for REST.

Expected: a PHP-serialised string that starts with `a:` and contains `HowTo` and the step names.

- [ ] **Step 4: Verify the JSON-LD on the live page**

```bash
curl -s 'https://<site>/<slug>/' \
  | grep -oE 'application/ld\+json[^<]*' \
  | head -c 4000
```

Or open the page in a browser and inspect the `<script type="application/ld+json">` blocks.

Expected: an entry in the `@graph` array with `"@type":"HowTo"` and the step titles you wrote.

- [ ] **Step 5: Test the empty-dict no-op**

Republish the same article with `rankmath.schemas: {}` and confirm the HowTo row is still there (no clear-all).

- [ ] **Step 6: Test the legacy-key warning**

Add `rankmath.rich_snippet: howto` to the frontmatter and republish. Expect a stderr warning naming `rankmath.schemas`, and no `rank_math_rich_snippet` row created.

- [ ] **Step 7: Push and open a PR**

```bash
git push -u origin rankmath-schemas
gh pr create --title 'Publish rankmath.schemas frontmatter as rank_math_schema_* meta' \
  --body "$(cat <<'EOF'
Closes #24.

## Summary
- New `update_rankmath_schemas` method PHP-serialises each schema dict and writes it via Rank Math's existing `updateMeta` endpoint as `rank_math_schema_<Type>` meta.
- `rankmath.schemas` frontmatter block gates the call: absent or `{}` = no-op; populated = upsert per type. No delete-orphan.
- Legacy `rich_snippet` / `snippet_howto_*` frontmatter keys warn and drop.
- Schema-write failures surface as `result['schema_failure']` (mirror of `msls_failures`) and propagate through `main()`'s JSON output and exit code.

## Test plan
- [x] Unit tests: 438 passing (was 418; +20 new).
- [x] Live smoke test on <site>/<slug>: HowTo JSON-LD renders in `@graph`.
- [x] Empty-dict republish leaves existing HowTo row intact.
- [x] Legacy `rich_snippet` frontmatter is warned + dropped, no meta row written.

## Follow-ups
- Documentation in `skills/wp-post/references/frontmatter.md` requires re-running `install.sh` in content projects that consume this feature.
EOF
)"
```

---

## Self-Review

Ran the three checks the writing-plans skill requires:

**1. Spec coverage.** Walked the issue #24 body:
- Problem statement / effect: no code, informational only. Covered.
- Approach (Python-only, phpserialize, updateMeta): Task 2 (dep), Task 3 (writer).
- Trade-off note (no delete-orphan): documented in Global Constraints and Task 3 docstring; enforced by not attempting discovery.
- Implementation-time verification requirement: Task 1 explicitly gates the plan.
- Frontmatter shape / semantics: Task 4 tests each branch (absent, empty, populated, schemas-only).
- `.pop` before scalar-meta pass: Task 4 Step 3, tested in Task 4 Step 1's `test_populated_schemas_written_after_scalar_meta`.
- `phpserialize` in requirements: Task 2.
- Legacy-key warn + drop, four named keys: Task 5.
- Schema-write failure surfaced via return payload: Task 4 Steps 3-4; CLI propagation in Task 6.
- Non-Rank-Math sites: 404 handling inherits from existing `update_rankmath_meta` pattern (returns failure dict, publish still succeeds). Covered by Task 3's `test_http_failure_returns_failure_dict`.
- Acceptance criteria: Task 8 end-to-end covers the live half; Tasks 4-6 unit tests cover the rest.

**2. Placeholder scan.** No TBD / TODO / "add appropriate" / "similar to Task N" text. One approximate reference in Task 6 Step 2 ("adjust class name after locating it") which is intentional - the exact class name for the main-level tests wasn't in the grep excerpt I had; the executor must locate it. Left as a locate-then-match instruction, not a code placeholder.

**3. Type consistency.** Method name is `update_rankmath_schemas` in Task 3's signature, callsite in Task 4 Step 3, and docstring - matches. Return-dict shape is `{status_code, error, types}` in Task 3 and referenced as `.status_code` / `.types` in Task 4's test. `result['schema_failure']` is the key in Task 4 Step 4 and Task 6's CLI test. Consistent.
