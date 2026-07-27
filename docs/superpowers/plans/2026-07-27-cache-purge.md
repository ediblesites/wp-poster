# `wp-post --purge` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--purge` action to `wp-post` that clears the SpinupWP page cache for one page, one site in a multisite network, or every site in the network.

**Architecture:** Seven module-level functions in `wp-post.py`, wired into `main()` alongside the existing standalone action flags (`--ping`, `--config-path`, `--init`). Config discovery, target resolution, command construction and execution are separate layers, so the whole feature is testable without SSH: `resolve_purge_targets` is a pure function asserted directly, and `spinupwp_purge` is the only function in the codebase that spawns a purge subprocess. One existing function (`find_site_for_file`) is corrected, and one existing method (`WordPressPost.parse_frontmatter_only`) becomes a delegating one-liner.

**Tech Stack:** Python 3, `argparse`, `subprocess`, `pytest` with `unittest.mock`. Purging is performed by the SpinupWP WordPress plugin's WP-CLI commands, reached over SSH.

**Spec:** `docs/superpowers/specs/2026-07-27-cache-purge-design.md`

## Global Constraints

- All code goes in `wp-post.py`. All tests go in `tests/test_wp_post.py`.
- **Use `python3`, not `python`.** There is no `python` on PATH in this environment; `python -m pytest` fails with "command not found". Every test command in this plan uses `python3`.
- Tests are imported through `tests/conftest.py`, which loads the hyphenated `wp-post.py` as the module `wp_post`. Patch targets are therefore `wp_post.<name>` (e.g. `@patch('wp_post.subprocess.run')`).
- Follow the repo's commit style: plain imperative sentences, no `feat:`/`fix:` prefixes. Examples from `git log`: `Add --ping flag to verify site connection and credentials`, `Treat frontmatter 'id: null' as absent to route new posts to create`.
- Treat a falsy frontmatter `id` (absent, `null`, `0`) as "not published", matching the existing `if frontmatter.get('id'):` idiom at `wp-post.py:522`.
- **No purge runs on unvalidated input.** Every configuration failure - missing config, missing alias, unknown site key, unpublished file, unreadable file, incomplete network entry - must be detected and reported before any subprocess is spawned. Purging the wrong site is worse than not purging.
- Error messages naming a configuration problem must name the config file they came from. The spec requires this at `docs/superpowers/specs/2026-07-27-cache-purge-design.md:94` and `:127`.
- Never purge Cloudflare. The spec records the measurements showing it caches no HTML on any of these zones, so a purge call would invalidate nothing.
- No retry or backoff on purge failures. Purging is idempotent and cheap to re-run by hand; a retry loop adds failure modes without adding reliability. This is deliberately unlike the MSLS write path.
- Per `CLAUDE.md`, bump the version in `.claude-plugin/plugin.json` when `skills/` changes. Task 6 bumps `1.10.0` -> `1.11.0`.

---

## File Structure

| File                            | Change | Responsibility                                                       |
|---------------------------------|--------|-----------------------------------------------------------------------|
| `wp-post.py`                    | Modify | New purge section (Tasks 1, 3, 4), `find_site_for_file` fix (Task 2), CLI wiring (Task 5) |
| `tests/test_wp_post.py`         | Modify | New test classes appended, following existing conventions             |
| `README.md`                     | Modify | Document `--purge` and the `wp_cli_alias` config key                  |
| `skills/wp-post/SKILL.md`       | Modify | Teach Claude when to reach for `--purge`                              |
| `.claude-plugin/plugin.json`    | Modify | Version bump required by `CLAUDE.md`                                  |

New purge code lands in one contiguous section of `wp-post.py`, placed immediately after `write_msls_links` (which ends at line 1135) and before `resolve_format`. That keeps the WP-CLI-over-SSH functions together, since they share a transport concern. Task 2 is the exception: it edits `find_site_for_file` in place at line 984.

## Review corrections folded into this plan

An external review of the first draft found nine issues; all nine were reproduced against the codebase before being accepted. The non-obvious ones:

- **Config was resolved from the working directory, not the target file.** `load_config()` walks up from `Path.cwd()` (`wp-post.py:1194` -> `find_local_config`). Reproduced: with a decoy `.wp-poster.json` in the CWD, `load_config()` returned `https://WRONG-SITE.com`, so `--purge --file /other/project/post.md` would have read the post ID from the target file and purged the CWD's site. Task 1 adds `find_config_for_purge`, anchored at the file.
- **Site matching used string prefixes.** `find_site_for_file` compares with `str.startswith` (`wp-post.py:992`). Reproduced: `/project/de/content-evil/post.md` matches the site rooted at `de/content/`. Task 2 makes containment boundary-aware.
- **Network targets were unvalidated.** `resolve_site_identity` returns `{'site_url': None, ...}` for an incomplete `network.sites` entry. Reproduced. Unchecked, that produces a literal `--url=None`. Task 3 validates every target.

