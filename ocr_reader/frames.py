"""
Turning a raw window capture into the frames the reader works with.

Found 2026-10 while packaging: every screenshot in known_screens/ is only
the TOP-LEFT 1280x720 of a 1920x1080 game frame. The reader process wasn't
DPI-aware, so on the development PC (1080p at 150% display scaling) Windows
reported the game's client area as 1280x720 while PrintWindow drew the
full-size 1920x1080 image into it - everything right of x=1280 or below
y=720 was silently dropped. That's the real cause of several things
PROGRESS.md logged as separate puzzles: the main-menu list "cut off right
after KOMBAT KARD", the quit dialog missing its buttons, the submenu
description "truncated by the 1280px capture width", and Player 2's panel
cut off on the MK2 screens. On any PC with different scaling or resolution
the capture would have been framed differently again, and the library
wouldn't have matched at all.

The fix has two halves:
  1. main() makes the process DPI-aware, so captures are the true full
     frame at whatever size the game window really is.
  2. normalize() rescales that frame to REFERENCE_SIZE, and library_view()
     crops the same top-left LIBRARY_BOX the existing library was captured
     with. Every existing entry keeps matching unchanged (verified by
     tests/test_frames.py at 960x540 through 3840x2160), while live OCR,
     highlight detection on unrecognised screens and saved misses now get
     the whole screen.

Coordinates inside LIBRARY_BOX are identical in both views (it's a crop
anchored at 0,0 with no scaling), so library bboxes can be sampled on
either.
"""

import ctypes

from PIL import Image

REFERENCE_SIZE = (1920, 1080)
LIBRARY_BOX = (0, 0, 1280, 720)
ASPECT_TOLERANCE = 0.02


def enable_dpi_awareness():
    """Call once, first thing, before any window or GDI calls. Returns a
    description of what was enabled, for the log."""
    attempts = (
        ("per-monitor v2", lambda: ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))),
        ("per-monitor", lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0),
        ("system", lambda: ctypes.windll.user32.SetProcessDPIAware()),
    )
    for name, attempt in attempts:
        try:
            if attempt():
                return name
        except Exception:
            continue
    return "unavailable"


def aspect_ratio_ok(size):
    width, height = size
    if not width or not height:
        return False
    expected = REFERENCE_SIZE[0] / REFERENCE_SIZE[1]
    return abs((width / height) / expected - 1) <= ASPECT_TOLERANCE


def normalize(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    if img.size != REFERENCE_SIZE:
        img = img.resize(REFERENCE_SIZE, Image.LANCZOS)
    return img


def library_view(full: Image.Image) -> Image.Image:
    return full.crop(LIBRARY_BOX)
