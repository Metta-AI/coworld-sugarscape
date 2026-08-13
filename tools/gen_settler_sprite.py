#!/usr/bin/env python3
"""Author the settler atlas: a gnome that reads at one board cell.

    python3 tools/gen_settler_sprite.py

Writes src/sugarscape/sprites/settler.json, which tools/build_viewer.py inlines.

WHY THIS IS AUTHORED RATHER THAN EXTRACTED
------------------------------------------
tools/export_settler.nim pulls heartleaf's gnomes out of the .aseprite and
area-downsamples them. That is the right tool for the art at its own size and the
wrong one here: heartleaf draws a ~26x29 figure with human proportions, and human
proportions at sixteen pixels are a blob with a smudge on top. The owner's read
was blunt and correct — "these don't look like gnomes".

So the silhouette is authored for the size it is actually seen at: MOSTLY HAT AND
HEAD, a small body, on a 16x16 grid. Head and hat take thirteen of the sixteen
rows and the body gets three. That is the standard answer for a sprite this small
and it is what makes a gnome legible as a gnome.

The palette is still heartleaf's — the beard, skin and boot values are lifted
from the decoded sheet — so the settlers stay of a piece with that art.

THE HAT GROWS UPWARD, NOT OUTWARD
---------------------------------
A measured pass earlier chose brim WIDTH for the wealth signal, because width
survives the 4.5:1 downscale better than crown height. That was true and still
missed: a wider brim reads as a different hat, not a bigger one, and the owner
could not see the change. Height reads as MORE. It only became affordable once
the figure was rebuilt around the hat — with thirteen rows to play with, the
crown runs 4 / 6 / 8 rows, a 2x span from poorest to richest.

WALK
----
Two frames per rung. The legs swap and the whole figure bobs a pixel, so a moving
settler walks and a settled one stands still. Sugarscape movement is a teleport to
the best cell in vision, so this is the interpolation made legible, not a claim
about gait.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src/sugarscape/sprites/settler.json"

W = H = 16
RUNGS = 3
FRAMES = 2

# Palette slots. 0 is transparent. `hat` and `tunic` are the roles the viewer
# repaints per tribe; everything else is left as authored.
TRANSPARENT, HAT_LIT, HAT_DIM, BEARD, SKIN, TUNIC, BOOT = range(7)
PALETTE = [
    "#00000000",
    "#f8d152ff",  # hat, lit    — repainted per tribe
    "#c08c2eff",  # hat, shadow — repainted per tribe
    "#efe1cfff",  # beard, from heartleaf's sheet
    "#e5cbb5ff",  # skin, from heartleaf's sheet
    "#7fb3d5ff",  # tunic       — repainted per tribe
    "#3b2f22ff",  # boots and eyes
]

BRIM_Y = 7            # the hat's brim row; everything above it is crown
HAT_ROWS = [4, 6, 8]  # crown height per rung — the wealth signal


def blank() -> list[list[int]]:
    return [[TRANSPARENT] * W for _ in range(H)]


def draw_hat(px: list[list[int]], rung: int) -> None:
    """A cone that grows upward, plus a brim that does not."""
    crown = HAT_ROWS[rung]
    top = BRIM_Y - crown
    for y in range(top, BRIM_Y):
        # Widen linearly from a 1px tip to the brim's shoulders.
        along = (y - top) / max(1, crown - 1)
        half = round(0.5 + along * 3.2)
        for x in range(8 - half, 8 + half + 1):
            if 0 <= x < W:
                # Light on the left, shadow on the right: one light source, and
                # the two stops are what stop the cone reading as a flat wedge.
                px[y][x] = HAT_LIT if x <= 8 else HAT_DIM
    # The brim is fixed, so every rung shares a base and only the crown moves.
    for x in range(3, 13):
        px[BRIM_Y][x] = HAT_LIT if x <= 8 else HAT_DIM
    px[BRIM_Y][3] = HAT_DIM
    px[BRIM_Y][12] = HAT_DIM


def draw_head(px: list[list[int]]) -> None:
    """A wide face band over a beard that tapers — the gnome's whole identity."""
    face = BRIM_Y + 1
    for x in range(4, 12):
        px[face][x] = SKIN
    for x in range(3, 13):
        px[face + 1][x] = SKIN
    # Eyes, one pixel each. At this size they are the difference between a face
    # and a bald patch.
    px[face + 1][6] = BOOT
    px[face + 1][9] = BOOT
    # Beard, widest under the face and tapering to a point.
    for x in range(3, 13):
        px[face + 2][x] = BEARD
    for x in range(4, 12):
        px[face + 3][x] = BEARD
    for x in range(6, 10):
        px[face + 4][x] = BEARD


def draw_body(px: list[list[int]], frame: int) -> None:
    """Three rows: a tunic sliver and the legs that carry the walk."""
    torso = BRIM_Y + 6
    for x in range(5, 11):
        px[torso][x] = TUNIC
    # Legs alternate between frames, so a moving settler reads as walking.
    left, right = (5, 9) if frame == 0 else (6, 10)
    for x in (left, left + 1):
        px[torso + 1][x] = TUNIC
        px[torso + 2][x] = BOOT
    for x in (right, right + 1):
        px[torso + 1][x] = TUNIC
        px[torso + 2][x] = BOOT


def build() -> bytes:
    out = bytearray()
    for rung in range(RUNGS):
        for frame in range(FRAMES):
            px = blank()
            draw_hat(px, rung)
            draw_head(px)
            draw_body(px, frame)
            # A one-pixel bob on the off frame. Without it the legs swap under a
            # perfectly still body, which reads as a shuffle rather than a walk.
            if frame == 1:
                px = px[1:] + [[TRANSPARENT] * W]
            for row in px:
                out.extend(row)
    return bytes(out)


def main() -> None:
    pix = build()
    assert len(pix) == RUNGS * FRAMES * W * H, len(pix)
    atlas = {
        "v": 2,
        "w": W,
        "h": H,
        "rungs": RUNGS,
        "frames": FRAMES,
        "palette": PALETTE,
        # No `outline` role: an ink keyline around a 16px gnome draws a second
        # gnome. Contrast comes from the body values, which clear 7:1 on the
        # plate, and from the beard, which is the brightest thing on the figure.
        "hat": [HAT_LIT, HAT_DIM],
        "tunic": [TUNIC, TUNIC],
        "pix": base64.b64encode(pix).decode(),
    }
    OUT.write_text(json.dumps(atlas, separators=(",", ":")))
    print(f"{OUT}  {OUT.stat().st_size} B  {RUNGS} rungs x {FRAMES} frames")
    for rung in range(RUNGS):
        base = rung * FRAMES * W * H
        print(f"--- rung {rung} (crown {HAT_ROWS[rung]} rows) ---")
        for y in range(H):
            row = pix[base + y * W:base + (y + 1) * W]
            print("".join("." if p == 0 else str(p) for p in row))


if __name__ == "__main__":
    main()
