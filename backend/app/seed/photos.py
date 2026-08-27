"""Procedurally drawn placeholder plate photographs for the seeded dataset.

These are not photographs and are not claimed to be. They exist so that signed
Storage URLs in a Phase 4/5 dashboard resolve to *something* rather than a
broken image icon, and so the upload/sign path is exercised end to end before
any real photo exists.

They must never be used to evaluate the Phase 2 vision pipeline. Section 6.5 is
explicit that no labelled dataset for tribal-Rajasthan dishes exists yet and has
to be bootstrapped during the pilot -- scoring a model against drawings would
manufacture exactly the false accuracy number that section warns against. Each
image is stamped with a visible watermark so it cannot be mistaken for field
data if it turns up in a screenshot.
"""

from __future__ import annotations

import io
import math
import random

from PIL import Image, ImageDraw

SIZE = 640
#: Roughly the colours of the PM POSHAN menu items in reference.MENU_ITEMS.
FOOD_COLOURS = [
    (214, 158, 46),  # dal
    (232, 213, 178),  # roti / rice
    (106, 141, 73),  # sabzi
    (245, 222, 120),  # khichdi
    (223, 202, 92),  # banana
    (247, 241, 227),  # milk
    (198, 122, 58),  # halwa
]


def draw_plate(variant: int) -> bytes:
    """Deterministically render one thali. Same variant -> identical bytes."""
    rng = random.Random(1000 + variant)
    img = Image.new("RGB", (SIZE, SIZE), (72, 66, 60))
    d = ImageDraw.Draw(img)

    cx = cy = SIZE // 2
    plate_r = 250
    d.ellipse(
        [cx - plate_r, cy - plate_r, cx + plate_r, cy + plate_r],
        fill=(238, 236, 231),
        outline=(196, 192, 185),
        width=6,
    )

    # Between three and five compartments, matching a typical prescribed menu.
    servings = rng.randint(3, 5)
    inner_r = plate_r - 70
    for i in range(servings):
        angle = 2 * math.pi * i / servings + rng.uniform(-0.15, 0.15)
        px = cx + int(inner_r * 0.55 * math.cos(angle))
        py = cy + int(inner_r * 0.55 * math.sin(angle))
        blob_r = rng.randint(58, 88)
        colour = FOOD_COLOURS[(variant + i) % len(FOOD_COLOURS)]
        d.ellipse(
            [px - blob_r, py - blob_r, px + blob_r, py + blob_r],
            fill=colour,
            outline=tuple(max(0, c - 34) for c in colour),
            width=3,
        )
        # A little texture so the blobs do not read as flat circles.
        for _ in range(rng.randint(6, 14)):
            tx = px + rng.randint(-blob_r + 12, blob_r - 12)
            ty = py + rng.randint(-blob_r + 12, blob_r - 12)
            tr = rng.randint(3, 9)
            d.ellipse(
                [tx - tr, ty - tr, tx + tr, ty + tr],
                fill=tuple(min(255, c + 22) for c in colour),
            )

    label = f"SYNTHETIC SEED IMAGE - NOT FIELD DATA  #{variant:02d}"
    d.rectangle([0, SIZE - 34, SIZE, SIZE], fill=(28, 26, 24))
    d.text((14, SIZE - 24), label, fill=(226, 222, 214))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return buf.getvalue()


def variants(count: int = 12) -> list[bytes]:
    return [draw_plate(i) for i in range(count)]
