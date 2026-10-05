"""Single source of truth for the Arkad TUI's visual language.

Every widget, modal, and rendered block pulls colors from the palette
tokens here. Changing a token in one place changes the entire UI.

Themes
------
PALETTES holds every built-in color scheme. set_theme(name)
reassigns the module-level tokens (BG_0 … ACCENT_3) and rebuilds
the two CSS strings; textual_theme(name) builds the matching Textual
Theme whose $jv-* variables drive the transcript widgets, so a
theme switch restyles the live conversation without re-rendering it.

Other modules that need theme-aware colors at runtime should use
from . import theme as ui → ui.OK, ui.ACCENT_2, … (never
cache the individual constants — they change on every switch).
"""
from __future__ import annotations


# ── Full palette definitions ─────────────────────────────────────────────

Palette = dict[str, str]

PALETTES: dict[str, Palette] = {
    "rose": {
        "bg_0": "#0b0f15",
        "bg_1": "#11161d",
        "bg_2": "#161c24",
        "bg_3": "#1c232c",
        "bg_4": "#232b36",
        "border": "#2a323d",
        "border_fc": "#f7527a",
        "fg": "#e6edf3",
        "fg_mute": "#9aa4b1",
        "fg_dim": "#6b7684",
        "sep": "#1f2630",
        "ok": "#56d364",
        "warn": "#e3b341",
        "err": "#f85149",
        "accent": "#f7527a",
        "accent_2": "#ff7b9a",
        "accent_3": "#ffb3c6",
    },
}

# Newer palettes — tuned for the minimal (borderless) transcript. The first
# three are the most-requested editor schemes; "opencode" and "claude" follow
# the look of those two agent TUIs.


# One-line descriptions for the /theme picker (order = picker order).
THEME_DESCRIPTIONS: dict[str, str] = {
    "rose": "hot pink accents, magenta borders",
}

DEFAULT_THEME = "rose"


# ── Tokens (module-level constants — reassigned by set_theme()) ──────────

BG_0 = "#0b0f15"
BG_1 = "#11161d"
BG_2 = "#161c24"
BG_3 = "#1c232c"
BG_4 = "#232b36"
BORDER = "#2a323d"
BORDER_FC = "#4d8df6"
FG = "#e6edf3"
FG_MUTE = "#9aa4b1"
FG_DIM = "#6b7684"
SEP = "#1f2630"
OK = "#56d364"
WARN = "#e3b341"
ERR = "#f85149"
ACCENT = "#79c0ff"
ACCENT_2 = "#c084fc"
ACCENT_3 = "#f0b3ff"


# ── Visible glyphs — keep ASCII-fallback-safe where used in tight strips ──
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# Busy indicator beside the activity label: a star that breathes.
PULSE_FRAMES = ("·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢")
DOT = "·"
ARROW = "❯"
CHECK = "✓"
CROSS = "✗"
BULLET = "●"
GUTTER = "⏺"
ELBOW = "⎿"


def blend(a: str, b: str, t: float) -> str:
    """Mix two ``#rrggbb`` colors; ``t`` = 0 → a, 1 → b."""
    t = max(0.0, min(1.0, t))
    try:
        ra, ga, ba = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
        rb, gb, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    except (ValueError, IndexError):
        return a
    r = round(ra + (rb - ra) * t)
    g = round(ga + (gb - ga) * t)
    bl = round(ba + (bb - ba) * t)
    return f"#{r:02x}{g:02x}{bl:02x}"


# ── Textual theme (drives built-in widgets + ``$jv-*`` CSS variables) ────

def textual_theme_name(name: str | None = None) -> str:
    return f"arkad-{name or _ACTIVE_THEME}"


