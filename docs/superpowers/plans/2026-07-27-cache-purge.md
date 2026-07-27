# `wp-post --purge` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--purge` action to `wp-post` that clears the SpinupWP page cache for one page, one site in a multisite network, or every site in the network.

**Architecture:** Five module-level functions in `wp-post.py`, wired into `main()` alongside the existing standalone action flags (`--ping`, `--config-path`, `--init`). Target resolution is split from command execution so the whole feature is testable without SSH: `resolve_purge_targets` is a pure function asserted directly, and `spinupwp_purge` is the single `subprocess` mock point. No changes to the `WordPressPost` class, which exists to hold an authenticated REST session that purging does not need.

**Tech Stack:** Python 3, `argparse`, `subprocess`, `pytest` with `unittest.mock`. Purging is performed by the SpinupWP WordPress plugin's WP-CLI commands, reached over SSH.

**Spec:** `docs/superpowers/specs/2026-07-27-cache-purge-design.md`

## Global Constraints

- All code goes in `wp-post.py`. All tests go in `tests/test_wp_post.py`.
- Tests are imported through `tests/conftest.py`, which loads the hyphenated `wp-post.py` as the module `wp_post`. Patch targets are therefore `wp_post.<name>` (e.g. `@patch('wp_post.subprocess.run')`).
- Follow the repo's commit style: plain imperative sentences, no `feat:`/`fix:` prefixes. Examples from `git log`: `Add --ping flag to verify site connection and credentials`, `Treat frontmatter 'id: null' as absent to route new posts to create`.
- Treat a falsy frontmatter `id` (absent, `null`, `0`) as "not published", matching the existing `if frontmatter.get('id'):` idiom at `wp-post.py:522`.
- Never purge Cloudflare. The spec records the measurements showing it caches no HTML on any of these zones, so a purge call would invalidate nothing.
- No retry or backoff on purge failures. Purging is idempotent and cheap to re-run by hand; a retry loop adds failure modes without adding reliability. This is deliberately unlike the MSLS write path.
- Per `CLAUDE.md`, bump the version in `.claude-plugin/plugin.json` when `skills/` changes. Task 5 bumps `1.10.0` -> `1.11.0`.

---

## File Structure

| File                            | Change | Responsibility                                              |
|---------------------------------|--------|-------------------------------------------------------------|
| `wp-post.py`                    | Modify | New purge section (Tasks 1-3), CLI wiring in `main()` (Task 4) |
| `tests/test_wp_post.py`         | Modify | New test classes appended, following existing conventions   |
| `README.md`                     | Modify | Document `--purge` and the `wp_cli_alias` config key        |
| `skills/wp-post/SKILL.md`       | Modify | Teach Claude when to reach for `--purge`                    |
| `.claude-plugin/plugin.json`    | Modify | Version bump required by `CLAUDE.md`                        |

All new code lands in one contiguous section of `wp-post.py`, placed immediately after `write_msls_links` (which ends at line 1135) and before `resolve_format`. That keeps the WP-CLI-over-SSH functions together, since they share a transport concern.

---

### Task 1: Frontmatter helper, error type, and transport resolution

**Files:**
- Modify: `wp-post.py:68-77` (delegate `parse_frontmatter_only`), and insert a new section after line 1135
- Test: `tests/test_wp_post.py` (append)

**Interfaces:**
- Consumes: `load_frontmatter(yaml_text)` (existing, `wp-post.py:53`)
- Produces:
  - `PurgeConfigError(Exception)` - raised for misconfiguration detected before any subprocess runs
  - `read_frontmatter(filepath) -> dict` - frontmatter of a file, `{}` when absent
  - `resolve_wp_cli_transport(config: dict) -> list[str]` - argv prefix, e.g. `['wp', '@payperfax']` or `['wp', '--ssh=dash/sites/dashpadd.com/files']`

`WordPressPost.parse_frontmatter_only` currently duplicates the frontmatter-reading logic and does not use `self`. Task 1 extracts it to a module-level `read_frontmatter` and has the method delegate, so the new purge code and the existing posting code read frontmatter the same way. This is a three-line change confined to code this feature touches; do not retrofit `find_translation_siblings`, which has its own inline copy.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_post.py`:

```python
# ===========================================================================
# Cache purging: transport resolution
# ===========================================================================

