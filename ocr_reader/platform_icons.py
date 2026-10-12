"""
Naming the platform of the selected game in the Game Library carousel.

Added 2026-10-11. The carousel shows a game's title and year as text, but
its platform only as a small line-art icon to the left of the title. Many
versions share a title and year ("MORTAL KOMBAT, 1993" is the Genesis,
Super Nintendo, Game Boy and Game Gear versions), so without the icon,
moving between them said nothing at all - the spoken text didn't change.

The icons are distinct shapes, so a nearest-template match on a small
binarised copy, plus the icon's aspect ratio, tells them apart reliably.
Templates live in platform_icons/<Platform name>.png, cut from live
captures of every game in the ALL tab (see tests/test_platform_icons.py).
"""

import os

import numpy as np
from PIL import Image

# Reference-frame band the title row sits in, and how to find the icon in it.
BAND = (300, 865, 1620, 955)
BRIGHT = 150
GAP = 12
SIZE = 32
MAX_DISTANCE = 0.30  # mean absolute difference (0..1) above which we don't guess

_templates = None


def _template_dir():
    import app_paths

    return os.path.join(app_paths.RESOURCE_DIR, "platform_icons")


def icon_box(full):
    """Box of the icon left of the selected game's title, or None."""
    band = np.asarray(full.crop(BAND).convert("L")).astype(int)
    cols = np.where((band > BRIGHT).sum(axis=0) >= 2)[0]
    if not len(cols):
        return None
    start = prev = cols[0]
    for c in cols[1:]:
        if c - prev > GAP:
            break
        prev = c
    x1, x2 = BAND[0] + start - 4, BAND[0] + prev + 5
    if not 20 <= x2 - x1 <= 140:
        return None
    return (int(x1), BAND[1] - 3, int(x2), BAND[3] + 3)


def features(icon):
    gray = icon.convert("L")
    aspect = gray.width / max(gray.height, 1)
    small = np.asarray(gray.resize((SIZE, SIZE), Image.LANCZOS)).astype(float)
    binary = (small > BRIGHT * 0.8).astype(float)
    return aspect, binary


def load_templates(directory=None):
    global _templates
    directory = directory or _template_dir()
    found = {}
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        names = []
    for name in names:
        if name.lower().endswith(".png"):
            with Image.open(os.path.join(directory, name)) as img:
                found[name[:-4]] = features(img.convert("RGB"))
    _templates = found
    return found


def classify(full):
    """Platform name for the selected game's icon, or None if unsure."""
    templates = _templates if _templates is not None else load_templates()
    box = icon_box(full)
    if box is None or not templates:
        return None
    aspect, binary = features(full.crop(box))
    best, best_distance = None, None
    for name, (t_aspect, t_binary) in templates.items():
        distance = float(np.abs(binary - t_binary).mean()) + abs(aspect - t_aspect) * 0.25
        if best_distance is None or distance < best_distance:
            best, best_distance = name, distance
    return best if best_distance is not None and best_distance <= MAX_DISTANCE else None
