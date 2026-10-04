#!/usr/bin/env python3
import pathlib
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

ART = pathlib.Path('/tmp/art.txt').read_text().rstrip('\n').splitlines()
PALETTE = ["#00e5ff", "#00b8d4", "#00e5ff", "#ff2d95", "#d500f9", "#7c4dff", "#ff2d95"]
W, H = 1280, 640
img = Image.new('RGB', (W, H), '#05060a')

# radial tints baked as two blends
mask_cyan = Image.new('L', (W, H), 0)
ImageDraw.Draw(mask_cyan).ellipse([-300, -200, 500, 400], fill=70)
img = Image.blend(img, Image.new('RGB', (W, H), '#032030'), 0.0)
tint1 = Image.new('RGB', (W, H), '#032030')
img = ImageChops.composite(tint1, img, mask_cyan)
mask_mag = Image.new('L', (W, H), 0)
ImageDraw.Draw(mask_mag).ellipse([W - 500, H - 400, W + 300, H + 200], fill=70)
img = ImageChops.composite(Image.new('RGB', (W, H), '#1a0320'), img, mask_mag)

draw = ImageDraw.Draw(img)
FONT_B = '/usr/share/fonts/jetbrains-mono-fonts/JetBrainsMono-Bold.otf'
FONT_R = '/usr/share/fonts/jetbrains-mono-fonts/JetBrainsMono-Regular.otf'
big = ImageFont.truetype(FONT_B, 21)
small = ImageFont.truetype(FONT_R, 13)

def text_size(d, s, f):
    b = d.textbbox((0, 0), s, font=f)
    return b[2] - b[0], b[3] - b[1]

y = 90
tag = "T E R M I N A L   A I   C O D I N G   A G E N T"
tw, _ = text_size(draw, tag, small)
draw.text(((W - tw) / 2, y), tag, fill='#8be9fd', font=small)

y = 148
line_h = 23
for i, line in enumerate(ART):
    color = PALETTE[i % len(PALETTE)]
    lw, _ = text_size(draw, line, big)
    x = (W - lw) / 2
    glow = img.copy()
    gd = ImageDraw.Draw(glow)
    gd.text((x, y), line, fill=color, font=big)
    glow = glow.filter(ImageFilter.GaussianBlur(6))
    img = Image.blend(img, glow, 0.40)
    draw = ImageDraw.Draw(img)
    draw.text((x, y), line, fill=color, font=big)
    y += line_h

y += 28
sub = "local-first  ·  Cloud-first  ·  RTX 4050  ·  Ghostty / Kitty"
sw, _ = text_size(draw, sub, small)
draw.text(((W - sw) / 2, y), sub, fill='#6272a4', font=small)

pathlib.Path('assets').mkdir(exist_ok=True)
img.save('assets/social-preview.png', optimize=True)
print('saved', img.size)
