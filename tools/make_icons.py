#!/usr/bin/env python3
"""Every app icon file, drawn from the glyph (BETA-6, FRIENDS.md ruling LOGO-2; design/logo/README.md).

The glyph is \\mathbb{Z}: the character "Z" of the AMS msbm10 font (design/logo/font/msbm10.pfb, SIL Open Font
License 1.1, design/logo/font/OFL.txt), in the dark text colour #101113 on the light tile #EDEDEF (LOGO-1), its
height 0.578 of the tile's and its box centred on the tile, as in design/logo/zugzwang-logo.png.

* **macOS** (`icon.icns`): Apple's template. The tile 824 x 824 centred in a 1024 x 1024 canvas, corner radius
  185.4, the standard shadow (black at 50 %, a 28 px blur, 12 px down; the blur is drawn as a Gaussian of
  sigma 14, as CSS draws `0 12px 28px`), rendered at 1024 px (supersampled 4x) and only ever scaled down for
  the smaller members. Also written to design/logo/zugzwang-icon-macos.png.
* **Windows and Linux** (`icon.ico`, the PNGs): the tile to the edges, as before (LOGO-1). Ruling LOGO-2 keeps
  the Windows icon unchanged, so they are written only with `--all`.

    python tools/make_icons.py            # icon.icns and design/logo/zugzwang-icon-macos.png
    python tools/make_icons.py --all      # also every Windows / Linux file in desktop/src-tauri/icons
    python tools/make_icons.py --check    # each .icns member's size and transparent margin, measured

Needs Pillow with FreeType (`pip install pillow`; requirements-dev.txt) and macOS's `iconutil` for the .icns.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "design/logo/font/msbm10.pfb"
ICONS = ROOT / "desktop/src-tauri/icons"
MASTER = ROOT / "design/logo/zugzwang-icon-macos.png"

TILE = (0xED, 0xED, 0xEF)
INK = (0x10, 0x11, 0x13)
GLYPH_OF_TILE = 296 / 512          # the glyph's height over the tile's, measured on zugzwang-logo.png
FULL_RADIUS_OF_TILE = 97 / 512     # that file's corner radius over its side
SS = 4                             # supersampling

# Apple's macOS template, at 1024 px
CANVAS, TILE_PX, RADIUS = 1024, 824, 185.4
SHADOW_ALPHA, SHADOW_SIGMA, SHADOW_DY = 0.5, 14, 12

ICNS_MEMBERS = {  # iconset name -> pixels
    "icon_16x16.png": 16, "icon_16x16@2x.png": 32, "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128, "icon_128x128@2x.png": 256, "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
}
FULL_PNGS = {"32x32.png": 32, "64x64.png": 64, "128x128.png": 128, "128x128@2x.png": 256, "icon.png": 512,
             "Square30x30Logo.png": 30, "Square44x44Logo.png": 44, "Square71x71Logo.png": 71, "Square89x89Logo.png": 89,
             "Square107x107Logo.png": 107, "Square142x142Logo.png": 142, "Square150x150Logo.png": 150,
             "Square284x284Logo.png": 284, "Square310x310Logo.png": 310, "StoreLogo.png": 50}
ICO_SIZES = [16, 24, 32, 48, 64, 256]


def glyph_mask(height: int) -> Image.Image:
    """The glyph's coverage, cropped to its ink, exactly `height` px tall (drawn larger, never enlarged)."""
    size = int(height * 1.6)
    while True:
        font = ImageFont.truetype(str(FONT), size)
        l, t, r, b = font.getbbox("Z")
        if b - t >= height:
            break
        size = int(size * 1.1) + 1
    im = Image.new("L", (r - l + 8, b - t + 8), 0)
    ImageDraw.Draw(im).text((4 - l, 4 - t), "Z", font=font, fill=255)
    im = im.crop(im.getbbox())
    w = round(im.width * height / im.height)
    return im.resize((w, height), Image.LANCZOS)


