# Design: language-sensitive callout labels

Date: 2026-07-31

Callout labels come from a translation table shipped with wp-poster,
keyed by the destination site's locale, defaulting to English.

## Motivation

Callouts shipped today in 1.12.0 with eight English labels baked into
`callouts.DEFAULT_CONFIG` - Note, Tip, Important, Warning, Caution,
In short, Frequently asked questions, Read next. Everything else a
callout renders comes from the content or from WordPress: FAQ questions
are authored in the post, bookmark titles and excerpts are fetched from
the target. The label is the only English wp-poster puts on the page
itself.

That is invisible on a monolingual site and wrong on a multilingual one.
`payperfax-content` publishes the same article to six sites - `en_US`,
`es_ES`, `de_DE`, `ja`, `ko_KR`, `fr_FR` - from a single root
`.wp-poster.json`. A German post rendering a "Warning" box titled
*Warning*, above a *Read next* card, is the tool writing English into
German prose.

The current answer is the `label` config key, which `skills/wp-post/SKILL.md`
introduces with "Use this to localise callouts." It does not work for the
case it was written for. `callout_config` is read once from the root config
(`wp-post.py:2315`, `wp-post.py:2431`) and there is no per-site or
per-language dimension to write into, so one `label` value would apply to
all six payperfax sites at once. Localisation by config is unreachable in
exactly the project that needs it.

## Approach

Ship the translations. Resolve the language from the site the post is
being published to. Remove the config key that pretended to solve this.

### Language resolution

The locale is already resolved and then discarded. `wp-post.py:2386` calls
`resolve_site_identity()` and keeps only `identity['site_url']`;
`identity['locale']` is right there, unused.

Locale maps to a table key by lowercasing, then trying the full locale
before its language prefix:

```
"de_DE" -> try "de_de", then "de"   -> de
"ja"    -> try "ja"                 -> ja
"zh_TW" -> try "zh_tw", then "zh"   -> zh
None    ->                             en
```

Two-step lookup rather than a bare prefix split so a Traditional Chinese
table can be added under `zh_tw` later without reworking the resolver. No
locale-specific entry ships now.

A locale whose language is absent from the table falls back to English and
warns once per publish:

```
⚠ no callout labels for language 'pt'; using English
```

Silence is the failure mode this repo spent 2026-07-31 removing - see
issues #17 (terms dropped on HTML entities) and #21 (bookmark slugs
degrading on case). A label quietly reverting to English belongs in the
same category.

Non-network projects have no `locale` key anywhere. `getboki-content`,
`nanopost-content`, and `dashpadd` all resolve to `None` and take English
without a warning, which is the documented default rather than a failure.

### Why the site locale, not frontmatter `lang`

`payperfax-content` writes `lang:` into frontmatter and wp-post has never
read it. It was the obvious candidate and it does not hold up: only 185 of
1052 markdown files carry the key.

| dir | files with `lang:` | total |
|-----|--------------------|-------|
| en  |  36                |  408  |
| es  |  16                |   88  |
| de  |   5                |   66  |
| ja  |  28                |  182  |
| ko  |  23                |  188  |
| fr  |  77                |  120  |

Sourcing language from frontmatter would render English labels into 61 of
66 German files and say nothing. The site locale is declared once per site
in `network.sites`, is already resolved on the publish path, and cannot go
missing for a file that resolves to a site at all.

### Config surface

`label` is removed from the schema. `merge_config()` seeds each type's
label from `_LABELS[lang]`, and the `label` branch at `callouts.py:197` is
deleted. A `label` key found in user config warns as an unrecognised key
rather than being silently dropped.

No project sets a callout label today, so nothing breaks.

`background`, `padding`, `color`, and `icon` keep their overrides
unchanged. None of them are language-dependent.

## The table

Eleven languages: the six payperfax publishes, plus Italian, Arabic, Thai,
Chinese, and Hebrew shipped ahead of need.

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

### Translation choices worth recording