## This plan has been executed once against a scratch copy

Every code and test block below was applied to a throwaway copy of the repo and run before the plan was finalised, so the counts and expectations are measured rather than estimated:

| Task | Test selector                                                    | Tests |
|------|------------------------------------------------------------------|-------|
| 1    | `ReadFrontmatter or FindConfigForPurge or ResolveWpCliTransport`  | 14    |
| 2    | `FindSiteForFile` (3 new + 2 pre-existing)                        | 5     |
| 3    | `ResolvePurgeTargets`                                             | 17    |
| 4    | `BuildPurgeCommand or SpinupwpPurge`                              | 9     |
| 5    | `HandlePurge or PurgeArgparseWiring or MainPurgeDispatch`         | 14    |

Full suite after all tasks: **234 passed** (177 pre-existing + 57 new), with no changes to any pre-existing test.

---

### Task 1: Config discovery, error type, and transport resolution

**Files:**
- Modify: `wp-post.py:68-77` (delegate `parse_frontmatter_only`), and insert a new section after line 1135
- Test: `tests/test_wp_post.py` (append)

**Interfaces:**
- Consumes: `load_frontmatter(yaml_text)` (existing, `wp-post.py:53`)
- Produces:
  - `PurgeConfigError(Exception)` - raised for misconfiguration detected before any subprocess runs
  - `read_frontmatter(filepath) -> dict` - frontmatter of a file, `{}` when absent
  - `find_config_for_purge(anchor_path) -> tuple[dict, str, str | None]` - `(config, config_path, project_root)`; `project_root` is set only when the config describes a network
  - `resolve_wp_cli_transport(config, config_path) -> list[str]` - argv prefix, e.g. `['wp', '@payperfax']` or `['wp', '--ssh=dash/sites/dashpadd.com/files']`

`WordPressPost.parse_frontmatter_only` currently duplicates the frontmatter-reading logic and does not use `self`. It becomes a delegating one-liner so the new purge code and the existing posting code read frontmatter the same way. This is a three-line change confined to code this feature touches; do not retrofit `find_translation_siblings`, which has its own inline copy.

`find_config_for_purge` deliberately prefers a network config found anywhere up the tree over a nearer non-network one. The legacy per-site layout that `resolve_site_identity` still supports (`wp-post.py:970`) puts a `<site_key>/.wp-poster.json` inside a network project; stopping at that file would lose the network map.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_post.py`:

```python
# ===========================================================================
# Cache purging: config discovery and transport
# ===========================================================================

read_frontmatter = wp_post.read_frontmatter
find_config_for_purge = wp_post.find_config_for_purge
resolve_wp_cli_transport = wp_post.resolve_wp_cli_transport
PurgeConfigError = wp_post.PurgeConfigError


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
```

`_PURGE_SITES` is defined in Task 3's test block. Define it now, above `TestFindConfigForPurge`, so Task 1's tests run standalone:

```python
_PURGE_SITES = [
    {'key': 'en', 'site_url': 'https://e.com', 'locale': 'en_US', 'blog_id': 1},
    {'key': 'de', 'site_url': 'https://e.com/de', 'locale': 'de_DE', 'blog_id': 3},
]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_wp_post.py -k "ReadFrontmatter or FindConfigForPurge or ResolveWpCliTransport" -v`
Expected: FAIL - `AttributeError: module 'wp_post' has no attribute 'read_frontmatter'` at collection time.

- [ ] **Step 3: Write the implementation**

Replace `WordPressPost.parse_frontmatter_only` (`wp-post.py:68-77`) with a delegating version:

```python
    def parse_frontmatter_only(self, filepath):
        """Parse just the frontmatter without processing content"""
        return read_frontmatter(filepath)
```

Insert after `write_msls_links` ends (`wp-post.py:1135`), before `def resolve_format`:

```python
# ---------------------------------------------------------------------------
# Cache purging (SpinupWP page cache, via the plugin's WP-CLI commands)
# ---------------------------------------------------------------------------

_PURGE_TIMEOUT = 30


class PurgeConfigError(Exception):
    """A purge could not be resolved from configuration.

    Raised before any subprocess is spawned, so a misconfigured run costs
    nothing and reports the exact file, key or value to fix.
    """


