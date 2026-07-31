# Language-Sensitive Callout Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Callout labels come from a translation table shipped with wp-poster, keyed by the destination site's locale, defaulting to English.

**Architecture:** `callouts.py` gains `_LABELS` (eleven languages x eight types) and `resolve_lang()`, which maps a WordPress locale to a table key. `merge_config()` seeds each type's label from the table instead of from `DEFAULT_CONFIG`, and the `label` config key is removed. The locale threads down the existing injection chain - `wp-post.py` resolves it from `network.sites`, hands it to `WordPressPost`, which forwards it to `GutenbergConverter`, which forwards it to `callout_plugin` - mirroring how `callout_config` already travels.

**Tech Stack:** Python 3, mistune 3, pytest.

**Spec:** `docs/superpowers/specs/2026-07-31-callout-labels-i18n-design.md`

## Global Constraints

- Table keys are lowercase: `en`, `de`, `es`, `fr`, `it`, `ja`, `ko`, `zh`, `th`, `ar`, `he`. Every one covers all eight types in `CALLOUT_TYPES`.
- An unknown-but-valid language warns once and falls back to English. A missing, empty, or non-string locale falls back to English silently - that is the documented default, not a failure.
- No callout failure may fail a publish. `resolve_lang()` never raises, whatever it is handed.
- `label` is not a config key. `background`, `padding`, `color`, and `icon` keep their overrides unchanged.
- Locale resolution reads on-disk config only. It must not make a network request, because `--test` uses the same path.
- Run tests with `python3 -m pytest` from the repo root. Baseline before this work: 389 passing.
- Work happens on a `callout-i18n` branch off `master`.
- Source files are `callouts.py`, `gutenberg.py`, `wp-post.py` at the repo root - there is no `src/` directory.

---

### Task 1: Translation table and language resolution

Pure additions to `callouts.py` with no callers yet: the eleven-language table and the locale-to-key resolver. Nothing else changes, so the existing 389 tests must still pass at the end of this task.

**Files:**
- Modify: `callouts.py` (add after `DEFAULT_CONFIG`, around line 139)
- Test: `tests/test_callouts.py`

**Interfaces:**
- Consumes: `CALLOUT_TYPES`, `_default_warn` - both already exist in `callouts.py`.
- Produces:
  - `_LABELS: dict[str, dict[str, str]]` - table key -> type name -> label
  - `resolve_lang(locale: str | None, warn: callable | None = None) -> str` - returns a key present in `_LABELS`, always

- [ ] **Step 1: Write the failing test**

Append to `tests/test_callouts.py`:

```python
class TestResolveLang:
    def test_locale_with_region_takes_the_language(self):
        assert callouts.resolve_lang("de_DE") == "de"

    def test_bare_language_locale(self):
        assert callouts.resolve_lang("ja") == "ja"

    def test_hyphenated_locale_is_normalised(self):
        assert callouts.resolve_lang("zh-TW") == "zh"

    def test_traditional_chinese_falls_back_to_the_language(self):
        # No zh_tw entry ships, so zh_TW takes Simplified. The two-step
        # lookup means adding one later needs no resolver change.
        assert callouts.resolve_lang("zh_TW") == "zh"

    def test_unknown_language_warns_and_uses_english(self):
        warnings = []
        assert callouts.resolve_lang("pt_BR", warn=warnings.append) == "en"
        assert len(warnings) == 1
        assert "'pt'" in warnings[0]

    def test_english_locale_does_not_warn(self):
        warnings = []
        assert callouts.resolve_lang("en_US", warn=warnings.append) == "en"
        assert warnings == []

    def test_none_is_english_without_a_warning(self):
        warnings = []
        assert callouts.resolve_lang(None, warn=warnings.append) == "en"
        assert warnings == []

    def test_non_string_locale_is_english_without_raising(self):
        assert callouts.resolve_lang(42) == "en"

    def test_empty_locale_is_english_without_a_warning(self):
        warnings = []
        assert callouts.resolve_lang("   ", warn=warnings.append) == "en"
        assert warnings == []

    def test_separator_only_locale_is_english_without_a_warning(self):
        warnings = []
        assert callouts.resolve_lang("_", warn=warnings.append) == "en"
        assert warnings == []


class TestLabelTable:
    def test_every_language_covers_every_type(self):
        for lang, labels in callouts._LABELS.items():
            assert set(labels) == set(callouts.CALLOUT_TYPES), lang

    def test_all_eleven_languages_ship(self):
        assert set(callouts._LABELS) == {
            "en", "de", "es", "fr", "it", "ja", "ko", "zh", "th", "ar", "he"
        }

    def test_english_labels(self):
        assert callouts._LABELS["en"]["warning"] == "Warning"
        assert callouts._LABELS["en"]["bookmark"] == "Read next"

    def test_german_labels(self):
        assert callouts._LABELS["de"]["warning"] == "Warnung"
        assert callouts._LABELS["de"]["bookmark"] == "Weiterlesen"

    def test_japanese_note_is_the_formal_term(self):
        # 注記, not メモ - payperfax's content is registry and filing
        # procedure, which reads formal.
        assert callouts._LABELS["ja"]["note"] == "注記"

    def test_italian_warning_is_avvertenza(self):
        # Avviso reads as "notice"; Avvertenza carries the warning sense.
        assert callouts._LABELS["it"]["warning"] == "Avvertenza"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_callouts.py::TestResolveLang -v`
