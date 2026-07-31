"""Markdown callouts rendered as core Gutenberg blocks.

Eight callout types are authored as GFM blockquotes:

    > [!NOTE]
    > Body text.

Colours come from the active theme's palette by default, so a callout
matches the site it lands on. A config value that looks like a hex
literal is used as-is; anything else is treated as a palette slug.
"""

import json
import re
import sys
from html import escape

CALLOUT_TYPES = (
    "note",
    "tip",
    "important",
    "warning",
    "caution",
    "summary",
    "faq",
    "bookmark",
)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")

# Octicon path data, rendered at 16x16. The first five are the paths the
# previous wp:quote admonitions used; the last three are new.
_ICON_PATHS = {
    "note": (
        "M0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8Zm8-6.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 "
        "0-13ZM6.5 7.75A.75.75 0 0 1 7.25 7h1a.75.75 0 0 1 .75.75v2.75h.25a.75.75 0 "
        "0 1 0 1.5h-2a.75.75 0 0 1 0-1.5h.25v-2h-.25a.75.75 0 0 1-.75-.75ZM8 6a1 1 0 "
        "1 1 0-2 1 1 0 0 1 0 2Z"
    ),
    "tip": (
        "M8 1.5c-2.363 0-4 1.69-4 3.75 0 .984.424 1.625.984 2.304l.214.253c.223.264"
        ".47.556.673.848.284.411.537.896.621 1.49a.75.75 0 0 1-1.484.211c-.04-.282-."
        "163-.547-.37-.847a8.456 8.456 0 0 0-.542-.68c-.084-.1-.173-.205-.268-.32C3."
        "201 7.75 2.5 6.766 2.5 5.25 2.5 2.31 4.863 0 8 0s5.5 2.31 5.5 5.25c0 "
        "1.516-.701 2.5-1.328 3.259-.095.115-.184.22-.268.319-.207.245-.383.453-."
        "541.681-.208.3-.33.565-.37.847a.751.751 0 0 1-1.485-.212c.084-.593.337-1."
        "078.621-1.489.203-.292.45-.584.673-.848.075-.088.147-.173.213-.253.561-."
        "679.985-1.32.985-2.304 0-2.06-1.637-3.75-4-3.75ZM5.75 12h4.5a.75.75 0 0 1 "
        "0 1.5h-4.5a.75.75 0 0 1 0-1.5ZM6 15.25a.75.75 0 0 1 .75-.75h2.5a.75.75 0 0 "
        "1 0 1.5h-2.5a.75.75 0 0 1-.75-.75Z"
    ),
    "important": (
        "M0 1.75C0 .784.784 0 1.75 0h12.5C15.216 0 16 .784 16 1.75v9.5A1.75 1.75 0 "
        "0 1 14.25 13H8.06l-2.573 2.573A1.458 1.458 0 0 1 3 14.543V13H1.75A1.75 "
        "1.75 0 0 1 0 11.25Zm1.75-.25a.25.25 0 0 0-.25.25v9.5c0 .138.112.25.25.25h2"
        "a.75.75 0 0 1 .75.75v2.19l2.72-2.72a.749.749 0 0 1 .53-.22h6.5a.25.25 0 0 "
        "0 .25-.25v-9.5a.25.25 0 0 0-.25-.25Zm7 2.25v2.5a.75.75 0 0 1-1.5 0v-2.5a."
        "75.75 0 0 1 1.5 0ZM9 9a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z"
    ),
    "warning": (
        "M6.457 1.047c.659-1.234 2.427-1.234 3.086 0l6.082 11.378A1.75 1.75 0 0 1 "
        "14.082 15H1.918a1.75 1.75 0 0 1-1.543-2.575Zm1.763.707a.25.25 0 0 0-.44 "
        "0L1.698 13.132a.25.25 0 0 0 .22.368h12.164a.25.25 0 0 0 .22-.368Zm.53 "
        "3.996v2.5a.75.75 0 0 1-1.5 0v-2.5a.75.75 0 0 1 1.5 0ZM9 11a1 1 0 1 1-2 0 1 "
        "1 0 0 1 2 0Z"
    ),
    "caution": (
        "M4.47.22A.749.749 0 0 1 5 0h6c.199 0 .389.079.53.22l4.25 4.25c.141.14.22."
        "331.22.53v6a.749.749 0 0 1-.22.53l-4.25 4.25A.749.749 0 0 1 11 16H5a.749."
        "749 0 0 1-.53-.22L.22 11.53A.749.749 0 0 1 0 11V5c0-.199.079-.389.22-.53Z"
        "m.84 1.28L1.5 5.31v5.38l3.81 3.81h5.38l3.81-3.81V5.31L10.69 1.5ZM8 4a.75."
        "75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 8 4Zm0 8a1 1 0 1 "
        "1 0-2 1 1 0 0 1 0 2Z"
    ),
    "summary": (
        "M5.75 2.5h8.5a.75.75 0 0 1 0 1.5h-8.5a.75.75 0 0 1 0-1.5Zm0 5h8.5a.75.75 0 0 1 0 "
        "1.5h-8.5a.75.75 0 0 1 0-1.5Zm0 5h8.5a.75.75 0 0 1 0 1.5h-8.5a.75.75 0 0 1 0-1.5ZM2 "
        "14a1 1 0 1 1 0-2 1 1 0 0 1 0 2Zm1-6a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM2 4a1 1 0 1 1 0-2 1 "
        "1 0 0 1 0 2Z"
    ),
    "faq": (
        "M0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8Zm8-6.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM6.92 "
        "6.085h.001a.749.749 0 1 1-1.342-.67c.169-.339.436-.701.849-.977C6.845 4.16 7.369 4 8 "
        "4a2.756 2.756 0 0 1 1.637.525c.503.377.863.965.863 1.725 0 .448-.115.83-.329 "
        "1.15-.205.307-.47.513-.692.662-.109.072-.22.138-.313.195l-.006.004a6.24 6.24 0 0 "
        "0-.26.16 1.113 1.113 0 0 0-.3.263.75.75 0 1 1-1.2-.9c.157-.21.35-.368.518-.476.15-.099"
        ".322-.201.458-.282l.005-.003c.106-.063.193-.114.273-.168.129-.086.186-.155.212-.194.024"
        "-.037.061-.107.061-.31 0-.26-.11-.44-.27-.56A1.273 1.273 0 0 0 8 5.5c-.369 "
        "0-.595.09-.74.187a.938.938 0 0 0-.34.398ZM9 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z"
    ),
    "bookmark": (
        "M3 2.75C3 1.784 3.784 1 4.75 1h6.5c.966 0 1.75.784 1.75 1.75v11.5a.75.75 0 0 "
        "1-1.227.579L8 11.722l-3.773 3.107A.751.751 0 0 1 3 14.25Zm1.75-.25a.25.25 0 0 "
        "0-.25.25v9.91l3.023-2.489a.75.75 0 0 1 .954 0l3.023 2.49V2.75a.25.25 0 0 0-.25-.25Z"
    ),
}