**`bookmark` is a slot label, not a phrase to translate.** `[!BOOKMARK]`
takes exactly one target and renders one card; in the degraded path
(`callouts.py:596-606`) the label becomes the anchor text. The slot means
"one related post the author picked," and each language uses its own
blog-native label for that slot - Weiterlesen, 延伸阅读, あわせて読みたい.
Forcing a literal *Read next* into all eleven (次に読む, Als Nächstes lesen)
would be accurate and read as machine output. The exact promise varies
slightly by language; that is what localisation is.

**`summary` is a register choice.** 要点, 요약, 摘要, and สรุป mean
"summary" or "key points" rather than literally "in short". Accepted: the
slot names a key-points box, and every language's natural label for that
box is what belongs there.

**`ja` note is 注記, not メモ.** GitHub's Japanese docs use メモ for
`[!NOTE]`, but メモ means "memo". payperfax's content is formal - legal
registry procedure, notarisation, corporate filing - and 注記 matches that
register.

**`it` warning is Avvertenza, not Avviso.** Avviso commonly reads as
"notice"; Avvertenza carries the warning sense.

Arabic, Hebrew, and Thai use the standard terms for each slot but have not
been reviewed by a native speaker. Worth doing before those languages
carry real traffic; not a blocker for shipping the table.

## Implementation

Four hops on the publish path, all short:

| where             | change                                                 |
|-------------------|--------------------------------------------------------|
| `wp-post.py:2386` | keep `identity.get('locale')` instead of discarding it |
| `wp-post.py:2427` | pass `locale=` into `WordPressPost(...)`               |
| `wp-post.py:105`  | `__init__` stores it; forwards at `wp-post.py:149`     |
| `gutenberg.py:317`| forwards to `callout_plugin(config, lang, ...)`        |

`callouts.py` gains `_LABELS`, a `resolve_lang(locale)` helper, and a
`lang` parameter on `merge_config()` and `callout_plugin()`.

### `--test` resolves the locale too

`wp-post.py:2314` builds a dummy poster against `https://example.com` and
never resolves the site, so `--test` on a German file would preview
English labels - the one place the tool would misreport its own output.
Test mode runs `find_network_config()` / `find_site_for_file()` purely to
obtain the locale. No network calls; bookmark resolution stays disabled.

## Out of scope

**Bidi.** Arabic and Hebrew are RTL and the markup anchors to physical
sides: the icon carries `margin-right:6px` (`callouts.py:101`) and the
accent bar is `style.border.left` (`callouts.py:320`). In RTL the icon gap
lands on the wrong side and the bar trails the text instead of leading it.
The icon is a one-line fix (`margin-inline-end`); the bar is not, because
Gutenberg's border attribute schema exposes physical sides only, so RTL
needs `border.right` emitted from an `_RTL` language set. Deferred by
decision - the labels ship first.

**Per-language config overrides.** Not built. If a project later wants a
brandier label for one type in one language, that is a `callouts.locales`
block, designed then.

## Testing

- `resolve_lang()`: `de_DE`→`de`, `ja`→`ja`, `zh_TW`→`zh`, `pt_BR`→`en`
  with a warning, `None`→`en` without one, and a malformed locale
  (non-string, empty) →`en` without raising.
- `merge_config(lang="de")` yields German labels; `lang=None` yields
  English; a `label` key in user config warns and does not take effect.
- Rendering: a `[!WARNING]` under a `de` locale emits *Warnung*; the
  unresolved bookmark card's anchor text is *Weiterlesen*.
- Every table entry covers all eight types - a missing key must fail a
  test, not fall through to a `KeyError` at publish time.
- `--test` on a file under a network site's `content_path` reports that
  site's language.

## Consequences

`skills/wp-post/SKILL.md` loses the `label` row and its "Use this to
localise callouts" line, gaining the table and the locale rule.
`wp-post.py`'s `callouts:` help section (`wp-post.py:2151`) gains a
sentence on language resolution.

There is no version to bump. `.claude-plugin/plugin.json` carried 1.12.0
and was deleted a few hours later in `0d5f9d3`, when the skill moved to
`install.sh`; no version string remains in the repo.

Because `install.sh` copies `skills/wp-post` rather than symlinking it,
the SKILL.md rewrite does not reach any project that already installed
the skill until `install.sh` is run there again. payperfax-content is one
of those projects.

payperfax-content needs no content change and no config change: its six
sites already declare locales, so callouts localise on the next publish.
