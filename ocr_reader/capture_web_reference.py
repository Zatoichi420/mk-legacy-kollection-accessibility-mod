"""
One-off helper to OCR an externally-sourced reference image (e.g. a web
screenshot of one of the emulated PS1 games' menus) and save it into
known_screens/ using the same format main.py's F10 capture produces -
just tagged with where it came from, since these aren't captured live
from the actual running game/window.

Usage: python capture_web_reference.py <game_slug> <image_path> [source_url]
"""

import asyncio
import json
import os
import sys

from PIL import Image

import main as reader

KNOWN_SCREENS_DIR = reader.KNOWN_SCREENS_DIR


def main(game_slug, image_path, source_url=None):
    img = Image.open(image_path)
    lines = asyncio.run(reader.ocr_image(img))
    screen_texts = [l["text"] for l in lines]
    slug = reader.slugify(" ".join(screen_texts)) if screen_texts else "blank_screen"

    name = f"{game_slug}__{slug}"
    suffix = 2
    os.makedirs(KNOWN_SCREENS_DIR, exist_ok=True)
    while os.path.exists(os.path.join(KNOWN_SCREENS_DIR, name + ".png")):
        name = f"{game_slug}__{slug}_{suffix}"
        suffix += 1

    img.convert("RGB").save(os.path.join(KNOWN_SCREENS_DIR, name + ".png"))
    data = {
        "source": "web",
        "source_url": source_url,
        "source_image_path": os.path.abspath(image_path),
        "verified_against_live_game": False,
        "lines": [{"text": l["text"], "bbox": l["bbox"]} for l in lines],
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