_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="20" height="20" '
    'fill="currentColor" style="display:inline-block;vertical-align:middle;'
    'margin-right:6px;position:relative;top:-2px;"><path d="{path}"></path></svg>'
)

# The five GFM admonitions carry GitHub's hues, because readers already
# associate those colours with those meanings - amber warns, red stops.
# A palette slug cannot express that: a theme's slots are named by role
# (primary, secondary) rather than by hue, so every type would share one
# colour and only the icon would distinguish them.
#
# The three types with no cross-site convention - summary, faq, bookmark -
# stay on `primary-alt-accent`, so a site's own brand still shows up in
# the callouts that are not standard GFM, in a tone that sets them apart
# from the five hue-coded types without competing with them.
#
# Backgrounds stay on the theme slug for every type, so the boxes read as
# part of the site rather than as imported GitHub chrome. Any of these can
# be overridden per project; see the `callouts` key in .wp-poster.json.
DEFAULT_CONFIG = {
    "background": "tertiary",
    "padding": "1.25rem",
    "types": {
        "note": {"label": "Note", "color": "#0969da", "icon": None},
        "tip": {"label": "Tip", "color": "#1a7f37", "icon": None},
        "important": {"label": "Important", "color": "#8250df", "icon": None},
        "warning": {"label": "Warning", "color": "#9a6700", "icon": None},
        "caution": {"label": "Caution", "color": "#d1242f", "icon": None},
        "summary": {"label": "In short", "color": "primary-alt-accent", "icon": None},
        "faq": {
            "label": "Frequently asked questions",
            "color": "primary-alt-accent",
            "icon": None,
        },
        "bookmark": {
            "label": "Read next",
            "color": "primary-alt-accent",
            "icon": None,
        },
    },
}


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