def tile_image(side: int, radius: float) -> Image.Image:
    """The tile with its glyph, `side` px square, transparent outside its rounded corners."""
    tile = Image.new("RGBA", (side, side), TILE + (0,))
    shape = Image.new("L", (side, side), 0)
    ImageDraw.Draw(shape).rounded_rectangle((0, 0, side - 1, side - 1), radius=radius, fill=255)
    tile.putalpha(shape)
    g = glyph_mask(round(side * GLYPH_OF_TILE))
    ink = Image.new("RGBA", g.size, INK + (255,))
    tile.paste(ink, ((side - g.width) // 2, (side - g.height) // 2), g)
    return tile


def macos_master() -> Image.Image:
    """Apple's template at 1024 px (drawn at 4096, then scaled down)."""
    n = CANVAS * SS
    side = TILE_PX * SS
    off = (n - side) // 2
    tile = tile_image(side, RADIUS * SS)
    shadow_a = Image.new("L", (n, n), 0)
    shadow_a.paste(tile.getchannel("A"), (off, off + SHADOW_DY * SS))
    shadow_a = shadow_a.filter(ImageFilter.GaussianBlur(SHADOW_SIGMA * SS)).point(lambda v: round(v * SHADOW_ALPHA))
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    out.putalpha(shadow_a)
    out.alpha_composite(tile, (off, off))
    return out.resize((CANVAS, CANVAS), Image.LANCZOS)


def full_bleed(px: int) -> Image.Image:
    n = px * SS
    return tile_image(n, n * FULL_RADIUS_OF_TILE).resize((px, px), Image.LANCZOS)


def write_icns(master: Image.Image, dest: Path) -> None:
    with tempfile.TemporaryDirectory() as d:
        iconset = Path(d) / "icon.iconset"
        iconset.mkdir()
        for name, px in ICNS_MEMBERS.items():
            (master if px == CANVAS else master.resize((px, px), Image.LANCZOS)).save(iconset / name)
        subprocess.run(["iconutil", "-c", "icns", "-o", str(dest), str(iconset)], check=True)


def check_icns(path: Path) -> list[str]:
    """Each member: its pixel size by its name, the tile's box (alpha >= 250) against the template's (824/1024 of
    the side, centred), and the margin outside the shadow's reach fully transparent. Returns the failures."""
    fails = []
    with tempfile.TemporaryDirectory() as d:
        iconset = Path(d) / "x.iconset"
        subprocess.run(["iconutil", "-c", "iconset", "-o", str(iconset), str(path)], check=True)
        names = sorted(p.name for p in iconset.iterdir())
        if set(names) != set(ICNS_MEMBERS):
            fails.append(f"members {names}")
        print(f"{'member':24} {'px':>5} {'tile box (l, t, r, b)':>24} {'expected':>24} {'clear rows':>10} {'clear cols':>10}")
        for name in names:
            im = Image.open(iconset / name).convert("RGBA")
            px = ICNS_MEMBERS.get(name, -1)
            a = im.getchannel("A")
            opaque = a.point(lambda v: 255 if v >= 250 else 0).getbbox()
            k = px / CANVAS
            lo = (CANVAS - TILE_PX) / 2 * k
            exp = (round(lo), round(lo), round(px - lo), round(px - lo))
            # the margin beyond the shadow's reach (3 sigma, less 12 px down at the top): transparent, alpha <= 3 (1 %)
            reach = (CANVAS - TILE_PX) / 2 - 3 * SHADOW_SIGMA
            top_clear = 0
            while top_clear < px and a.crop((0, top_clear, px, top_clear + 1)).getextrema()[1] <= 3:
                top_clear += 1
            left_clear = 0
            while left_clear < px and a.crop((left_clear, 0, left_clear + 1, px)).getextrema()[1] <= 3:
                left_clear += 1
            ok_size = im.size == (px, px)
            ok_box = opaque is not None and all(abs(o - e) <= max(1, round(2 * k)) for o, e in zip((opaque[0], opaque[1], opaque[2], opaque[3]), exp))
            ok_margin = top_clear >= int((reach + SHADOW_DY) * k * 0.9) and left_clear >= int(reach * k * 0.9)
            print(f"{name:24} {im.width:>5} {str(opaque):>24} {str(exp):>24} {top_clear:>10} {left_clear:>10}"
                  f"{'' if ok_size and ok_box and ok_margin else '   FAIL'}")
            if not ok_size:
                fails.append(f"{name}: {im.size}, expected {px}")
            if not ok_box:
                fails.append(f"{name}: tile box {opaque}, expected {exp}")
            if not ok_margin:
                fails.append(f"{name}: transparent margin {top_clear} rows / {left_clear} columns")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--all", action="store_true", help="also the Windows and Linux files (LOGO-2 keeps them unchanged)")
    ap.add_argument("--check", action="store_true", help="measure icon.icns's members; write nothing")
    ap.add_argument("--icons", type=Path, default=ICONS, help="the icons folder (default desktop/src-tauri/icons)")
    a = ap.parse_args()
    if a.check:
        fails = check_icns(a.icons / "icon.icns")
        print("\n".join(fails) if fails else "icon.icns: every member as the template")
        return 1 if fails else 0
    if not shutil.which("iconutil"):
        sys.exit("iconutil (macOS) is needed for the .icns")
    master = macos_master()
    master.save(MASTER)
    write_icns(master, a.icons / "icon.icns")
    print(f"wrote {a.icons / 'icon.icns'} and {MASTER.relative_to(ROOT)}")
    if a.all:
        for name, px in FULL_PNGS.items():
            full_bleed(px).save(a.icons / name)
        big = full_bleed(256)
        big.save(a.icons / "icon.ico", sizes=[(s, s) for s in ICO_SIZES])
        print(f"wrote {len(FULL_PNGS)} PNGs and icon.ico (the tile to the edges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
