#!/usr/bin/env python3
"""Generate the Arkad Agent brand assets (logo, README banner, social preview).

Run from the repo root:  python scripts/make_brand_assets.py

Everything is derived from the product itself:
- the half-block ARKAD wordmark used by the TUI welcome screen
  (arkad/tui/transcript.py::_LOGO) — rasterised as literal quarter-blocks,
  so no font is needed for the mark;
- the Nightwing palette from arkad/tui/theme.py (midnight base, electric
  blue #0088ff -> neon cyan #00d2ff accent ramp, steel chrome).

Outputs (overwritten in place):
    assets/arkad-logo.png       1024x1024 mark  (GitHub avatar / docs icon)
    assets/arkad-banner.png     1280x400 README header
    assets/social-preview.png   1280x640 OpenGraph image
"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# ── Nightwing palette (arkad/tui/theme.py) ───────────────────────────────────
BG_0 = "#05070a"       # Midnight Black
BG_1 = "#0c162e"       # Stalker Navy (panels)
BORDER = "#4a5d78"     # Escrima Steel
FG = "#b9cadb"         # Acrobat Silver
FG_DIM = "#4a5d78"
ACCENT = "#0088ff"     # Electric Blue
ACCENT_2 = "#00d2ff"   # Neon Glow
OK = "#56d364"

# ── The wordmark, exactly as the TUI prints it ───────────────────────────────
WORDMARK = (
    "▄▀█ █▀█ █ █ ▄▀█ █▀▄",
    "█▀█ █▀▄ █▀▄ █▀█ █▄▀",
)

FONT_DIR = pathlib.Path("/usr/share/fonts/jetbrains-mono-fonts")


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / f"JetBrainsMono-{weight}.otf"), size)


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def lerp_rgb(a: str, b: str, t: float) -> tuple[int, int, int]:
    ca, cb = _hex_rgb(a), _hex_rgb(b)
    return tuple(round(ca[i] + (cb[i] - ca[i]) * t) for i in range(3))  # type: ignore[return-value]


def scanlines(img: Image.Image, step: int = 4, alpha: int = 22) -> None:
    """Subtle CRT scanlines — the terminal texture, kept barely visible."""
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for y in range(0, img.size[1], step):
        d.line([(0, y), (img.size[0], y)], fill=(0, 0, 0, alpha), width=1)
    img.alpha_composite(ov)


def corner_brackets(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int],
                    color: tuple[int, int, int], arm: int, width: int = 3) -> None:
    """Four L-shaped viewfinder brackets — restrained 'focus' framing."""
    x0, y0, x1, y1 = box
    for (cx, cy, dx, dy) in (
        (x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1),
    ):
        d.line([(cx, cy), (cx + dx * arm, cy)], fill=color, width=width)
        d.line([(cx, cy), (cx, cy + dy * arm)], fill=color, width=width)


def draw_wordmark(d: ImageDraw.ImageDraw, x0: int, y0: int, cell_w: int,
                  band_h: int, ramp: tuple[str, str] = (ACCENT, ACCENT_2)) -> tuple[int, int]:
    """Rasterise WORDMARK as quarter blocks and return (width, height).

    Each column of the art is two stacked glyphs; a glyph fills the top and/or
    bottom half of its band — the same thing a terminal font does with ▀/▄/█.
    """
    rows = len(WORDMARK)
    cols = max(len(r) for r in WORDMARK)
    qh = band_h // 2
    for c in range(cols):
        for r in range(rows):
            g = WORDMARK[r][c] if c < len(WORDMARK[r]) else " "
            if g == " ":
                continue
            upper, lower = g in "█▀", g in "█▄"
            color = lerp_rgb(ramp[0], ramp[1], c / max(1, cols - 1))
            cx = x0 + c * cell_w
            cy = y0 + r * band_h
            if upper:
                d.rectangle([cx, cy, cx + cell_w - 1, cy + qh - 1], fill=color)
            if lower:
                d.rectangle([cx, cy + qh, cx + cell_w - 1, cy + band_h - 1], fill=color)
    return cols * cell_w, rows * band_h


def glow(img: Image.Image, center: tuple[int, int], radius: int,
         color: str, strength: float) -> None:
    """Soft radial tint — the only gradient in the whole kit."""
    w, h = img.size
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    cx, cy = center
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
              fill=(*_hex_rgb(color), int(255 * strength)))
    ov = ov.filter(ImageFilter.GaussianBlur(radius / 2))
    img.alpha_composite(ov)


def text_w(d: ImageDraw.ImageDraw, s: str, f: ImageFont.FreeTypeFont) -> int:
    b = d.textbbox((0, 0), s, font=f)
    return b[2] - b[0]


def letterspaced(d: ImageDraw.ImageDraw, cx: int, y: int, s: str,
                 f: ImageFont.FreeTypeFont, tracking: int,
                 fill: tuple[int, int, int]) -> int:
    """Center a tracked-out line; returns its pixel width."""
    widths = [d.textbbox((0, 0), ch, font=f)[2] for ch in s]
    total = sum(widths) + tracking * (len(s) - 1)
    x = cx - total // 2
    for ch, cw in zip(s, widths):
        d.text((x, y), ch, font=f, fill=fill)
        x += cw + tracking
    return total


# ── Logo: square mark — block ARKAD over tracked-out AGENT ───────────────────
def make_logo() -> Image.Image:
    S = 1024
    img = Image.new("RGBA", (S, S), _hex_rgb(BG_0) + (255,))
    glow(img, (S // 2, int(S * 0.40)), int(S * 0.55), ACCENT, 0.10)
    d = ImageDraw.Draw(img)
    corner_brackets(d, (58, 58, S - 58, S - 58), (*_hex_rgb(BORDER), 255), arm=64, width=4)

    cell_w, band_h = 36, 46
    wm_w = max(len(r) for r in WORDMARK) * cell_w
    wm_h = len(WORDMARK) * band_h
    x0, y0 = (S - wm_w) // 2, 372
    draw_wordmark(d, x0, y0, cell_w, band_h)

    # "AGENT" tracked to the wordmark width so the two lines lock up.
    f = font("SemiBold", 88)
    letterspaced(d, S // 2, y0 + wm_h + 62, "AGENT", f,
                  tracking=(wm_w - text_w(d, "AGENT", f)) // 4, fill=_hex_rgb(FG))

    f_sm = font("Regular", 34)
    line = "$ arkad"
    lw = text_w(d, line, f_sm)
    cw = 20  # cursor block
    x = (S - lw - cw - 10) // 2
    d.text((x, y0 + wm_h + 210), "$", font=f_sm, fill=_hex_rgb(OK))
    d.text((x + text_w(d, "$ ", f_sm), y0 + wm_h + 210), "arkad", font=f_sm, fill=_hex_rgb(FG_DIM))
    d.rectangle([x + lw + 10, y0 + wm_h + 212, x + lw + 10 + cw, y0 + wm_h + 212 + 38],
                fill=_hex_rgb(ACCENT_2))

    scanlines(img)
    return img


# ── Banner: wide README header ───────────────────────────────────────────────
def make_banner() -> Image.Image:
    W, H = 1280, 400
    img = Image.new("RGBA", (W, H), _hex_rgb(BG_0) + (255,))
    glow(img, (300, H // 2), 420, ACCENT, 0.13)
    glow(img, (W - 260, H - 60), 320, ACCENT_2, 0.07)
    d = ImageDraw.Draw(img)

    # Left: the logo, squashed into a rounded terminal tile.
    tile = 264
    tx, ty = 72, (H - tile) // 2
    d.rounded_rectangle([tx, ty, tx + tile, ty + tile], radius=28,
                        fill=_hex_rgb(BG_1), outline=(*_hex_rgb(BORDER), 255), width=3)
    # tile title bar — three dim dots + a path, like a terminal window
    for i in range(3):
        d.ellipse([tx + 24 + i * 26, ty + 24, tx + 38 + i * 26, ty + 38],
                  fill=_hex_rgb(FG_DIM))
    d.text((tx + 24, ty + 60), "arkad", font=font("Regular", 26), fill=_hex_rgb(FG_DIM))
    d.line([(tx + 20, ty + 104), (tx + tile - 20, ty + 104)], fill=(*_hex_rgb(BORDER), 255), width=2)
    cell_w, band_h = 9, 13
    wm_w = max(len(r) for r in WORDMARK) * cell_w
    wm_h = len(WORDMARK) * band_h
    draw_wordmark(d, tx + (tile - wm_w) // 2, ty + 152, cell_w, band_h)
    d.rectangle([tx + (tile - wm_w) // 2 + wm_w + 8, ty + 152 + band_h - 14,
                 tx + (tile - wm_w) // 2 + wm_w + 20, ty + 152 + band_h],
                fill=_hex_rgb(ACCENT_2))

    # Right: name + tagline.
    lx = tx + tile + 64
    f_title = font("ExtraBold", 96)
    d.text((lx, 96), "ARKAD", font=f_title, fill=_hex_rgb(ACCENT))
    w_ad = text_w(d, "ARKAD ", f_title)
    d.text((lx + w_ad, 96), "AGENT", font=f_title, fill=_hex_rgb(FG))

    f_tag = font("Regular", 40)
    d.text((lx, 226), "A terminal-native AI coding agent", font=f_tag, fill=_hex_rgb(FG))

    chips = ["free tier", "multi-provider", "MCP", "web remote"]
    avail = W - lx - 48
    for size in (28, 26, 24, 22, 20):
        f_chip = font("Medium", size)
        widths = [text_w(d, f"  {c}  ", f_chip) for c in chips]
        if sum(widths) + 16 * (len(chips) - 1) <= avail:
            break
    x, y = lx, 302
    for c, w in zip(chips, widths):
        label = f"  {c}  "
        d.rounded_rectangle([x, y, x + w, y + 44], radius=10,
                            outline=(*_hex_rgb(BORDER), 255), width=2)
        d.text((x, y + 6), label, font=f_chip, fill=_hex_rgb(FG_DIM))
        x += w + 16
    assert x - 16 - lx <= avail, "banner chips overflow"

    scanlines(img)
    return img


# ── Social preview: OpenGraph card ───────────────────────────────────────────
def make_social() -> Image.Image:
    W, H = 1280, 640
    img = Image.new("RGBA", (W, H), _hex_rgb(BG_0) + (255,))
    glow(img, (W // 2, 250), 520, ACCENT, 0.12)
    d = ImageDraw.Draw(img)
    corner_brackets(d, (40, 40, W - 40, H - 40), (*_hex_rgb(BORDER), 255), arm=48, width=3)

    f = font("Regular", 30)
    letterspaced(d, W // 2, 96, "T E R M I N A L   A I   C O D I N G   A G E N T",
                 f, tracking=0, fill=_hex_rgb(FG_DIM))

    cell_w, band_h = 44, 56
    wm_w = max(len(r) for r in WORDMARK) * cell_w
    wm_h = len(WORDMARK) * band_h
    x0, y0 = (W - wm_w) // 2, 190
    draw_wordmark(d, x0, y0, cell_w, band_h)

    f2 = font("SemiBold", 76)
    letterspaced(d, W // 2, y0 + wm_h + 48, "AGENT", f2,
                  tracking=(wm_w - text_w(d, "AGENT", f2)) // 4, fill=_hex_rgb(FG))

    f3 = font("Regular", 34)
    tag = "arkad — free tier by default · bring your own model"
    d.text(((W - text_w(d, tag, f3)) // 2, y0 + wm_h + 172), tag,
           font=f3, fill=_hex_rgb(FG_DIM))

    scanlines(img)
    return img


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    for name, img in (
        ("arkad-logo.png", make_logo()),
        ("arkad-banner.png", make_banner()),
        ("social-preview.png", make_social()),
    ):
        out = ASSETS / name
        img.convert("RGB").save(out, optimize=True)
        print("saved", out.relative_to(ROOT), img.size)


if __name__ == "__main__":
    main()