def read_frontmatter(filepath):
    """Parse just the frontmatter of a file, returning {} when it has none."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            return load_frontmatter(parts[1]) or {}
    return {}


def _global_config_paths():
    """Global config locations, in precedence order.

    Deliberately excludes the cwd-relative lookup that load_config() performs:
    a purge must never be steered by which directory the shell happens to be
    in. Defined as a function so tests can substitute it.
    """
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    return [
        Path.home() / '.wp-poster.json',
        Path.home() / '.config/wp-poster/config.json',
        script_dir / '.wp-poster.json',
    ]


def find_config_for_purge(anchor_path):
    """Locate the config governing anchor_path.

    Returns (config, config_path, project_root). project_root is the config's
    directory when the config describes a network, otherwise None.

    Anchoring at the target file rather than the working directory is what
    makes `wp-post --purge --file /other/project/post.md` purge the site that
    file belongs to, instead of whatever project the shell is sitting in. A
    network config found anywhere up the tree beats a nearer non-network one,
    so the legacy per-site config layout cannot shadow the network map.
    """
    start = Path(anchor_path).resolve()
    current = start if start.is_dir() else start.parent
    nearest = None

    while True:
        candidate = current / '.wp-poster.json'
        if candidate.exists():
            try:
                with open(candidate, 'r') as f:
                    config = json.load(f)
            except (OSError, ValueError) as e:
                raise PurgeConfigError(f"Could not read {candidate}: {e}")
            if 'network' in config:
                return config, str(candidate), str(current)
            if nearest is None:
                nearest = (config, str(candidate))
        if current.parent == current:
            break
        current = current.parent

    if nearest:
        return nearest[0], nearest[1], None

    for path in _global_config_paths():
        if path.exists():
            try:
                with open(path, 'r') as f:
                    return json.load(f), str(path), None
            except (OSError, ValueError) as e:
                raise PurgeConfigError(f"Could not read {path}: {e}")

    raise PurgeConfigError(
        f"No .wp-poster.json found from {start} upward, or in any global location."
    )


def resolve_wp_cli_transport(config, config_path):
    """Return the argv prefix for wp-cli calls, e.g. ['wp', '@payperfax'].

    The alias is read from network.wp_cli_alias when the config describes a
    network (where the key already exists for MSLS linking), otherwise from a
    top-level wp_cli_alias. A value starting with '@' is a wp-cli alias
    resolved through ~/.wp-cli/config.yml; anything else is used as an --ssh=
    target, so a project can be self-contained with no external wp-cli config.
    """
    alias = (config.get('network') or {}).get('wp_cli_alias') or config.get('wp_cli_alias')
    if not alias:
        raise PurgeConfigError(
            f"No wp_cli_alias in {config_path}. Add one, either as a wp-cli alias\n"
            "resolved through ~/.wp-cli/config.yml:\n"
            '  "wp_cli_alias": "@myalias"\n'
            "or as an ssh target, which needs no wp-cli config at all:\n"
            '  "wp_cli_alias": "myhost/sites/example.com/files"'
        )
    if not isinstance(alias, str):
        raise PurgeConfigError(
            f"wp_cli_alias in {config_path} must be a string, got {type(alias).__name__}."
        )
    if alias.startswith('@'):
        return ['wp', alias]
    return ['wp', f'--ssh={alias}']
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_wp_post.py -k "ReadFrontmatter or FindConfigForPurge or ResolveWpCliTransport" -v`
Expected: PASS, 14 tests.

Then run the full suite to confirm the `parse_frontmatter_only` delegation broke nothing:

Run: `python3 -m pytest tests/ -q`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Add file-anchored config discovery and wp-cli transport resolution"
```

---

### Task 2: Boundary-safe site matching

**Files:**
- Modify: `wp-post.py:984-994` (`find_site_for_file`)
- Test: `tests/test_wp_post.py` (append)

**Interfaces:**
- Produces: `find_site_for_file(project_root, network_config, filepath)` - unchanged signature and return type, corrected containment check.

`find_site_for_file` currently decides which site a file belongs to with `file_abs.startswith(content_abs)`. Because `os.path.abspath` strips the trailing slash from a `content_path` like `de/content/`, a file at `de/content-evil/post.md` matches the site rooted at `de/content`. Reproduced against the current code. For posting this misfiles a translation; for purging it clears the wrong blog's cache.

This function is also on the posting path (`_do_post_to_wordpress`), so the fix is deliberately behaviour-preserving for legitimate paths: it only stops matching paths that were never inside the content root. Both existing tests in `TestFindSiteForFile` must continue to pass untouched.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_post.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_wp_post.py -k "FindSiteForFileBoundaries" -v`
Expected: FAIL - `test_sibling_directory_sharing_a_prefix_does_not_match` asserts `key is None` but gets `'de'`. The other two pass already.

- [ ] **Step 3: Write the implementation**

Replace `find_site_for_file` (`wp-post.py:984-994`) with:

```python
def find_site_for_file(project_root, network_config, filepath):
    """Return (site_key, site_info) for the network site whose content_path
    contains filepath, or (None, None) if no site matches.

    Containment is checked on path boundaries rather than string prefixes: a
    file under 'de/content-evil/' must not match the site rooted at
    'de/content/', which a startswith comparison would wrongly accept once
    the trailing slash is normalised away.
    """
    file_path = Path(filepath).resolve()
    sites = network_config.get('network', {}).get('sites', {})
    for site_key, site_info in sites.items():
        content_root = Path(project_root, site_info['content_path']).resolve()
        try:
            file_path.relative_to(content_root)
        except ValueError:
            continue
        return site_key, site_info
    return None, None
```

`Path.resolve()` is non-strict by default, so it works on paths that do not exist (as the existing tests rely on). Resolving both sides also means a symlinked content directory is compared consistently.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_wp_post.py -k "FindSiteForFile" -v`
Expected: PASS, 5 tests - the 3 new ones plus the 2 pre-existing `TestFindSiteForFile` tests, which must be unmodified.

Run: `python3 -m pytest tests/ -q`
Expected: PASS, no regressions on the posting path.

- [ ] **Step 5: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Match network sites on path boundaries instead of string prefixes"
```

---

### Task 3: Scope resolution

**Files:**
- Modify: `wp-post.py` (append to the purge section from Task 1)
- Test: `tests/test_wp_post.py` (append)

**Interfaces:**
- Consumes: `read_frontmatter`, `PurgeConfigError` (Task 1); `find_site_for_file` (Task 2); `resolve_site_identity(project_root, site_key, site_info)` (existing, `wp-post.py:955`)
- Produces: `resolve_purge_targets(scope, value, config, project_root=None, config_path=None) -> list[dict]`, each dict `{'label': str, 'site_url': str, 'post_id': int | None}`. A `post_id` of `None` means "purge this whole site"; an int means "purge just that post".

`scope` is one of `'file'`, `'site'`, `'network'`. `value` is the file path for `'file'`, the site key (or `''`/`None` for "the configured site") for `'site'`, and ignored for `'network'`.

Every returned target is validated before it is returned. `resolve_site_identity` yields `{'site_url': None, ...}` for an incomplete `network.sites` entry (reproduced), which unchecked would produce a literal `--url=None` on the wire.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_post.py`. These reuse `_scaffold_network_map` (defined at line 864) and `_PURGE_SITES` (defined in Task 1).

```python
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
        """resolve_site_identity yields site_url=None for an incomplete entry."""
        config = {'network': {'wp_cli_alias': '@x', 'sites': {
            'de': {'content_path': 'de/content/'},   # no site_url / locale / blog_id
        }}}
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('site', 'de', config, str(tmp_path))
        assert 'site_url' in str(exc.value)

    def test_non_http_site_url_rejected(self, tmp_path):
        config = {'network': {'wp_cli_alias': '@x', 'sites': {
            'de': {'content_path': 'de/content/', 'site_url': 'ftp://e.com', 'blog_id': 3},
        }}}
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('site', 'de', config, str(tmp_path))
        assert 'site_url' in str(exc.value)

    def test_non_integer_post_id_rejected(self, tmp_path):
        f = tmp_path / 'a.md'
        f.write_text('---\ntitle: T\nid: "not-a-number"\n---\nbody', encoding='utf-8')
        with pytest.raises(PurgeConfigError) as exc:
            resolve_purge_targets('file', str(f), {'site_url': 'https://x.com'}, None)
        assert 'post id' in str(exc.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_wp_post.py -k "ResolvePurgeTargets" -v`
Expected: FAIL - `AttributeError: module 'wp_post' has no attribute 'resolve_purge_targets'`.

- [ ] **Step 3: Write the implementation**

Append to the purge section in `wp-post.py`:

```python
def _validate_purge_target(target, source):
    """Reject a target that could not be safely turned into a wp-cli command.

    Runs before any subprocess, so a half-configured network entry fails with
    a readable message instead of shipping `--url=None` to the server.
    """
    site_url = target['site_url']
    if not isinstance(site_url, str) or not site_url.startswith(('http://', 'https://')):
        raise PurgeConfigError(
            f"Target '{target['label']}' has an unusable site_url ({site_url!r}) "
            f"in {source}. Expected an http(s) URL."
        )
    post_id = target['post_id']
    if post_id is not None:
        if isinstance(post_id, bool) or not isinstance(post_id, int) or post_id <= 0:
            raise PurgeConfigError(
                f"Target '{target['label']}' has an unusable post id ({post_id!r}). "
                "Expected a positive integer."
            )
    return target


def resolve_purge_targets(scope, value, config, project_root=None, config_path=None):
    """Resolve a purge scope to an ordered list of validated targets.

    scope: 'file' | 'site' | 'network'
    value: file path for 'file'; site key (or '' meaning "the configured
           site") for 'site'; ignored for 'network'.

    Returns [{'label': str, 'site_url': str, 'post_id': int | None}, ...]
    where a post_id of None means "purge this whole site".

    Every failure mode raises PurgeConfigError naming what to fix, rather than
    guessing at a target - purging the wrong blog is worse than not purging.
    """
    source = config_path or 'the loaded config'
    network = config.get('network') or {}
    sites = network.get('sites') or {}

    if scope == 'network':
        if not sites:
            raise PurgeConfigError(
                f"--network needs a network config, but {source} has no 'network' key. "
                "Use --site for a single-site project."
            )
        targets = []
        for site_key, site_info in sites.items():
            identity = resolve_site_identity(project_root, site_key, site_info)
            targets.append(_validate_purge_target({
                'label': site_key,
                'site_url': identity['site_url'],
                'post_id': None,
            }, source))
        return targets

    if scope == 'site':
        if not sites:
            site_url = config.get('site_url')
            if not site_url:
                raise PurgeConfigError(f"No site_url in {source}; cannot resolve --site.")
            return [_validate_purge_target(
                {'label': site_url, 'site_url': site_url, 'post_id': None}, source)]
        valid = ', '.join(sorted(sites))
        if not value:
            raise PurgeConfigError(
                f"--site requires a site key on a network project. Valid keys: {valid}"
            )
        if value not in sites:
            raise PurgeConfigError(f"Unknown site '{value}'. Valid keys: {valid}")
        identity = resolve_site_identity(project_root, value, sites[value])
        return [_validate_purge_target(
            {'label': value, 'site_url': identity['site_url'], 'post_id': None}, source)]

    # scope == 'file'
    try:
        frontmatter = read_frontmatter(value)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise PurgeConfigError(f"Could not read frontmatter from {value}: {e}")

    post_id = frontmatter.get('id')
    if not post_id:
        raise PurgeConfigError(
            f"{value} has no post id in its frontmatter, so it has not been "
            "published yet and nothing is cached for it."
        )

    if sites:
        site_key, site_info = find_site_for_file(project_root, config, value)
        if site_key is None:
            configured = ', '.join(sorted(s['content_path'] for s in sites.values()))
            raise PurgeConfigError(
                f"{value} is not inside any configured content_path ({configured}) "
                f"from {source}, so its site could not be determined."
            )
        identity = resolve_site_identity(project_root, site_key, site_info)
        return [_validate_purge_target({
            'label': f'{site_key} #{post_id}',
            'site_url': identity['site_url'],
            'post_id': post_id,
        }, source)]

    site_url = config.get('site_url')
    if not site_url:
        raise PurgeConfigError(f"No site_url in {source}; cannot resolve --file.")
    return [_validate_purge_target(
        {'label': f'#{post_id}', 'site_url': site_url, 'post_id': post_id}, source)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_wp_post.py -k "ResolvePurgeTargets" -v`
Expected: PASS, 17 tests.

- [ ] **Step 5: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Resolve and validate purge scopes into SpinupWP targets"
```

---

### Task 4: Command construction and execution

**Files:**
- Modify: `wp-post.py` (append to the purge section)
- Test: `tests/test_wp_post.py` (append)

**Interfaces:**
- Consumes: transport list (Task 1), target dicts (Task 3), `_PURGE_TIMEOUT` (Task 1)
- Produces:
  - `build_purge_command(transport, target) -> list[str]`
  - `spinupwp_purge(transport, target, timeout=_PURGE_TIMEOUT) -> tuple[bool, str | None]` returning `(ok, error)`

`build_purge_command` is separate from `spinupwp_purge` so `--test` mode can print the exact command without running it, and so command shape is asserted directly rather than through mock call inspection.

`spinupwp_purge` must not raise. `FileNotFoundError` is caught first for its specific message, then `OSError` catches the rest (`PermissionError`, `NotADirectoryError`, and so on - all `OSError` subclasses). `subprocess.TimeoutExpired` is **not** an `OSError` subclass and needs its own clause.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_post.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_wp_post.py -k "BuildPurgeCommand or SpinupwpPurge" -v`
Expected: FAIL - `AttributeError: module 'wp_post' has no attribute 'build_purge_command'`.

- [ ] **Step 3: Write the implementation**

Append to the purge section in `wp-post.py`:

```python
def build_purge_command(transport, target):
    """Build the wp-cli argv that purges one target.

    A target with a post_id purges just that post; without one it purges the
    whole site. --url= is how wp-cli selects a blog within a multisite
    network, and is harmless on a single site.
    """
    base = transport + ['spinupwp', 'cache']
    if target['post_id'] is None:
        return base + ['purge-site', f"--url={target['site_url']}"]
    return base + ['purge-post', str(target['post_id']), f"--url={target['site_url']}"]


def spinupwp_purge(transport, target, timeout=_PURGE_TIMEOUT):
    """Purge one target. Returns (ok, error) and never raises.

    Failures are returned rather than raised so the caller can keep purging
    the remaining targets: one unreachable site should not leave the rest of
    the network stale.
    """
    cmd = build_purge_command(transport, target)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return False, "wp-cli not found (is `wp` on PATH?)"
    except subprocess.TimeoutExpired:
        # Not an OSError subclass, so this clause is load-bearing.
        return False, f"wp timed out after {timeout}s"
    except OSError as e:
        return False, f"could not run wp: {e}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip()
        return False, f"wp exited {result.returncode}" + (f": {detail}" if detail else "")
    return True, None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_wp_post.py -k "BuildPurgeCommand or SpinupwpPurge" -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Build and run SpinupWP purge commands"
```

---

### Task 5: Orchestration and CLI wiring

**Files:**
- Modify: `wp-post.py` (append `handle_purge` to the purge section; extract `build_arg_parser`, add flags and dispatch in `main()`)
- Test: `tests/test_wp_post.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1-4
- Produces: `build_arg_parser() -> argparse.ArgumentParser`, `handle_purge(args) -> int` (process exit code), called from `main()`

**CRITICAL - argparse dest collision.** `main()` already defines a positional `file` argument. Adding `--file` without an explicit `dest` silently collides: argparse raises no error, and `wp-post --purge --file X` parses to `file=None`, losing the value entirely. Verified. `--file` MUST be declared as `dest='purge_file'`. `--site` and `--network` get `dest='purge_site'` and `dest='purge_network'` for symmetry.

`--site` uses `nargs='?', const=''` so three states are distinguishable: flag absent (`None`), flag given bare (`''`, meaning "the configured site"), and flag given a key (`'de'`).

**Test layering.** Orchestration tests patch `wp_post.spinupwp_purge`, because what they assert is control flow: which targets get attempted, what the exit code is, whether `--test` short-circuits. Command content is already covered at the `subprocess` boundary in Task 4. One test (`test_end_to_end_command_reaches_subprocess`) deliberately patches `subprocess.run` instead, to prove the whole chain composes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_post.py`:

```python
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
        """Regression: the target file's project, not the shell's, decides the site."""
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
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

    def test_two_scope_selectors_exit_one(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert handle_purge(_PurgeArgs(purge_site='de', purge_network=True)) == 1


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_wp_post.py -k "HandlePurge or PurgeArgparseWiring or MainPurgeDispatch" -v`
Expected: FAIL - `AttributeError: module 'wp_post' has no attribute 'handle_purge'`.

- [ ] **Step 3: Write the implementation**

Append to the purge section in `wp-post.py`:

```python
def handle_purge(args):
    """Resolve the requested scope, purge each target, return an exit code.

    Configuration problems are reported before anything runs. Once purging
    starts, a failure on one target is recorded and the loop continues, so a
    single unreachable site cannot leave the rest of the network stale.
    """
    selected = [
        ('file', args.purge_file is not None),
        ('site', args.purge_site is not None),
        ('network', bool(args.purge_network)),
    ]
    chosen = [name for name, active in selected if active]
    if len(chosen) != 1:
        problem = "Specify exactly one scope" if not chosen else f"Got {len(chosen)} scopes"
        print(f"✗ {problem} for --purge: --file <path>, --site [key], or --network",
              file=sys.stderr)
        return 1
    scope = chosen[0]
    value = {'file': args.purge_file, 'site': args.purge_site, 'network': None}[scope]

    # Anchor config discovery at the target file when there is one, so a
    # --file from another project is never purged against the shell's site.
    anchor = args.purge_file or os.getcwd()

    try:
        config, config_path, project_root = find_config_for_purge(anchor)
        transport = resolve_wp_cli_transport(config, config_path)
        targets = resolve_purge_targets(scope, value, config, project_root, config_path)
    except PurgeConfigError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1

    noun = 'site' if len(targets) == 1 else 'sites'
    print(f"Purging SpinupWP cache ({len(targets)} {noun})")

    failures = 0
    for target in targets:
        if args.test:
            print(f"  [test] {target['label']:<12} {' '.join(build_purge_command(transport, target))}")
            continue
        if args.verbose:
            print(f"  → {' '.join(build_purge_command(transport, target))}")
        ok, error = spinupwp_purge(transport, target)
        if ok:
            print(f"  ✓ {target['label']:<12} {target['site_url']}")
        else:
            failures += 1
            print(f"  ✗ {target['label']:<12} {target['site_url']}  ({error})")

    if args.test:
        return 0
    purged = len(targets) - failures
    mark = '✓' if failures == 0 else '✗'
    print(f"{mark} {purged} purged, {failures} failed")
    return 1 if failures else 0
```

Now wire the CLI. The parser construction moves out of `main()` into `build_arg_parser()` so the argparse regression tests can exercise it.

Before:

```python
def main():
    parser = argparse.ArgumentParser(
        description='Post files with frontmatter to WordPress',
        ...
    )
    parser.add_argument('file', nargs='?', help='File to post')
    ...
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed debug output')

    args = parser.parse_args()

    # Handle --init flag
    if args.init:
```

After:

```python
def build_arg_parser():
    parser = argparse.ArgumentParser(
        description='Post files with frontmatter to WordPress',
        ...
    )
    parser.add_argument('file', nargs='?', help='File to post')
    ...
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed debug output')
    parser.add_argument('--purge', action='store_true',
                        help='Clear the SpinupWP page cache (requires a scope selector)')
    # dest is mandatory here: a bare --file would collide with the positional
    # 'file' argument and silently parse to None.
    parser.add_argument('--file', dest='purge_file', metavar='PATH',
                        help='--purge scope: the page published from this file')
    parser.add_argument('--site', dest='purge_site', nargs='?', const='', metavar='KEY',
                        help='--purge scope: one site (network key, or bare for a single site)')
    parser.add_argument('--network', dest='purge_network', action='store_true',
                        help='--purge scope: every site in the network')
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    # Handle --purge flag
    if args.purge:
        sys.exit(handle_purge(args))

    # Handle --init flag
    if args.init:
```

The `...` above stands for the existing arguments and epilog, which are unchanged - do not retype or reflow them. Everything from `if args.init:` onward stays exactly as it is. The `--purge` dispatch goes first among the standalone actions purely for readability; the flags are independent, so order does not affect behavior.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_wp_post.py -k "HandlePurge or PurgeArgparseWiring or MainPurgeDispatch" -v`
Expected: PASS, 14 tests.

Run the full suite, since `main()` was restructured:

Run: `python3 -m pytest tests/ -q`
Expected: PASS, no regressions.

Smoke-test the real CLI against the live network in test mode, which spawns no subprocess:

Run: `cd ~/projects/payperfax-content && python3 ~/projects/wp-poster/wp-post.py --purge --network --test`
Expected: six `[test]` lines, one per site, each ending `spinupwp cache purge-site --url=https://payperfax.com...`

- [ ] **Step 5: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Add --purge action with file, site, and network scopes"
```

---

### Task 6: Documentation, skill, and version bump

**Files:**
- Modify: `README.md`
- Modify: `skills/wp-post/SKILL.md`
- Modify: `.claude-plugin/plugin.json`

**Interfaces:**
- Consumes: the finished CLI from Task 5. No new code.

- [ ] **Step 1: Add the README usage entry**

In `README.md`, in the `## Usage` fenced block, after the `wp-post --config-path` line, add:

```bash
# Clear the SpinupWP page cache
wp-post --purge --file my-file.md      # just that page
wp-post --purge --site de              # one site in a network
wp-post --purge --network              # every site in the network
```

- [ ] **Step 2: Add the README config key**

In `README.md`, in the `### Config File Format` JSON block, add a `wp_cli_alias` entry after `"default_format": "raw",`:

```json
  "wp_cli_alias": "myhost/sites/example.com/files",
```

Then, after the existing sentence `The `ssh` section is optional metadata for external tooling (not used by wp-post directly).`, add:

```markdown
`wp_cli_alias` is required only for `--purge`. A value starting with `@` is a
WP-CLI alias resolved through `~/.wp-cli/config.yml`; anything else is used as
a `wp --ssh=` target, which needs no WP-CLI config at all. Network projects
read it from `network.wp_cli_alias` instead, where it already exists.

For `--purge --file`, config is resolved by walking up from the target file,
not from the working directory, so purging a file in another project always
uses that project's configuration.
```

- [ ] **Step 3: Add the README purge section**

In `README.md`, immediately before the `## Claude Code Skill` heading, add:

```markdown
## Cache purging

`--purge` clears the SpinupWP page cache. It requires exactly one scope:

| Scope                 | Clears                                            |
|-----------------------|---------------------------------------------------|
| `--file <path>`       | the single page published from that file          |
| `--site [key]`        | one site (network key, or bare for a single site) |
| `--network`           | every site in the network                         |

It never runs automatically - the SpinupWP plugin already purges on ordinary
content updates. Reach for it when a change bypassed that, most notably after
MSLS translation linking: those links are written with `wp eval` and
`update_option`, which never fires `save_post`, so the sibling-language pages
keep serving a stale language switcher. `--purge --file` clears only the page
you name, so use `--site` or `--network` after linking translations.

Add `--test` to print the commands without running them. A failure on one site
is reported and the remaining sites are still purged; the exit code is 1 if any
target failed.

Cloudflare is deliberately not purged. These sites serve
`cf-cache-status: DYNAMIC` for HTML, so there is nothing cached at the edge to
clear; see `docs/superpowers/specs/2026-07-27-cache-purge-design.md`.
```

- [ ] **Step 4: Update the skill**

`skills/wp-post/SKILL.md` uses numbered `### N.` subsections under `## Workflow`, currently ending at `### 7. Translation linking (MSLS multisite)` (line 108), followed by `## Configuration` (line 142).

Insert this as a new section 8, immediately after section 7 and before `## Configuration`. Placing it directly after the MSLS section is deliberate: that is the case where purging actually matters.

```markdown
### 8. Clearing the cache

After publishing, the SpinupWP plugin purges the page cache on its own, so no
action is normally needed. Use `wp-post --purge` when a change bypassed that:

    wp-post --purge --file content/de/my-post/index.md   # one page
    wp-post --purge --site de                            # one site
    wp-post --purge --network                            # every site

Most importantly, run `--purge --site` or `--purge --network` after publishing
a post with `translation_set`. MSLS links are written in a way that does not
trigger WordPress's own cache invalidation, so sibling-language pages keep
serving a stale language switcher until purged.

Requires `wp_cli_alias` in `.wp-poster.json`.
```

Then, in the `## Configuration` section of the same file, add `wp_cli_alias` to the documented keys:

```markdown
- `wp_cli_alias` - required only for `--purge`. A value starting with `@` is a
  WP-CLI alias; anything else is used as a `wp --ssh=` target. Network projects
  read `network.wp_cli_alias` instead.
```

- [ ] **Step 5: Bump the plugin version**

`CLAUDE.md` requires a version bump for any change to `skills/`. In `.claude-plugin/plugin.json`, change `"version": "1.10.0"` to `"version": "1.11.0"`.

- [ ] **Step 6: Verify and commit**

Run: `python3 -m pytest tests/ -q`
Expected: PASS.

Run: `python3 -c "import json; print(json.load(open('.claude-plugin/plugin.json'))['version'])"`
Expected: `1.11.0`

```bash
git add README.md skills/wp-post/SKILL.md .claude-plugin/plugin.json
git commit -m "Document --purge and bump plugin to 1.11.0"
git push origin master
```

- [ ] **Step 7: Close out the issue**

```bash
gh issue comment 16 --body "Implemented. See \`docs/superpowers/plans/2026-07-27-cache-purge.md\`."
gh issue close 16
```

---

## Post-implementation verification

Against the live payperfax network, after the work is merged:

```bash
cd ~/projects/payperfax-content
python3 ~/projects/wp-poster/wp-post.py --purge --site de --test   # inspect the command
python3 ~/projects/wp-poster/wp-post.py --purge --site de          # run it
curl -sSI -A "Mozilla/5.0" https://payperfax.com/de/impressum/ | grep -i fastcgi-cache
```

Expected: `fastcgi-cache: MISS` on the first request after the purge, then `HIT`
on a second request. That MISS is the proof the purge did real work - it is the
same signal used to establish the baseline in the spec.