def _default_warn(message):
    """Warn on stderr without failing the publish."""
    print(f"⚠ {message}", file=sys.stderr)


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
    normalised = locale.strip().lower()
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


def _clean_str(value, fallback):
    """A non-empty string, or the fallback. Guards hand-edited config."""
    if isinstance(value, str) and value.strip():
        return value
    return fallback


def merge_config(user_config=None, warn=None):
    """User config merged over the built-in defaults.

    Every field is optional; a partial override touches only what it
    names. Config arrives from hand-edited JSON, so every value may be
    the wrong type - this function never raises, it warns and falls
    back, because a bad config must not fail a publish.
    """
    warn = warn or _default_warn
    merged = {
        "background": DEFAULT_CONFIG["background"],
        "padding": DEFAULT_CONFIG["padding"],
        "types": {name: dict(spec) for name, spec in DEFAULT_CONFIG["types"].items()},
    }
    if not user_config:
        return merged
    if not isinstance(user_config, dict):
        warn(
            "callouts config must be an object, ignored: "
            f"{type(user_config).__name__}"
        )
        return merged

    if "background" in user_config:
        merged["background"] = _clean_str(user_config["background"], merged["background"])
    if "padding" in user_config:
        merged["padding"] = _clean_str(user_config["padding"], merged["padding"])

    types = user_config.get("types")
    if types is not None and not isinstance(types, dict):
        warn(f"callouts.types must be an object, ignored: {type(types).__name__}")
        types = None

    for name, overrides in (types or {}).items():
        key = str(name).lower()
        if key not in merged["types"]:
            warn(f"unknown callout type in config, ignored: {name}")
            continue
        if not isinstance(overrides, dict):
            warn(f"callouts.types.{name} must be an object, ignored")
            continue

        target = merged["types"][key]
        target["label"] = _clean_str(overrides.get("label"), target["label"])
        target["color"] = _clean_str(overrides.get("color"), target["color"])
        if "icon" in overrides:
            # "" is meaningful (disables the icon), so _clean_str is wrong
            # here; anything non-string falls back to the built-in SVG.
            icon = overrides["icon"]
            target["icon"] = icon if isinstance(icon, str) else None

    return merged


def color_attr(value):
    """Block-attribute form of a colour: hex literal or preset reference."""
    if _HEX_RE.match(value):
        return value
    return f"var:preset|color|{value}"


def color_css(value):
    """Inline-style form, matching what Gutenberg serialises."""
    if _HEX_RE.match(value):
        return value
    return f"var(--wp--preset--color--{value})"


def icon_html(type_name, cfg):
    """Icon markup for a type: built-in SVG, config override, or nothing."""
    override = cfg["types"][type_name].get("icon")
    if override is not None:
        return override
    return _SVG_TEMPLATE.format(path=_ICON_PATHS[type_name])


_CALLOUT_RE = re.compile(
    r"^\[!(" + "|".join(CALLOUT_TYPES) + r")\]\s*\n?",
    re.IGNORECASE,
)

_FAQ_QUESTION_RE = re.compile(r"^\*\*(.+?)\*\*[ \t]*$", re.MULTILINE)