def textual_theme(name: str | None = None):
    """Build a :class:`textual.theme.Theme` for a palette.

    Built-in widgets (Markdown, OptionList, TextArea, toasts, scrollbars)
    read ``$primary`` / ``$surface`` / … so they follow the palette, and our
    own widgets use the ``$jv-*`` variables, which Textual re-resolves on
    every ``App.theme`` change — no stylesheet rebuild needed.
    """
    from textual.theme import Theme

    key = name or _ACTIVE_THEME
    p = PALETTES.get(key) or PALETTES[DEFAULT_THEME]
    variables = {f"jv-{k.replace('_', '-')}": v for k, v in p.items()}
    variables.update({
        "jv-user-bg": blend(p["bg_0"], p["bg_3"], 0.8),
        "jv-code-bg": blend(p["bg_0"], p["bg_2"], 0.9),
        "jv-select": blend(p["bg_0"], p["accent"], 0.28),
        "jv-modal-select": blend(p["bg_1"], p["accent"], 0.22),
        "block-cursor-background": p["accent"],
        "block-cursor-foreground": p["bg_0"],
        "block-cursor-text-style": "bold",
        "block-cursor-blurred-background": blend(p["bg_0"], p["accent"], 0.3),
        "block-cursor-blurred-foreground": p["fg"],
        "block-hover-background": blend(p["bg_0"], p["bg_4"], 0.6),
        "input-selection-background": blend(p["bg_0"], p["accent"], 0.35),
        "input-cursor-background": p["accent"],
        "input-cursor-foreground": p["bg_0"],
        "footer-background": p["bg_0"],
        "scrollbar": p["bg_3"],
        "scrollbar-hover": p["border"],
        "scrollbar-active": p["accent"],
        "scrollbar-background": p["bg_0"],
        "scrollbar-background-hover": p["bg_0"],
        "scrollbar-background-active": p["bg_0"],
        "scrollbar-corner-color": p["bg_0"],
        "markdown-h1-color": p["accent"],
        "markdown-h1-background": "transparent",
        "markdown-h1-text-style": "bold",
        "markdown-h2-color": p["accent"],
        "markdown-h2-background": "transparent",
        "markdown-h2-text-style": "bold",
        "markdown-h3-color": p["fg"],
        "markdown-h3-background": "transparent",
        "markdown-h3-text-style": "bold",
        "markdown-h4-color": p["fg"],
        "markdown-h4-background": "transparent",
        "markdown-h4-text-style": "bold italic",
        "markdown-h5-color": p["fg_mute"],
        "markdown-h5-background": "transparent",
        "markdown-h5-text-style": "bold",
        "markdown-h6-color": p["fg_mute"],
        "markdown-h6-background": "transparent",
        "markdown-h6-text-style": "italic",
        "link-color": p["accent_2"],
        "link-color-hover": p["accent"],
        "link-background-hover": "transparent",
    })
    return Theme(
        name=textual_theme_name(key),
        primary=p["accent"],
        secondary=p["accent_2"],
        accent=p["accent_3"],
        warning=p["warn"],
        error=p["err"],
        success=p["ok"],
        foreground=p["fg"],
        background=p["bg_0"],
        surface=p["bg_1"],
        panel=p["bg_2"],
        boost=blend(p["bg_0"], p["fg"], 0.04),
        dark=True,
        variables=variables,
    )


# ── CSS builders (called once at module load and again on every theme switch) ──

