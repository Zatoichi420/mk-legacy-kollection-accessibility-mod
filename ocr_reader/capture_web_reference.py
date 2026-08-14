"""
One-off helper to OCR an externally-sourced reference image (e.g. a web
screenshot of one of the emulated PS1 games' menus) and save it into
known_screens/ as a *candidate* entry.

IMPORTANT: like main.py's F10 capture, this writes canonical_text: null -
screen_library.py's loader silently skips any entry without it (see
PROGRESS.md section 5 on why raw/uncorrected OCR text is never trusted for
speech). The OCR text this script produces is frequently wrong on this
game's stylized/compressed fonts (confirmed repeatedly - see PROGRESS.md's
"web-sourcing results" entries), so every entry this script writes still
needs a human (or Claude, vision-capable) to look at the saved .png and
fill in canonical_text by hand before it's usable - this script alone does
NOT produce a ready-to-use library entry.

Usage: python capture_web_reference.py <game_slug> <image_path> [source_url]
"""

import asyncio
import json
import os
import sys
import time

from PIL import Image

import main as reader

KNOWN_SCREENS_DIR = reader.KNOWN_SCREENS_DIR


def main(game_slug, image_path, source_url=None):
    img = Image.open(image_path)
    lines = asyncio.run(reader.ocr_image(img))
    screen_texts = [l["text"] for l in lines]
    highlighted_text = reader.find_highlighted_text(img, lines)
    slug = reader.slugify(" ".join(screen_texts)) if screen_texts else "blank_screen"

    name = f"{game_slug}__{slug}"
    suffix = 2
    os.makedirs(KNOWN_SCREENS_DIR, exist_ok=True)
    while os.path.exists(os.path.join(KNOWN_SCREENS_DIR, name + ".png")):
        name = f"{game_slug}__{slug}_{suffix}"
        suffix += 1

    img.convert("RGB").save(os.path.join(KNOWN_SCREENS_DIR, name + ".png"))
    data = {
        "screen_id": name,
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "web",
        "source_url": source_url,
        "source_image_path": os.path.abspath(image_path),
        "canonical_text": None,  # needs hand verification before this entry is used for recognition
        "highlighted": highlighted_text,
        "capture_size": list(img.size),
        "ocr_lines_raw": [{"text": l["text"], "bbox": l["bbox"]} for l in lines],
    }
    with open(os.path.join(KNOWN_SCREENS_DIR, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Saved {name}: {screen_texts}")
    return name


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python capture_web_reference.py <game_slug> <image_path> [source_url]")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