read_frontmatter = wp_post.read_frontmatter
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


class TestResolveWpCliTransport:
    def test_network_alias(self):
        config = {'network': {'wp_cli_alias': '@payperfax', 'sites': {}}}
        assert resolve_wp_cli_transport(config) == ['wp', '@payperfax']

    def test_top_level_alias(self):
        assert resolve_wp_cli_transport({'wp_cli_alias': '@dashpadd'}) == ['wp', '@dashpadd']

    def test_ssh_target_becomes_ssh_flag(self):
        config = {'wp_cli_alias': 'dash/sites/dashpadd.com/files'}
        assert resolve_wp_cli_transport(config) == ['wp', '--ssh=dash/sites/dashpadd.com/files']

    def test_network_alias_wins_over_top_level(self):
        config = {'wp_cli_alias': 'ignored', 'network': {'wp_cli_alias': '@net', 'sites': {}}}
        assert resolve_wp_cli_transport(config) == ['wp', '@net']

    def test_missing_alias_raises(self):
        with pytest.raises(PurgeConfigError) as exc:
            resolve_wp_cli_transport({'site_url': 'https://example.com'})
        assert 'wp_cli_alias' in str(exc.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wp_post.py -k "ReadFrontmatter or ResolveWpCliTransport" -v`
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
    nothing and reports the exact key or value to fix.
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


def resolve_wp_cli_transport(config):
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
            "No wp_cli_alias configured. Add one to .wp-poster.json, either as a\n"
            "wp-cli alias resolved through ~/.wp-cli/config.yml:\n"
            '  "wp_cli_alias": "@myalias"\n'
            "or as an ssh target, which needs no wp-cli config at all:\n"
            '  "wp_cli_alias": "myhost/sites/example.com/files"'
        )
    if alias.startswith('@'):
        return ['wp', alias]
    return ['wp', f'--ssh={alias}']
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wp_post.py -k "ReadFrontmatter or ResolveWpCliTransport" -v`
Expected: PASS, 8 tests.

Then run the full suite to confirm the `parse_frontmatter_only` delegation broke nothing:

Run: `python -m pytest tests/ -q`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Add wp-cli transport resolution for cache purging"
```

---

### Task 2: Scope resolution

**Files:**
- Modify: `wp-post.py` (append to the purge section from Task 1)
- Test: `tests/test_wp_post.py` (append)

**Interfaces:**
- Consumes: `read_frontmatter`, `PurgeConfigError` (Task 1); `find_site_for_file(project_root, network_config, filepath)` and `resolve_site_identity(project_root, site_key, site_info)` (existing, `wp-post.py:984` and `wp-post.py:955`)
- Produces: `resolve_purge_targets(scope, value, config, project_root=None) -> list[dict]`, each dict `{'label': str, 'site_url': str, 'post_id': int | None}`. A `post_id` of `None` means "purge this whole site"; an int means "purge just that post".

`scope` is one of `'file'`, `'site'`, `'network'`. `value` is the file path for `'file'`, the site key (or `''`/`None` for "the configured site") for `'site'`, and ignored for `'network'`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_post.py`. These reuse the existing `_scaffold_network_map` helper defined at line 864.

```python
# ===========================================================================
# Cache purging: scope resolution
# ===========================================================================

resolve_purge_targets = wp_post.resolve_purge_targets

_PURGE_SITES = [
    {'key': 'en', 'site_url': 'https://e.com', 'locale': 'en_US', 'blog_id': 1},
    {'key': 'de', 'site_url': 'https://e.com/de', 'locale': 'de_DE', 'blog_id': 3},
]


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
            resolve_purge_targets('network', None, self.SINGLE, None)
        assert '--network' in str(exc.value)

    def test_missing_site_url_raises(self):
        with pytest.raises(PurgeConfigError):
            resolve_purge_targets('site', '', {'wp_cli_alias': '@x'}, None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wp_post.py -k "ResolvePurgeTargets" -v`
Expected: FAIL - `AttributeError: module 'wp_post' has no attribute 'resolve_purge_targets'`.

- [ ] **Step 3: Write the implementation**

Append to the purge section in `wp-post.py`:

```python
def resolve_purge_targets(scope, value, config, project_root=None):
    """Resolve a purge scope to an ordered list of targets.

    scope: 'file' | 'site' | 'network'
    value: file path for 'file'; site key (or '' meaning "the configured
           site") for 'site'; ignored for 'network'.

    Returns [{'label': str, 'site_url': str, 'post_id': int | None}, ...]
    where a post_id of None means "purge this whole site".

    Every failure mode raises PurgeConfigError naming what to fix, rather than
    guessing at a target - purging the wrong blog is worse than not purging.
    """
    network = config.get('network') or {}
    sites = network.get('sites') or {}

    if scope == 'network':
        if not sites:
            raise PurgeConfigError(
                "--network needs a network config, but the config that was loaded "
                "has no 'network' key. Use --site for a single-site project."
            )
        targets = []
        for site_key, site_info in sites.items():
            identity = resolve_site_identity(project_root, site_key, site_info)
            targets.append({
                'label': site_key,
                'site_url': identity['site_url'],
                'post_id': None,
            })
        return targets

    if scope == 'site':
        if not sites:
            site_url = config.get('site_url')
            if not site_url:
                raise PurgeConfigError("No site_url in config; cannot resolve --site.")
            return [{'label': site_url, 'site_url': site_url, 'post_id': None}]
        valid = ', '.join(sorted(sites))
        if not value:
            raise PurgeConfigError(
                f"--site requires a site key on a network project. Valid keys: {valid}"
            )
        if value not in sites:
            raise PurgeConfigError(f"Unknown site '{value}'. Valid keys: {valid}")
        identity = resolve_site_identity(project_root, value, sites[value])
        return [{'label': value, 'site_url': identity['site_url'], 'post_id': None}]

    # scope == 'file'
    frontmatter = read_frontmatter(value)
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
                f"{value} is not inside any configured content_path ({configured}), "
                "so its site could not be determined."
            )
        identity = resolve_site_identity(project_root, site_key, site_info)
        return [{
            'label': f'{site_key} #{post_id}',
            'site_url': identity['site_url'],
            'post_id': post_id,
        }]

    site_url = config.get('site_url')
    if not site_url:
        raise PurgeConfigError("No site_url in config; cannot resolve --file.")
    return [{'label': f'#{post_id}', 'site_url': site_url, 'post_id': post_id}]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wp_post.py -k "ResolvePurgeTargets" -v`
Expected: PASS, 13 tests.

- [ ] **Step 5: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Resolve purge scopes to SpinupWP targets"
```

---

### Task 3: Command construction and execution

**Files:**
- Modify: `wp-post.py` (append to the purge section)
- Test: `tests/test_wp_post.py` (append)

**Interfaces:**
- Consumes: `resolve_wp_cli_transport` output shape (Task 1), target dicts (Task 2), `_PURGE_TIMEOUT` (Task 1)
- Produces:
  - `build_purge_command(transport, target) -> list[str]`
  - `spinupwp_purge(transport, target, timeout=_PURGE_TIMEOUT) -> tuple[bool, str | None]` returning `(ok, error)`

`build_purge_command` is separate from `spinupwp_purge` so `--test` mode can print the exact command without running it, and so command shape is asserted directly rather than through mock call inspection.

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
        ok, error = spinupwp_purge(_TRANSPORT, _SITE_TARGET)
        assert ok is True
        assert error is None

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

    @patch('wp_post.subprocess.run')
    def test_runs_the_built_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')
        spinupwp_purge(_TRANSPORT, _POST_TARGET)
        assert mock_run.call_args[0][0] == build_purge_command(_TRANSPORT, _POST_TARGET)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wp_post.py -k "BuildPurgeCommand or SpinupwpPurge" -v`
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
        return False, f"wp timed out after {timeout}s"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip()
        return False, f"wp exited {result.returncode}" + (f": {detail}" if detail else "")
    return True, None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wp_post.py -k "BuildPurgeCommand or SpinupwpPurge" -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Build and run SpinupWP purge commands"
```

---

### Task 4: Orchestration and CLI wiring

**Files:**
- Modify: `wp-post.py` (append `handle_purge` to the purge section; add argparse flags and dispatch in `main()`)
- Test: `tests/test_wp_post.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1-3, plus `find_network_config(filepath)` (existing, `wp-post.py:935`) and `load_config()` (existing, `wp-post.py:1179`)
- Produces: `handle_purge(args) -> int` (process exit code), called from `main()`

**CRITICAL - argparse dest collision.** `main()` already defines a positional `file` argument (`wp-post.py`, `parser.add_argument('file', nargs='?', ...)`). Adding `--file` without an explicit `dest` silently collides: argparse raises no error, and `wp-post --purge --file X` parses to `file=None`, losing the value entirely. Verified behavior. `--file` MUST be declared as `dest='purge_file'`. `--site` and `--network` get `dest='purge_site'` and `dest='purge_network'` for symmetry.

`--site` uses `nargs='?', const=''` so that three states are distinguishable: flag absent (`None`), flag given bare (`''`, meaning "the configured site"), and flag given a key (`'de'`).

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
    @patch('wp_post.subprocess.run')
    def test_network_purges_every_site_and_exits_zero(self, mock_run, tmp_path, monkeypatch):
        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        (root / 'anchor.md').write_text('x', encoding='utf-8')
        monkeypatch.chdir(root)

        code = handle_purge(_PurgeArgs(purge_network=True))
        assert code == 0
        assert mock_run.call_count == 2
        urls = [c[0][0][-1] for c in mock_run.call_args_list]
        assert urls == ['--url=https://e.com', '--url=https://e.com/de']

    @patch('wp_post.subprocess.run')
    def test_one_failure_does_not_abort_the_rest(self, mock_run, tmp_path, monkeypatch):
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout='', stderr='boom'),
            MagicMock(returncode=0, stdout='', stderr=''),
        ]
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        monkeypatch.chdir(root)

        code = handle_purge(_PurgeArgs(purge_network=True))
        assert code == 1
        assert mock_run.call_count == 2

    @patch('wp_post.subprocess.run')
    def test_file_scope_purges_the_post(self, mock_run, tmp_path, monkeypatch):
        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        f = root / 'de' / 'content' / 'p' / 'index.md'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('---\ntitle: T\nid: 412\n---\nbody', encoding='utf-8')
        monkeypatch.chdir(root)

        code = handle_purge(_PurgeArgs(purge_file=str(f)))
        assert code == 0
        cmd = mock_run.call_args[0][0]
        assert cmd[-3:] == ['purge-post', '412', '--url=https://e.com/de']

    @patch('wp_post.subprocess.run')
    def test_test_mode_runs_nothing(self, mock_run, tmp_path, monkeypatch, capsys):
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        monkeypatch.chdir(root)

        code = handle_purge(_PurgeArgs(purge_network=True, test=True))
        assert code == 0
        mock_run.assert_not_called()
        assert 'purge-site' in capsys.readouterr().out

    @patch('wp_post.subprocess.run')
    def test_config_error_exits_one_without_running(self, mock_run, tmp_path, monkeypatch):
        root = _scaffold_network_map(tmp_path, _PURGE_SITES)
        f = root / 'de' / 'content' / 'unpublished.md'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('---\ntitle: T\n---\nbody', encoding='utf-8')
        monkeypatch.chdir(root)

        code = handle_purge(_PurgeArgs(purge_file=str(f)))
        assert code == 1
        mock_run.assert_not_called()

    def test_no_scope_selector_exits_one(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert handle_purge(_PurgeArgs()) == 1

    def test_two_scope_selectors_exit_one(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert handle_purge(_PurgeArgs(purge_site='de', purge_network=True)) == 1


class TestPurgeArgparseWiring:
    def test_dash_dash_file_does_not_collide_with_positional(self):
        """Regression: --file without an explicit dest silently nulls the value."""
        parser = wp_post.build_arg_parser()
        args = parser.parse_args(['--purge', '--file', 'x.md'])
        assert args.purge_file == 'x.md'
        assert args.file is None

    def test_positional_file_still_parses(self):
        parser = wp_post.build_arg_parser()
        args = parser.parse_args(['post.md'])
        assert args.file == 'post.md'
        assert args.purge_file is None

    def test_bare_site_flag_is_empty_string(self):
        parser = wp_post.build_arg_parser()
        assert parser.parse_args(['--purge', '--site']).purge_site == ''

    def test_site_flag_with_key(self):
        parser = wp_post.build_arg_parser()
        assert parser.parse_args(['--purge', '--site', 'de']).purge_site == 'de'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wp_post.py -k "HandlePurge or PurgeArgparseWiring" -v`
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

    # A network project is identified by walking up from the target file, or
    # from the working directory for the site/network scopes.
    anchor = args.purge_file or os.path.join(os.getcwd(), '_')
    project_root, network_config = find_network_config(anchor)
    config = network_config if network_config else load_config()

    try:
        transport = resolve_wp_cli_transport(config)
        targets = resolve_purge_targets(scope, value, config, project_root)
    except PurgeConfigError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1

    noun = 'site' if len(targets) == 1 else 'sites'
    print(f"Purging SpinupWP cache ({len(targets)} {noun})")

    failures = 0
    for target in targets:
        cmd = build_purge_command(transport, target)
        if args.test:
            print(f"  [test] {target['label']:<12} {' '.join(cmd)}")
            continue
        if args.verbose:
            print(f"  → {' '.join(cmd)}")
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

Now wire the CLI. In `main()`, the parser construction must be extracted into a reusable `build_arg_parser()` so the argparse regression tests can exercise it. Change the opening of `main()` from:

```python
def main():
    parser = argparse.ArgumentParser(
```

to:

```python
def build_arg_parser():
    parser = argparse.ArgumentParser(
```

Then, immediately after the existing `parser.add_argument('--verbose', ...)` line, add:

```python
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
```

The full restructure, for clarity. Before:

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
    # ... the four new --purge arguments from above ...
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

Run: `python -m pytest tests/test_wp_post.py -k "HandlePurge or PurgeArgparseWiring" -v`
Expected: PASS, 11 tests.

Run the full suite, since `main()` was restructured:

Run: `python -m pytest tests/ -q`
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

### Task 5: Documentation, skill, and version bump

**Files:**
- Modify: `README.md`
- Modify: `skills/wp-post/SKILL.md`
- Modify: `.claude-plugin/plugin.json`

**Interfaces:**
- Consumes: the finished CLI from Task 4. No new code.

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

Then replace the sentence `The `ssh` section is optional metadata for external tooling (not used by wp-post directly).` with:

```markdown
The `ssh` section is optional metadata for external tooling (not used by wp-post directly).

`wp_cli_alias` is required only for `--purge`. A value starting with `@` is a
WP-CLI alias resolved through `~/.wp-cli/config.yml`; anything else is used as
a `wp --ssh=` target, which needs no WP-CLI config at all. Network projects
read it from `network.wp_cli_alias` instead, where it already exists.
```

- [ ] **Step 3: Add the README purge section**

In `README.md`, immediately before the `## Claude Code Skill` heading, add:

```markdown
## Cache purging

`--purge` clears the SpinupWP page cache. It requires exactly one scope:

| Scope                 | Clears                                       |
|-----------------------|----------------------------------------------|
| `--file <path>`       | the single page published from that file     |
| `--site [key]`        | one site (network key, or bare for a single site) |
| `--network`           | every site in the network                    |

It never runs automatically - the SpinupWP plugin already purges on ordinary
content updates. Reach for it when a change bypassed that, most notably after
MSLS translation linking: those links are written with `wp eval` and
`update_option`, which never fires `save_post`, so the sibling-language pages
keep serving a stale language switcher. `--purge --file` clears only the page
you name, so use `--site` or `--network` after linking translations.

Add `--test` to print the commands without running them.

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

Run: `python -m pytest tests/ -q`
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

Against the live payperfax network, after the branch is merged:

```bash
cd ~/projects/payperfax-content
python3 ~/projects/wp-poster/wp-post.py --purge --site de --test   # inspect the command
python3 ~/projects/wp-poster/wp-post.py --purge --site de          # run it
curl -sSI -A "Mozilla/5.0" https://payperfax.com/de/impressum/ | grep -i fastcgi-cache
```

Expected: `fastcgi-cache: MISS` on the first request after the purge, then `HIT`
on a second request. That MISS is the proof the purge did real work - it is the
same signal used to establish the baseline in the spec.