def _split_faq(body, warn=None):
    """Split an FAQ body into (preamble, [(question, answer_markdown), ...]).

    A question is a line consisting solely of bold text, and only opens a
    new question when it is the first line of the body or is preceded by
    a blank line - a bold line stuck directly to the end of an answer
    (no blank line above it) stays part of that answer instead of starting
    a new one. A standalone bold line that *is* preceded by a blank line
    inside an answer is still read as a new question; that's accepted as
    an unavoidable ambiguity, not something this function tries to guess
    around.

    A pair whose answer is empty or whitespace-only is dropped rather than
    emitted as an empty accordion, but never silently: it is reported
    through `warn` so nothing disappears without a trace.
    """
    warn = warn or _default_warn
    questions = []
    for match in _FAQ_QUESTION_RE.finditer(body):
        start = match.start()
        if start == 0:
            questions.append(match)
            continue
        # MULTILINE '^' means start sits right after the '\n' that ends
        # the previous line, so body[start - 1] is that newline. Look at
        # the line before it to see whether it's blank.
        prior_newline = body.rfind("\n", 0, start - 1)
        previous_line = body[prior_newline + 1 : start - 1]
        if previous_line.strip() == "":
            questions.append(match)

    if not questions:
        return body, []

    preamble = body[: questions[0].start()]
    pairs = []
    for index, match in enumerate(questions):
        start = match.end()
        end = questions[index + 1].start() if index + 1 < len(questions) else len(body)
        answer = body[start:end]
        question = match.group(1).strip()
        if not answer.strip():
            warn(f'[!FAQ] question "{question}" has no answer; skipped')
            continue
        pairs.append((question, answer))
    return preamble, pairs


def _apply_background(background, attrs, classes, styles):
    """Add a background to a block's attributes, classes, and inline style.

    A palette slug rides on the block's own `backgroundColor` attribute
    and the class WordPress generates from it; a hex literal has to go
    through `style.color.background` instead. Shared by every callout
    block so the two forms cannot drift apart between them.
    """
    if _HEX_RE.match(background):
        attrs.setdefault("style", {}).setdefault("color", {})["background"] = background
        classes.append("has-background")
        styles.append(f"background-color:{color_css(background)}")
    else:
        attrs["backgroundColor"] = background
        classes.append(f"has-{background}-background-color")
        classes.append("has-background")


def _group_attrs(type_name, cfg):
    """Block attributes for a callout's wrapping core/group.

    Background is not applied here - `_group_open` adds it through
    `_apply_background`, so the attribute, the class, and the inline
    style are all decided in one place.
    """
    accent = cfg["types"][type_name]["color"]
    padding = cfg["padding"]

    attrs = {"className": f"is-callout is-callout-{type_name}"}
    style = {
        # "style":"solid" is mandatory, not decorative: the CSS initial
        # value of border-style is none, which computes border-width to
        # 0. Colour and width alone render no border at all.
        "border": {
            "left": {"color": color_attr(accent), "width": "4px", "style": "solid"}
        },
        "spacing": {
            "padding": {
                "top": padding,
                "right": padding,
                "bottom": padding,
                "left": padding,
            }
        },
    }
    attrs["style"] = style
    attrs["layout"] = {"type": "constrained"}
    return attrs


def _group_open(type_name, cfg):
    """Opening comment and <div> for a callout's wrapping core/group."""
    accent = cfg["types"][type_name]["color"]
    padding = cfg["padding"]
    attrs = _group_attrs(type_name, cfg)

    classes = ["wp-block-group", "is-callout", f"is-callout-{type_name}"]
    styles = [
        f"border-left-color:{color_css(accent)}",
        "border-left-width:4px",
        "border-left-style:solid",
    ]
    _apply_background(cfg["background"], attrs, classes, styles)
    for side in ("top", "right", "bottom", "left"):
        styles.append(f"padding-{side}:{padding}")

    return (
        f"<!-- wp:group {json.dumps(attrs, separators=(',', ':'))} -->\n"
        f'<div class="{" ".join(classes)}" style="{";".join(styles)}">\n'
    )


_GROUP_CLOSE = "</div>\n<!-- /wp:group -->\n\n"


def _label_block(type_name, cfg):
    """The coloured, icon-prefixed label paragraph."""
    accent = cfg["types"][type_name]["color"]
    label = cfg["types"][type_name]["label"]
    icon = icon_html(type_name, cfg)
    attrs = {
        "className": "is-callout-label",
        "style": {"color": {"text": color_attr(accent)}},
    }
    return (
        f"<!-- wp:paragraph {json.dumps(attrs, separators=(',', ':'))} -->\n"
        f'<p class="is-callout-label has-text-color" style="color:{color_css(accent)}">'
        f"<strong>{icon}{label}</strong></p>\n"
        f"<!-- /wp:paragraph -->\n\n"
    )


# The percentage width of the image column in a resolved bookmark's
# core/media-text card. Read from here for both the block's mediaWidth
# attribute and the grid-template-columns style core/media-text's own
# save() derives from it, so the two can't drift apart.
_BOOKMARK_MEDIA_WIDTH = 30