Expected: FAIL with `AttributeError: module 'callouts' has no attribute 'resolve_lang'`

- [ ] **Step 3: Write minimal implementation**

In `callouts.py`, insert after `DEFAULT_CONFIG` (which ends at line 139) and before `def _default_warn`:

```python
# Labels are the only English wp-poster puts on the page itself - FAQ
# questions are authored in the post and bookmark cards come from
# WordPress, so both are already in the right language. Eleven languages
# ship: the six payperfax publishes, plus five ahead of need.
#
# `bookmark` is a slot label, not a phrase to translate. The slot means
# "one related post the author picked", and each language uses its own
# blog-native label for it. A literal "Read next" everywhere (次に読む,
# Als Nächstes lesen) would be accurate and read as machine output.
_LABELS = {
    "en": {
        "note": "Note", "tip": "Tip", "important": "Important",
        "warning": "Warning", "caution": "Caution", "summary": "In short",
        "faq": "Frequently asked questions", "bookmark": "Read next",
    },
    "de": {
        "note": "Hinweis", "tip": "Tipp", "important": "Wichtig",
        "warning": "Warnung", "caution": "Vorsicht", "summary": "Kurz gesagt",
        "faq": "Häufige Fragen", "bookmark": "Weiterlesen",
    },
    "es": {
        "note": "Nota", "tip": "Consejo", "important": "Importante",
        "warning": "Advertencia", "caution": "Precaución",
        "summary": "En resumen", "faq": "Preguntas frecuentes",
        "bookmark": "Sigue leyendo",
    },
    "fr": {
        "note": "Note", "tip": "Astuce", "important": "Important",
        "warning": "Avertissement", "caution": "Attention",
        "summary": "En bref", "faq": "Questions fréquentes",
        "bookmark": "À lire ensuite",
    },
    "it": {
        "note": "Nota", "tip": "Suggerimento", "important": "Importante",
        "warning": "Avvertenza", "caution": "Attenzione",
        "summary": "In breve", "faq": "Domande frequenti",
        "bookmark": "Leggi anche",
    },
    "ja": {
        "note": "注記", "tip": "ヒント", "important": "重要",
        "warning": "警告", "caution": "注意", "summary": "要点",
        "faq": "よくある質問", "bookmark": "あわせて読みたい",
    },
    "ko": {
        "note": "참고", "tip": "팁", "important": "중요",
        "warning": "경고", "caution": "주의", "summary": "요약",
        "faq": "자주 묻는 질문", "bookmark": "이어서 읽기",
    },
    "zh": {
        "note": "备注", "tip": "提示", "important": "重要",
        "warning": "警告", "caution": "注意", "summary": "摘要",
        "faq": "常见问题", "bookmark": "延伸阅读",
    },
    "th": {
        "note": "หมายเหตุ", "tip": "เคล็ดลับ", "important": "สำคัญ",
        "warning": "คำเตือน", "caution": "ข้อควรระวัง", "summary": "สรุป",
        "faq": "คำถามที่พบบ่อย", "bookmark": "อ่านต่อ",
    },
    "ar": {
        "note": "ملاحظة", "tip": "نصيحة", "important": "مهم",
        "warning": "تحذير", "caution": "تنبيه", "summary": "باختصار",
        "faq": "الأسئلة الشائعة", "bookmark": "اقرأ أيضًا",
    },
    "he": {
        "note": "הערה", "tip": "טיפ", "important": "חשוב",
        "warning": "אזהרה", "caution": "זהירות", "summary": "בקצרה",
        "faq": "שאלות נפוצות", "bookmark": "להמשך קריאה",
    },
}
```