def _build_global_css() -> str:
    """Return the app CSS string using the current module-level tokens.

    Only layout chrome lives here; transcript blocks carry their own
    ``DEFAULT_CSS`` built on the ``$jv-*`` theme variables.
    """
    return f"""
Screen {{
    background: {BG_0};
    color: {FG};
    layers: base overlay;
}}

#main {{
    height: 1fr;
    width: 100%;
    min-width: 0;
    background: {BG_0};
}}
#body {{
    width: 1fr;
    height: 100%;
    min-width: 0;
    layers: base overlay;  /* StickyPrompt floats over the transcript */
}}

/* ── Bottom dock: queue · ask · activity · popups · composer · footer ──
   Gutters match the transcript: 3 cols left; right = its 3 + scrollbar. */
#dock {{
    height: auto;
    padding: 0 4 0 3;
    background: {BG_0};
}}

/* Queued messages (tui/queue_bar.py): header + one row per message, each
   with ⚡ send now · ✎ edit · ✕ buttons on the right. */
#queuebar {{
    height: auto;
    max-height: 9;
    background: {BG_1};
    border-left: outer {ACCENT};
    padding: 0 1;
    margin: 1 0 1 0;
    overflow-y: auto;
    scrollbar-size-vertical: 1;
}}
#queuebar.hidden, #askbar.hidden, #popup.hidden {{
    display: none;
}}

#askbar {{
    height: auto;
    max-height: 16;
    background: {BG_0};
    color: {FG};
    border: round {ACCENT};
    padding: 0 1;
    margin: 1 0 0 0;
    overflow-y: auto;
}}

/* One blank row above (transcript padding) and below; the whole row
   collapses when there's nothing to show (ActivityLine.wanted). */
#activity {{
    height: 1;
    padding: 0;
    margin: 0 0 1 0;
    background: {BG_0};
    color: {FG_MUTE};
    overflow: hidden;
}}
#activity.-idle {{
    display: none;
}}

#popup {{
    height: auto;
    max-height: 14;
    background: {BG_1};
    padding: 0 0;
    margin: 0;
}}
#popup_hint {{
    height: 1;
    padding: 0 2;
    color: {FG_DIM};
    background: {BG_1};
}}
#popup_list {{
    height: auto;
    max-height: 10;
    text-wrap: nowrap;
    text-overflow: ellipsis;
    background: {BG_1};
    border: none;
    padding: 0;
    scrollbar-size-vertical: 1;
}}
#popup_list > .option-list--option {{
    padding: 0 1;
}}
#popup_list > .option-list--option-highlighted,
#popup_list:focus > .option-list--option-highlighted {{
    background: {blend(BG_1, ACCENT, 0.2)};
    color: {FG};
    text-style: none;
}}

#composer {{
    height: auto;
    background: {BG_2};
    border-left: outer {ACCENT};
    padding: 0 2;
    margin: 0;
}}
#composer.-busy {{
    border-left: outer {FG_DIM};
}}
#composer.-shell {{
    border-left: outer {WARN};
}}
/* Vertical breathing room lives on the children (not composer padding). */
#prompt_prefix {{
    width: 2;
    height: 1;
    margin: 1 0;
    color: {ACCENT};
    text-style: bold;
    background: {BG_2};
}}
#composer.-shell #prompt_prefix {{
    color: {WARN};
}}
#prompt {{
    height: auto;
    min-height: 1;
    max-height: 14;
    margin: 1 0;
    width: 1fr;
    background: {BG_2};
    border: none;
    padding: 0;
    scrollbar-size-vertical: 1;
}}
#prompt:focus {{
    border: none;
}}
#prompt > .text-area--placeholder {{
    color: {FG_DIM};
}}

/* Text lines up with the composer's content (bar + 2 cols padding);
   one blank row separates it from the composer. */
#footer {{
    height: 1;
    padding: 0 2 0 3;
    margin: 1 0 0 0;
    background: {BG_0};
    color: {FG_DIM};
}}
#footer_left {{
    width: 1fr;
    height: 1;
    overflow: hidden;
}}
#footer_right {{
    width: auto;
    height: 1;
    overflow: hidden;
}}

#web_qr_overlay.hidden {{ display: none; }}

/* ── Shared widget defaults ─────────────────────────────────────── */
Input, TextArea {{
    background: {BG_2};
    color: {FG};
}}
TextArea > .text-area--cursor-line {{
    background: transparent;
}}
TextArea > .text-area--cursor {{
    background: {ACCENT};
    color: {BG_0};
}}
*:focus TextArea > .text-area--selection,
TextArea > .text-area--selection {{
    background: {blend(BG_0, ACCENT, 0.3)};
    color: {FG};
}}

Toast {{
    background: {BG_2};
    color: {FG};
    border-left: outer {ACCENT};
    padding: 0 1;
}}
Toast.-information {{
    border-left: outer {ACCENT};
}}
Toast.-warning {{
    border-left: outer {WARN};
}}
Toast.-error {{
    border-left: outer {ERR};
}}
Toast .toast--title {{
    text-style: bold;
}}
ToastRack {{
    align: right top;
    padding: 1 2 0 0;
}}

Scrollbar {{
    scrollbar-background: {BG_0};
    scrollbar-color: {BG_3};
    scrollbar-color-hover: {BORDER};
    scrollbar-color-active: {ACCENT};
}}
"""