def _bookmark_body(data, cfg):
    """Label, linked title, and excerpt - shared by both resolved cards."""
    title = escape(str(data.get("title", "") or ""), quote=False)
    link = escape(str(data.get("link", "") or ""), quote=True)
    excerpt = escape(str(data.get("excerpt", "") or ""), quote=False)

    parts = [
        _label_block("bookmark", cfg),
        '<!-- wp:heading {"level":3} -->\n'
        f'<h3 class="wp-block-heading"><a href="{link}">{title}</a></h3>\n'
        "<!-- /wp:heading -->\n\n",
    ]
    if excerpt:
        parts.append(
            "<!-- wp:paragraph -->\n"
            f"<p>{excerpt}</p>\n"
            "<!-- /wp:paragraph -->\n\n"
        )
    return "".join(parts)


def callout_plugin(config=None, bookmark_resolver=None, warn=None):
    """Build a mistune plugin rendering callouts with this configuration."""
    cfg = merge_config(config, warn=warn)
    _warn = warn or _default_warn

    def parse(block, m, state):
        """Replace the block_quote parser; emit callout or block_quote."""
        text, end_pos = block.extract_block_quote(m, state)
        if not text.endswith("\n"):
            text += "\n"

        matched = _CALLOUT_RE.match(text)
        if state.depth() >= block.max_nested_level - 1:
            rules = list(block.block_quote_rules)
            rules.remove("block_quote")
        else:
            rules = block.block_quote_rules

        if not matched:
            child = state.child_state(text)
            block.parse(child, rules)
            token = {"type": "block_quote", "children": child.tokens, "attrs": {}}
        else:
            name = matched.group(1).lower()
            body = text[matched.end():]

            if name == "bookmark":
                token = {
                    "type": "callout",
                    "children": [],
                    "attrs": {"name": name, "target": body.strip()},
                }
                if end_pos:
                    state.prepend_token(token)
                    return end_pos
                state.append_token(token)
                return state.cursor

            if name == "faq":
                preamble, pairs = _split_faq(body, warn=_warn)
                if not pairs:
                    _warn(
                        "[!FAQ] callout has no questions (no **question** "
                        "lines found); rendering its body as ordinary content"
                    )
                    child = state.child_state(body)
                    block.parse(child, rules)
                    children = child.tokens
                else:
                    if preamble.strip():
                        _warn(
                            "[!FAQ] callout has text before the first question; "
                            "it was dropped"
                        )
                    children = []
                    for question, answer in pairs:
                        item_state = state.child_state(answer)
                        block.parse(item_state, rules)
                        children.append(
                            {
                                "type": "faq_item",
                                "children": item_state.tokens,
                                "attrs": {"question": question},
                            }
                        )
            else:
                child = state.child_state(body)
                block.parse(child, rules)
                children = child.tokens

            token = {
                "type": "callout",
                "children": children,
                "attrs": {"name": name},
            }

        if end_pos:
            state.prepend_token(token)
            return end_pos
        state.append_token(token)
        return state.cursor

    def render_callout(renderer, text, name, target=None):
        if name == "bookmark":
            return _render_bookmark(target)
        return _group_open(name, cfg) + _label_block(name, cfg) + text + _GROUP_CLOSE

    def _render_bookmark(target):
        data = None
        if bookmark_resolver is not None:
            try:
                data = bookmark_resolver(target)
            except Exception as exc:  # never fail a publish over a bookmark
                _warn(f"bookmark lookup failed for {target}: {exc}")
            else:
                if data is None:
                    _warn(f"could not resolve bookmark target: {target}")
                elif not isinstance(data, dict):
                    _warn(
                        "bookmark resolver returned a "
                        f"{type(data).__name__}, expected a dict, for "
                        f"target: {target}"
                    )
                    data = None

        if data is None:
            return _bookmark_link_card(target)
        # The two guards above only cover the shape of `data` itself; they
        # can't cover every way a field inside it might misbehave once
        # consumed (a value whose __str__ raises, a dict subclass whose
        # .get() raises, ...). Rather than chase each one individually,
        # this net catches whatever they miss and still degrades to a
        # usable card instead of failing the publish.
        try:
            if data.get("image_url"):
                return _bookmark_media_text(data)
            return _bookmark_group_card(data)
        except Exception as exc:
            _warn(
                f"bookmark card could not be built for {target}: {exc}; "
                "using a plain link"
            )
            return _bookmark_link_card(target)

    def _bookmark_media_text(data):
        image_url = escape(str(data["image_url"]), quote=True)
        image_id = data.get("image_id")
        # The contract is int | None. bool is a subclass of int, so it's
        # excluded explicitly; anything else non-int (a set, a string, a
        # float, ...) is treated as absent rather than risking a
        # json.dumps crash or a garbage "wp-image-{...}" class.
        if isinstance(image_id, bool) or not isinstance(image_id, int):
            image_id = None
        title = escape(str(data.get("title", "") or ""), quote=True)
        media_width = _BOOKMARK_MEDIA_WIDTH
        attrs = {
            "mediaType": "image",
            "mediaWidth": media_width,
            # "Crop image to fit" in the editor. Without it a portrait
            # thumbnail leaves dead space beside the text; with it the
            # image fills its column at any aspect ratio.
            "imageFill": True,
            "className": "is-callout is-callout-bookmark",
        }
        if image_id:
            attrs["mediaId"] = image_id
        # core/media-text's save() derives both of these from the block's
        # own attributes (mediaWidth, mediaId) - they aren't decorative,
        # Gutenberg's block validator re-derives the expected markup from
        # the attributes and rejects the block if it doesn't match. The
        # style is only added when mediaWidth differs from core's default
        # of 50, which ours always does, so it's unconditional here.
        styles = [f"grid-template-columns:{media_width}% auto"]
        classes = [
            "wp-block-media-text",
            "is-stacked-on-mobile",
            # Paired with the imageFill attribute above; core's save()
            # emits it in this position, and block validation compares
            # the whole class string.
            "is-image-fill-element",
            "is-callout",
            "is-callout-bookmark",
        ]
        # Without this the image-bearing card is the only callout on a page
        # with no background, since it builds its own markup instead of
        # going through _group_open like every other type.
        _apply_background(cfg["background"], attrs, classes, styles)
        style = f' style="{";".join(styles)}"'
        img_class = f' class="wp-image-{image_id} size-full"' if image_id else ""
        # imageFill makes save() emit object-position from focalPoint,
        # which defaults to dead centre when the attribute is absent.
        img_style = ' style="object-position:50% 50%"'
        return (
            f"<!-- wp:media-text {json.dumps(attrs, separators=(',', ':'))} -->\n"
            f'<div class="{" ".join(classes)}"{style}>\n'
            '<figure class="wp-block-media-text__media">'
            f'<img src="{image_url}" alt="{title}"{img_class}{img_style}/></figure>\n'
            '<div class="wp-block-media-text__content">\n'
            f"{_bookmark_body(data, cfg)}"
            "</div></div>\n"
            "<!-- /wp:media-text -->\n\n"
        )

    def _bookmark_group_card(data):
        return (
            _group_open("bookmark", cfg)
            + _bookmark_body(data, cfg)
            + _GROUP_CLOSE
        )

    def _bookmark_link_card(target):
        safe = escape(str(target), quote=True)
        label = cfg["types"]["bookmark"]["label"]
        return (
            _group_open("bookmark", cfg)
            + _label_block("bookmark", cfg)
            + "<!-- wp:paragraph -->\n"
            f'<p><a href="{safe}">{escape(label, quote=False)}</a></p>\n'
            "<!-- /wp:paragraph -->\n\n"
            + _GROUP_CLOSE
        )

    def render_faq_item(renderer, text, question):
        return (
            "<!-- wp:details -->\n"
            '<details class="wp-block-details">\n'
            f'<summary><h3 style="display:inline;margin:0">{escape(question, quote=False)}</h3></summary>\n'
            f"{text}"
            "</details>\n"
            "<!-- /wp:details -->\n\n"
        )

    def plugin(md):
        md.block.register("block_quote", None, parse)
        if md.renderer and md.renderer.NAME == "html":
            md.renderer.register("callout", render_callout)
            md.renderer.register("faq_item", render_faq_item)

    return plugin