Then add the resolver immediately after `_default_warn` (which ends at line 144 before this task's insert):

```python
def resolve_lang(locale, warn=None):
    """Table key for a WordPress locale. Always returns a key in _LABELS.

    Tries the full locale before its language prefix, so a `zh_tw` table
    can be added later without touching this function. A locale whose
    language has no entry warns and takes English; a missing or malformed
    locale takes English silently, because that is the documented default
    rather than a failure.
    """
    if not isinstance(locale, str):
        return "en"
    normalised = locale.strip().lower().replace("-", "_")
    if normalised in _LABELS:
        return normalised
    prefix = normalised.split("_")[0]
    if not prefix:
        return "en"
    if prefix in _LABELS:
        return prefix
    (warn or _default_warn)(
        f"no callout labels for language '{prefix}'; using English"
    )
    return "en"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_callouts.py -v`
Expected: PASS, including all pre-existing tests in the file - this task adds nothing that changes existing behaviour.

Then run the full suite: `python3 -m pytest -q`
Expected: 389 baseline tests plus the 15 added here, all passing.

- [ ] **Step 5: Commit**

```bash
git add callouts.py tests/test_callouts.py
git commit -m "Add callout label translations for eleven languages"
```

---

### Task 2: merge_config seeds labels from the table

`merge_config()` gains a `locale` parameter and takes each type's label from `_LABELS`. The `label` config key is removed: it is now an unrecognised key that warns, not a silent no-op. Existing tests that exercised label overrides are migrated to `color`.

**Files:**
- Modify: `callouts.py:118-139` (`DEFAULT_CONFIG`), `callouts.py:154-205` (`merge_config`)
- Test: `tests/test_callouts.py:37-66` (migrate), `tests/test_callouts.py:96-100` (adjust), `tests/test_wp_post.py:2893-2900` (migrate)

**Interfaces:**
- Consumes: `_LABELS`, `resolve_lang(locale, warn)` from Task 1.
- Produces: `merge_config(user_config: dict | None = None, warn: callable | None = None, locale: str | None = None) -> dict`. The returned shape is unchanged - each type still has `label`, `color`, `icon` - but `label` is now sourced from the table. `DEFAULT_CONFIG["types"][name]` no longer contains a `label` key.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_callouts.py`:

```python
class TestMergeConfigLocale:
    def test_german_locale_yields_german_labels(self):
        merged = callouts.merge_config(None, locale="de_DE")
        assert merged["types"]["warning"]["label"] == "Warnung"
        assert merged["types"]["bookmark"]["label"] == "Weiterlesen"

    def test_no_locale_yields_english(self):
        merged = callouts.merge_config(None)
        assert merged["types"]["warning"]["label"] == "Warning"

    def test_unknown_locale_yields_english_and_warns(self):
        warnings = []
        merged = callouts.merge_config(None, warn=warnings.append, locale="pt_BR")
        assert merged["types"]["warning"]["label"] == "Warning"
        assert len(warnings) == 1
        assert "'pt'" in warnings[0]

    def test_locale_does_not_affect_colour(self):
        merged = callouts.merge_config(None, locale="ja")
        assert merged["types"]["warning"]["color"] == "#9a6700"

    def test_config_overrides_still_apply_under_a_locale(self):
        merged = callouts.merge_config(
            {"types": {"warning": {"color": "primary"}}}, locale="de_DE"
        )
        assert merged["types"]["warning"]["color"] == "primary"
        assert merged["types"]["warning"]["label"] == "Warnung"

    def test_label_key_in_config_warns_and_is_ignored(self):
        warnings = []
        merged = callouts.merge_config(
            {"types": {"note": {"label": "Hinweis"}}}, warn=warnings.append
        )
        assert merged["types"]["note"]["label"] == "Note"
        assert len(warnings) == 1
        assert "label" in warnings[0]

    def test_defaults_carry_no_label(self):
        # _LABELS is the single source of truth for label text.
        assert "label" not in callouts.DEFAULT_CONFIG["types"]["note"]
```

Migrate the six existing tests that used `label` as an override. Replace `tests/test_callouts.py:37-44` with:

```python
    def test_partial_override_leaves_other_fields(self):
        merged = callouts.merge_config({"types": {"note": {"color": "primary"}}})
        assert merged["types"]["note"]["color"] == "primary"
        assert merged["types"]["note"]["icon"] == callouts.DEFAULT_CONFIG["types"]["note"]["icon"]

    def test_partial_override_leaves_other_types(self):
        merged = callouts.merge_config({"types": {"note": {"color": "primary"}}})
        assert merged["types"]["tip"]["color"] == callouts.DEFAULT_CONFIG["types"]["tip"]["color"]
```

Replace `tests/test_callouts.py:50-66` with:

```python
    def test_unknown_type_warns_and_is_ignored(self):
        warnings = []
        merged = callouts.merge_config(
            {"types": {"sidebar": {"color": "primary"}}}, warn=warnings.append
        )
        assert "sidebar" not in merged["types"]
        assert len(warnings) == 1
        assert "sidebar" in warnings[0]

    def test_type_name_matching_is_case_insensitive(self):
        merged = callouts.merge_config({"types": {"NOTE": {"color": "primary"}}})
        assert merged["types"]["note"]["color"] == "primary"

    def test_defaults_are_not_mutated_by_merge(self):
        merged = callouts.merge_config({"types": {"note": {"color": "primary"}}})
        merged["types"]["note"]["color"] = "secondary"
        assert callouts.DEFAULT_CONFIG["types"]["note"]["color"] == "#0969da"
```

`tests/test_callouts.py:96-100` (`test_null_type_override_warns_and_is_skipped`) asserts `merged["types"]["note"]["label"] == "Note"` and still passes unchanged, because English is the default. Leave it.

`tests/test_wp_post.py` has a second label-override test that breaks here, not in Task 3 - it goes through `WordPressPost`, not `GutenbergConverter`. Replace `tests/test_wp_post.py:2893-2900`:

```python
    def test_callout_config_reaches_the_converter(self, md_file):
        poster = wp_post.WordPressPost(
            "https://example.com", "u", "p",
            callout_config={"types": {"note": {"label": "Hinweis"}}},
        )
        path = md_file({"title": "T"}, "> [!NOTE]\n> Body.")
        _, content = poster.parse_markdown_file(path)
        assert "Hinweis</strong>" in content
```

with the same assertion expressed through a key that is still configurable:

```python
    def test_callout_config_reaches_the_converter(self, md_file):
        poster = wp_post.WordPressPost(
            "https://example.com", "u", "p",
            callout_config={"types": {"note": {"color": "primary"}}},
        )
        path = md_file({"title": "T"}, "> [!NOTE]\n> Body.")
        _, content = poster.parse_markdown_file(path)
        assert "var:preset|color|primary" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_callouts.py -v`
Expected: `TestMergeConfigLocale` fails with `TypeError: merge_config() got an unexpected keyword argument 'locale'`, and `test_defaults_carry_no_label` fails because `DEFAULT_CONFIG` still holds labels.

- [ ] **Step 3: Write minimal implementation**

In `callouts.py`, strip `label` from every entry in `DEFAULT_CONFIG["types"]` (lines 121-138), leaving:

```python
    "types": {
        "note": {"color": "#0969da", "icon": None},
        "tip": {"color": "#1a7f37", "icon": None},
        "important": {"color": "#8250df", "icon": None},
        "warning": {"color": "#9a6700", "icon": None},
        "caution": {"color": "#d1242f", "icon": None},
        "summary": {"color": "primary-alt-accent", "icon": None},
        "faq": {"color": "primary-alt-accent", "icon": None},
        "bookmark": {"color": "primary-alt-accent", "icon": None},
    },
```

Change the `merge_config` signature and the block that builds `merged` (lines 154-166):

```python
def merge_config(user_config=None, warn=None, locale=None):
    """User config merged over the built-in defaults, for one language.

    Every field is optional; a partial override touches only what it
    names. Config arrives from hand-edited JSON, so every value may be
    the wrong type - this function never raises, it warns and falls
    back, because a bad config must not fail a publish.

    Labels are not configurable. They come from `_LABELS`, keyed by the
    destination site's locale, because a network project publishes every
    language from one root config and has nowhere to write a per-language
    label.
    """
    warn = warn or _default_warn
    labels = _LABELS[resolve_lang(locale, warn)]
    merged = {
        "background": DEFAULT_CONFIG["background"],
        "padding": DEFAULT_CONFIG["padding"],
        "types": {
            name: dict(spec, label=labels[name])
            for name, spec in DEFAULT_CONFIG["types"].items()
        },
    }
```

Delete the `label` line at what is currently `callouts.py:197`:

```python
        target["label"] = _clean_str(overrides.get("label"), target["label"])
```

and replace it with a rejection, so a stale config is reported rather than silently ignored:

```python
        if "label" in overrides:
            warn(
                f"callouts.types.{name}.label is no longer configurable; "
                "labels come from the site's locale"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_callouts.py tests/test_wp_post.py -v`
Expected: PASS.

Run: `python3 -m pytest -q`
Expected: exactly one failure - `tests/test_callouts.py:233` `test_label_override_is_used`, which drives `GutenbergConverter` and is rewired in Task 3. Any other failure means a label-override test was missed; find it with `grep -rn '"label"' tests/` and migrate it here rather than carrying it forward.

- [ ] **Step 5: Commit**

```bash
git add callouts.py tests/test_callouts.py tests/test_wp_post.py
git commit -m "Seed callout labels from the translation table, drop the label key"
```

---

### Task 3: Thread the locale to the plugin and converter

`callout_plugin` and `GutenbergConverter` gain a `locale` parameter and pass it to `merge_config`. This closes the last failure from Task 2.

**Files:**
- Modify: `callouts.py:406-408` (`callout_plugin`), `gutenberg.py:317-338` (`GutenbergConverter.__init__`)
- Test: `tests/test_callouts.py:233-237` (replace), plus new cases

**Interfaces:**
- Consumes: `merge_config(user_config, warn, locale)` from Task 2.
- Produces:
  - `callout_plugin(config: dict | None = None, bookmark_resolver: callable | None = None, warn: callable | None = None, locale: str | None = None)`
  - `GutenbergConverter(image_handler=None, callout_config=None, bookmark_resolver=None, locale=None)`

  Both keep `locale` last so every existing positional call site stays valid.

- [ ] **Step 1: Write the failing test**

Replace `tests/test_callouts.py:233-237` (`test_label_override_is_used`) with:

```python
    def test_label_config_no_longer_overrides(self):
        cfg = {"types": {"note": {"label": "Hinweis"}}}
        result = convert("> [!NOTE]\n> A note.", callout_config=cfg)
        assert "Note</strong>" in result
        assert "Hinweis" not in result

    def test_locale_selects_the_label(self):
        result = convert("> [!NOTE]\n> A note.", locale="de_DE")
        assert "Hinweis</strong>" in result
        assert "Note</strong>" not in result

    def test_locale_reaches_the_faq_label(self):
        # The assertion must be the generated label, not the authored
        # question - "Frage?" is body text and would pass with an English
        # label sitting right above it.
        md = "> [!FAQ]\n> **Frage?**\n> Antwort."
        result = convert(md, locale="de_DE")
        assert "Häufige Fragen</strong>" in result
        assert "Frequently asked questions" not in result

    def test_locale_reaches_the_unresolved_bookmark_anchor(self):
        result = convert("> [!BOOKMARK]\n> /ein-artikel/", locale="de_DE")
        assert ">Weiterlesen</a>" in result

    def test_no_locale_still_renders_english(self):
        result = convert("> [!WARNING]\n> Careful.")
        assert "Warning</strong>" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_callouts.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'locale'` on the locale cases.

- [ ] **Step 3: Write minimal implementation**

In `callouts.py`, change `callout_plugin` (lines 406-408) from:

```python
def callout_plugin(config=None, bookmark_resolver=None, warn=None):
    """Build a mistune plugin rendering callouts with this configuration."""
    cfg = merge_config(config, warn=warn)
```

to:

```python
def callout_plugin(config=None, bookmark_resolver=None, warn=None, locale=None):
    """Build a mistune plugin rendering callouts with this configuration.

    `locale` is the destination site's WordPress locale; labels are
    resolved from it once, here, so an unknown language warns once per
    conversion rather than once per callout.
    """
    cfg = merge_config(config, warn=warn, locale=locale)
```

In `gutenberg.py`, change `GutenbergConverter.__init__` (line 317) to add the parameter, document it, and forward it:

```python
    def __init__(self, image_handler=None, callout_config=None,
                 bookmark_resolver=None, locale=None):
        """
        Initialize converter.

        Args:
            image_handler: Optional callable(image_url) -> (final_url, media_id)
                          If None, images are left as-is with no media ID.
            callout_config: Optional dict merged over callouts.DEFAULT_CONFIG.
            bookmark_resolver: Optional callable(target) -> dict | None used by
                          [!BOOKMARK] callouts. If None, bookmarks degrade to
                          a plain link card without a network request.
            locale: Optional WordPress locale ("de_DE", "ja") selecting the
                          callout label language. None means English.
        """
```

and in the `plugins=[...]` list at line 337:

```python
                callout_plugin(callout_config, bookmark_resolver, locale=locale),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest -q`
Expected: all passing, including everything from Tasks 1 and 2.

- [ ] **Step 5: Commit**

```bash
git add callouts.py gutenberg.py tests/test_callouts.py
git commit -m "Thread the site locale to the callout plugin"
```

---

### Task 4: wp-post resolves and carries the site locale

`wp-post.py` learns the destination site's locale from `network.sites` and hands it to the converter. A single helper serves both the publish path and, in Task 5, `--test`, so the two cannot drift.

**Files:**
- Modify: `wp-post.py` - add `resolve_locale_for_file()` after `find_site_for_file()` (which ends at line 1272); `WordPressPost.__init__` at lines 103-115; the converter construction at line 146; the poster construction at lines 2427-2432
- Test: `tests/test_wp_post.py`

**Interfaces:**
- Consumes: `find_network_config(filepath)`, `find_site_for_file(project_root, network_config, filepath)`, `resolve_site_identity(project_root, site_key, site_info)` - all already in `wp-post.py`. `GutenbergConverter(..., locale=...)` from Task 3.
- Produces:
  - `resolve_locale_for_file(filepath: str) -> str | None`
  - `WordPressPost(site_url, username, app_password, callout_config=None, resolve_bookmarks=True, locale=None)`

- [ ] **Step 1: Write the failing test**

`tests/test_wp_post.py` binds each function under test to a module-level name at the top of the file (`wp_post = sys.modules["wp_post"]`, then `find_site_for_file = wp_post.find_site_for_file`, and so on through line 23). Add one more to that block:

```python
resolve_locale_for_file = wp_post.resolve_locale_for_file
```

`json`, `pytest`, and `Path` are already imported there. Then add:

```python
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


class TestResolveLocaleIsBestEffort:
    """Locale discovery runs unconditionally and under --test, so it must
    degrade to English rather than abort a publish that used to work."""

    def test_malformed_json_warns_and_returns_none(self, tmp_path, capsys):
        (tmp_path / "content").mkdir()
        (tmp_path / ".wp-poster.json").write_text('{"network": {')
        article = tmp_path / "content" / "post.md"
        article.write_text("# Title\n")
        assert resolve_locale_for_file(str(article)) is None
        assert "site language" in capsys.readouterr().err

    def test_site_entry_missing_content_path_warns_and_returns_none(self, tmp_path, capsys):
        (tmp_path / "content").mkdir()
        (tmp_path / ".wp-poster.json").write_text(json.dumps({
            "network": {"sites": {"de": {"locale": "de_DE", "blog_id": 3}}}
        }))
        article = tmp_path / "content" / "post.md"
        article.write_text("# Title\n")
        assert resolve_locale_for_file(str(article)) is None
        assert "site language" in capsys.readouterr().err

    def test_non_dict_site_entry_warns_and_returns_none(self, tmp_path, capsys):
        (tmp_path / "content").mkdir()
        (tmp_path / ".wp-poster.json").write_text(json.dumps({
            "network": {"sites": {"de": "content/de"}}
        }))
        article = tmp_path / "content" / "post.md"
        article.write_text("# Title\n")
        assert resolve_locale_for_file(str(article)) is None
        assert "site language" in capsys.readouterr().err


class TestPosterCarriesLocale:
    def test_locale_defaults_to_none(self):
        poster = WordPressPost("https://e.com", "u", "p")
        assert poster._locale is None

    def test_locale_is_stored(self):
        poster = WordPressPost("https://e.com", "u", "p", locale="de_DE")
        assert poster._locale == "de_DE"

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_wp_post.py -k "Locale" -v`
Expected: FAIL with `NameError: name 'resolve_locale_for_file' is not defined`.

- [ ] **Step 3: Write minimal implementation**

Add to `wp-post.py` immediately after `find_site_for_file()` ends at line 1272:

```python
def resolve_locale_for_file(filepath):
    """The declared locale of the network site a file belongs to, or None.

    Reads on-disk config only - no network calls - so `--test` and a real
    publish resolve callout labels through exactly the same path.

    Best-effort by construction. The helpers it calls are not:
    find_network_config json.load()s without a guard, and
    find_site_for_file indexes site_info['content_path'] directly, so
    malformed JSON or a site entry missing content_path raises. Those
    already run on the publish path, but only when --site-url is absent;
    this function runs unconditionally and under --test, so an exception
    here would newly break paths that used to work. A label falling back
    to English must never cost a publish.
    """
    try:
        net_root, net_config = find_network_config(filepath)
        if not net_config:
            return None
        site_key, site_info = find_site_for_file(net_root, net_config, filepath)
        if not site_info:
            return None
        return resolve_site_identity(net_root, site_key, site_info).get('locale')
    except Exception as e:
        print(
            f"⚠ Could not determine the site language for {filepath} ({e}); "
            "using English callout labels",
            file=sys.stderr,
        )
        return None
```

Change `WordPressPost.__init__` (line 103):

```python
    def __init__(self, site_url, username, app_password,
                 callout_config=None, resolve_bookmarks=True, locale=None):
```

and store it alongside `self._callout_config` at line 111:

```python
        self._locale = locale
```

Forward it in `parse_markdown_file`'s converter construction (line 146):

```python
        converter = GutenbergConverter(
            image_handler=self._handle_image,
            callout_config=self._callout_config,
            bookmark_resolver=self._resolve_bookmark if self._resolve_bookmarks else None,
            locale=self._locale,
        )
```

In `main()`, resolve the locale from the file before the poster is built. Add this immediately before the `poster = WordPressPost(` call at line 2427:

```python
    # Language follows the file's site mapping, not --site-url: the
    # content's language does not change based on where it is pushed.
    site_locale = resolve_locale_for_file(args.file)

```

and add the argument to the call:

```python
    poster = WordPressPost(
        config['site_url'],
        config['username'],
        config['app_password'],
        callout_config=config.get('callouts'),
        locale=site_locale
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_wp_post.py -k "Locale" -v`
Expected: PASS.

Run: `python3 -m pytest -q`
Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Resolve the destination site's locale on the publish path"
```

---

### Task 5: --test previews the real labels

`--test` builds a poster against a dummy URL and never resolves the site, so a German file would preview English labels - the one place the tool would misreport its own output.

**Files:**
- Modify: `wp-post.py:2312-2316`
- Test: `tests/test_wp_post.py`

**Interfaces:**
- Consumes: `resolve_locale_for_file(filepath)` from Task 4.
- Produces: nothing new.

This task changes three lines inside `main()`, so the test has to drive `main()`. That is reachable: `main()` is at `wp-post.py:2226`, `--test` needs no credentials, and the branch ends in `sys.exit(0)` after printing the blocks to stdout. Patching `sys.argv` and catching `SystemExit` gives a genuine red-green cycle against a temporary project - no live content repo involved.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_wp_post.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_wp_post.py::TestTestModeLocale -v`
Expected: `test_test_mode_previews_the_sites_language` FAILS - stdout carries `Warning</strong>`, English chrome previewed for a German post. `test_test_mode_outside_a_network_project_previews_english` passes already; it guards the fallback against over-correction.

- [ ] **Step 3: Write minimal implementation**

In `wp-post.py`, replace the poster construction in the `--test` branch at lines 2312-2316:

```python
        # Create a dummy poster instance just for parsing (no bookmark
        # lookups in test mode - the dummy site URL is not real)
        poster = WordPressPost('https://example.com', 'user', 'pass',
                               callout_config=load_config().get('callouts'),
                               resolve_bookmarks=False)
```

with:

```python
        # Create a dummy poster instance just for parsing (no bookmark
        # lookups in test mode - the dummy site URL is not real). The
        # locale is still resolved for real, so --test previews the same
        # callout labels a publish would emit.
        poster = WordPressPost('https://example.com', 'user', 'pass',
                               callout_config=load_config().get('callouts'),
                               resolve_bookmarks=False,
                               locale=resolve_locale_for_file(args.file))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_wp_post.py::TestTestModeLocale -v`
Expected: PASS.

Run: `python3 -m pytest -q`
Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add wp-post.py tests/test_wp_post.py
git commit -m "Resolve the locale in --test so previews match publishes"
```

---

### Task 6: Documentation

`SKILL.md` currently tells the reader to localise callouts with the `label` key, which no longer exists. The CLI help gains the locale rule.

**Files:**
- Modify: `skills/wp-post/SKILL.md:186-202`, `wp-post.py:2151-2178`

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces: nothing code-facing.

- [ ] **Step 1: Update SKILL.md**

Replace the config block and bullet list at `skills/wp-post/SKILL.md:186-202`. The current text is:

````markdown
Override per project in `.wp-poster.json`:

```json
"callouts": {
  "background": "tertiary",
  "padding": "1.25rem",
  "types": {
    "note":    {"label": "Note",    "color": "#0969da"},
    "caution": {"label": "Caution", "color": "primary"}
  }
}
```

- `label` - text shown after the icon. Use this to localise callouts.
- `color` - a hex literal like `#cf2e2e`, or a palette slug like `primary`
  to tie a type to the site's brand instead of the convention.
- `icon` - inline HTML replacing the built-in SVG. Set `""` to remove it.
````

Replace it with:

````markdown
Override per project in `.wp-poster.json`:

```json
"callouts": {
  "background": "tertiary",
  "padding": "1.25rem",
  "types": {
    "caution": {"color": "primary"}
  }
}
```

- `color` - a hex literal like `#cf2e2e`, or a palette slug like `primary`
  to tie a type to the site's brand instead of the convention.
- `icon` - inline HTML replacing the built-in SVG. Set `""` to remove it.

### Callout labels and language

Labels are not configurable. They come from a table shipped with
wp-poster, selected by the destination site's `locale` in the
`network.sites` map:

| lang | note | tip | important | warning | caution | summary | faq | bookmark |
|------|------|-----|-----------|---------|---------|---------|-----|----------|
| en | Note | Tip | Important | Warning | Caution | In short | Frequently asked questions | Read next |
| de | Hinweis | Tipp | Wichtig | Warnung | Vorsicht | Kurz gesagt | Häufige Fragen | Weiterlesen |
| es | Nota | Consejo | Importante | Advertencia | Precaución | En resumen | Preguntas frecuentes | Sigue leyendo |
| fr | Note | Astuce | Important | Avertissement | Attention | En bref | Questions fréquentes | À lire ensuite |
| it | Nota | Suggerimento | Importante | Avvertenza | Attenzione | In breve | Domande frequenti | Leggi anche |
| ja | 注記 | ヒント | 重要 | 警告 | 注意 | 要点 | よくある質問 | あわせて読みたい |
| ko | 참고 | 팁 | 중요 | 경고 | 주의 | 요약 | 자주 묻는 질문 | 이어서 읽기 |
| zh | 备注 | 提示 | 重要 | 警告 | 注意 | 摘要 | 常见问题 | 延伸阅读 |
| th | หมายเหตุ | เคล็ดลับ | สำคัญ | คำเตือน | ข้อควรระวัง | สรุป | คำถามที่พบบ่อย | อ่านต่อ |
| ar | ملاحظة | نصيحة | مهم | تحذير | تنبيه | باختصار | الأسئلة الشائعة | اقرأ أيضًا |
| he | הערה | טיפ | חשוב | אזהרה | זהירות | בקצרה | שאלות נפוצות | להמשך קריאה |

A locale like `de_DE` takes its language prefix. A language with no entry
falls back to English and warns. A project with no `network.sites` map has
no locale and takes English silently.

`--test` resolves the locale the same way, so a preview shows the labels a
publish would emit.

Arabic and Hebrew are right-to-left; the labels are correct but the icon
gap and the accent bar still anchor to the left. Bidi is not yet handled.
````

- [ ] **Step 2: Update the CLI help**

In `wp-post.py`, replace the sentence at line 2171-2173:

```
  Override per type in .wp-poster.json under "callouts", where a value
  like "#cf2e2e" is used as a literal and anything else is treated as a
  palette slug. See the wp-post skill for the full schema.
```

with:

```
  Override colour and icon per type in .wp-poster.json under "callouts",
  where a value like "#cf2e2e" is used as a literal and anything else is
  treated as a palette slug. See the wp-post skill for the full schema.

  Labels are not configurable. They come from a built-in table in eleven
  languages, selected by the destination site's locale in network.sites -
  a post under a de_DE site gets "Warnung", not "Warning". A language with
  no entry falls back to English and warns. --test resolves the locale the
  same way, so a preview matches a publish.
```

- [ ] **Step 3: Verify the help renders**

Run: `python3 wp-post.py --help | grep -A 6 "Labels are not configurable"`
Expected: the new paragraph, correctly wrapped.

Run: `python3 -m pytest -q`
Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add skills/wp-post/SKILL.md wp-post.py
git commit -m "Document callout label localisation, drop the label key"
```

- [ ] **Step 5: Reinstall the skill where it is already installed**

`install.sh` copies `skills/wp-post` rather than symlinking it, so this rewrite does not reach a project that already installed the skill. Reinstall in each:

```bash
cd /home/adam/projects/payperfax-content && /home/adam/projects/wp-poster/install.sh
```

Check for other installs first and repeat for each hit:

```bash
ls -d /home/adam/projects/*/.claude/skills/wp-post 2>/dev/null
```

---

## Verification

After Task 6, confirm the whole feature end to end:

- [ ] `python3 -m pytest -q` from the repo root - all passing, and more than the 389 baseline.
- [ ] `git log --oneline master..` shows six commits, one per task.
- [ ] No test asserts that a configured label takes effect. `grep -rn '"label"' tests/` is too blunt to check this - it also matches legitimate reads of the resolved label and the tests that pass a label to prove it is rejected. Read the hits rather than expecting none.
- [ ] `grep -rn '"label"' skills/wp-post/SKILL.md` returns nothing.
- [ ] `TestResolveLocaleIsBestEffort` passes - malformed JSON, a site entry with no `content_path`, and a non-dict site entry each warn and fall back to English rather than aborting.
- [ ] `TestTestModeLocale::test_test_mode_previews_the_sites_language` fails if the `locale=` argument is deleted from the `--test` branch. Check this by hand once: remove it, watch the test go red, put it back.
- [ ] A config carrying a stale `"label"` key warns rather than failing:
  `python3 -c "import callouts; callouts.merge_config({'types': {'note': {'label': 'x'}}})"`
  prints a warning to stderr and exits 0.