def _build_modal_css() -> str:
    """Return the shared modal chrome CSS (``TuiModalScreen.DEFAULT_CSS``).

    Dialogs are flat panels on a dimmed backdrop: no heavy frame, a bold
    title, and an accent-filled selection row. Colors are ``$jv-*`` theme
    variables, so the string is the same for every palette and Textual
    re-resolves it on each ``App.theme`` switch — open dialogs included.
    """
    return """
.tui-modal-screen {
    background: $jv-bg-0 60%;
    align: center middle;
}

.tui-modal-screen #modal {
    height: auto;
    background: $jv-bg-1;
    border: none;
    border-left: outer $jv-accent;
    padding: 1 3;
}

.tui-modal-screen #modal_title {
    color: $jv-fg;
    text-style: bold;
    padding: 0 1;
    margin-bottom: 1;
    width: 100%;
}

.tui-modal-screen #modal_status {
    color: $jv-fg-mute;
    padding: 0 1;
    margin-bottom: 1;
    width: 100%;
    height: auto;
}

.tui-modal-screen #modal_hint {
    color: $jv-fg-dim;
    padding: 0 1;
    margin-top: 1;
    width: 100%;
}

.tui-modal-screen Input {
    background: $jv-bg-2;
    color: $jv-fg;
    border: none;
    padding: 0 1;
    height: 1;
    margin: 0 0 1 0;
}
/* TuiModalScreen makes inputs compact; outrank Textual's `padding: 0`. */
.tui-modal-screen Input.-textual-compact {
    padding: 0 1;
}
.tui-modal-screen Input:focus {
    border: none;
    background: $jv-bg-3;
}
.tui-modal-screen Input > .input--placeholder {
    color: $jv-fg-dim;
}

.tui-modal-screen OptionList {
    background: $jv-bg-1;
    color: $jv-fg;
    border: none;
    padding: 0;
    text-wrap: nowrap;
    text-overflow: ellipsis;
    overflow-y: auto;
    scrollbar-background: $jv-bg-1;
    scrollbar-color: $jv-bg-4;
    scrollbar-color-hover: $jv-border;
    scrollbar-color-active: $jv-accent;
    scrollbar-size-vertical: 1;
}
.tui-modal-screen OptionList:focus {
    border: none;
    background-tint: transparent;
}
.tui-modal-screen OptionList > .option-list--option {
    padding: 0 1;
}
.tui-modal-screen OptionList > .option-list--option-highlighted,
.tui-modal-screen OptionList:focus > .option-list--option-highlighted {
    background: $jv-modal-select;
    color: $jv-fg;
    text-style: bold;
}
.tui-modal-screen OptionList > .option-list--option-hover {
    background: $jv-bg-3;
}
.tui-modal-screen OptionList > .option-list--option-disabled {
    color: $jv-fg-dim;
    text-style: none;
}
.tui-modal-screen #modal_status, .tui-modal-screen #model_subtitle,
.tui-modal-screen #modal_subtitle {
    color: $jv-fg-dim;
    padding: 0 1;
    margin-bottom: 1;
}
.tui-modal-screen OptionList > .option-list--separator {
    color: $jv-bg-4;
}

.tui-modal-screen TextArea {
    background: $jv-bg-2;
    color: $jv-fg;
    border: tall $jv-bg-2;
    padding: 0 1;
}
.tui-modal-screen TextArea:focus {
    border: tall $jv-bg-3;
}

.tui-modal-screen Static {
    background: transparent;
}
.tui-modal-screen Button {
    background: $jv-bg-3;
    color: $jv-fg;
    border: none;
    min-width: 8;
    height: 1;
    margin: 0 1;
}
.tui-modal-screen Button:focus, .tui-modal-screen Button:hover {
    background: $jv-accent;
    color: $jv-bg-0;
    text-style: bold;
}
"""


# ── Pre-built CSS strings (rebuilt by set_theme()) ───────────────────────

GLOBAL_CSS: str = ""
MODAL_CSS: str = ""


# ── Theme switcher ────────────────────────────────────────────────────────

_ACTIVE_THEME: str = DEFAULT_THEME


def set_theme(name: str) -> None:
    """Switch all theme tokens + CSS strings to the named palette.

    The app applies the change live via ``ArkadTUI._apply_theme_runtime``
    (stylesheet rebuild + ``App.theme`` swap).
    """
    global _ACTIVE_THEME
    global BG_0, BG_1, BG_2, BG_3, BG_4
    global BORDER, BORDER_FC
    global FG, FG_MUTE, FG_DIM, SEP
    global OK, WARN, ERR
    global ACCENT, ACCENT_2, ACCENT_3
    global GLOBAL_CSS, MODAL_CSS

    p = PALETTES.get(name)
    if p is None:
        name = DEFAULT_THEME
        p = PALETTES[name]

    _ACTIVE_THEME = name

    BG_0 = p["bg_0"]
    BG_1 = p["bg_1"]
    BG_2 = p["bg_2"]
    BG_3 = p["bg_3"]
    BG_4 = p["bg_4"]
    BORDER = p["border"]
    BORDER_FC = p["border_fc"]
    FG = p["fg"]
    FG_MUTE = p["fg_mute"]
    FG_DIM = p["fg_dim"]
    SEP = p["sep"]
    OK = p["ok"]
    WARN = p["warn"]
    ERR = p["err"]
    ACCENT = p["accent"]
    ACCENT_2 = p["accent_2"]
    ACCENT_3 = p["accent_3"]

    GLOBAL_CSS = _build_global_css()
    MODAL_CSS = _build_modal_css()


def active_theme() -> str:
    """Return the name of the currently active theme."""
    return _ACTIVE_THEME


def theme_names() -> list[str]:
    """Palette names in picker order (described ones first)."""
    ordered = [n for n in THEME_DESCRIPTIONS if n in PALETTES]
    return ordered + [n for n in PALETTES if n not in THEME_DESCRIPTIONS]


# ── Init at module load time ─────────────────────────────────────────────
set_theme(DEFAULT_THEME)
