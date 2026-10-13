"""The screen library is what decides which pre-verified text gets spoken,
so a wrong match means confidently reading the wrong screen. These replay
the library's own screenshots through the matcher - the same offline check
PROGRESS.md section 5.5 did by hand, now run on every build."""

import glob
import itertools
import json
import os
import shutil

import pytest
from PIL import Image

import app_paths
from game_a11y_core.screen_library import MATCH_DISTANCE_THRESHOLD, ScreenLibrary, compute_dhash, hamming_distance

KNOWN_SCREENS = app_paths.bundled_known_screens_dir()


def _verified_json_files():
    files = []
    for path in sorted(glob.glob(os.path.join(KNOWN_SCREENS, "*.json"))):
        with open(path, encoding="utf-8") as f:
            if json.load(f).get("canonical_text"):
                files.append(path)
    return files


@pytest.fixture(scope="module")
def library():
    return ScreenLibrary(KNOWN_SCREENS)


def test_every_verified_entry_loads(library):
    assert len(library.entries) == len(_verified_json_files())
    assert len(library.entries) > 0


def test_every_entry_recognises_its_own_screenshot(library):
    for entry in library.entries:
        with Image.open(entry["png_path"]) as img:
            result = library.match(img.convert("RGB"))
        assert result is not None, f"{entry['screen_id']} didn't match its own screenshot"
        matched, distance = result
        assert matched["screen_id"] == entry["screen_id"]
        assert distance == 0


def test_no_two_screens_are_confusable(library):
    """For every pair, hash B's screenshot the way A would hash a live frame;
    it must land outside A's match threshold."""
    images = {e["screen_id"]: Image.open(e["png_path"]).convert("RGB") for e in library.entries}
    closest = None
    for a, b in itertools.permutations(library.entries, 2):
        frame = images[b["screen_id"]]
        if a["roi"] and a["capture_size"] and tuple(a["capture_size"]) != frame.size:
            continue  # match() skips this pairing too
        distance = hamming_distance(compute_dhash(frame, a["roi"]), a["hash"])
        limit = max(MATCH_DISTANCE_THRESHOLD, a.get("match_distance") or 0)
        assert distance > limit, f"{b['screen_id']} would be read as {a['screen_id']} (distance {distance})"
        closest = distance if closest is None else min(closest, distance)
    assert closest is not None


def test_resized_frame_never_matches_an_roi_entry(library):
    """A wrongly-sized frame must fall back to OCR, not hash the wrong crop
    (PROGRESS.md 6.2, finding 5)."""
    main_menu = next(e for e in library.entries if e["screen_id"] == "launcher__main_menu")
    assert main_menu["roi"]
    with Image.open(main_menu["png_path"]) as img:
        resized = img.convert("RGB").resize((960, 540))
    result = library.match(resized)
    assert result is None or result[0]["screen_id"] != "launcher__main_menu"


def test_add_directory_loads_a_second_folder(tmp_path, library):
    source = next(e for e in library.entries if e["screen_id"] == "launcher__play_menu")
    stem = os.path.splitext(source["png_path"])[0]
    with open(stem + ".json", encoding="utf-8") as f:
        data = json.load(f)
    data["screen_id"] = "user__extra_screen"
    with open(tmp_path / "user__extra_screen.json", "w", encoding="utf-8") as f:
        json.dump(data, f)
    shutil.copy(stem + ".png", tmp_path / "user__extra_screen.png")

    combined = ScreenLibrary(KNOWN_SCREENS)
    combined.add_directory(str(tmp_path))
    assert len(combined.entries) == len(library.entries) + 1
    assert any(e["screen_id"] == "user__extra_screen" for e in combined.entries)


def test_missing_directory_is_ignored(tmp_path):
    lib = ScreenLibrary(str(tmp_path / "does-not-exist"))
    lib.add_directory(str(tmp_path / "also-missing"))
    assert lib.entries == []


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _windowed(name):
    with Image.open(os.path.join(FIXTURES, name)) as img:
        return img.convert("RGB").crop((0, 0, 1280, 720))


def test_windowed_game_library_matches(library):
    """Live 2026-10-12: windowed at 1280x720 the Game Library scored 25-28,
    just past the default threshold, and flipped to OCR on every move. Its
    entry's match_distance covers that."""
    result = library.match(_windowed("windowed_game_library_720p.png"))
    assert result is not None and result[0]["screen_id"] == "launcher__game_library_tabs"


def test_windowed_game_submenu_is_not_the_game_library(library):
    """The look-alike under the same GAME LIBRARY title must still miss."""
    result = library.match(_windowed("windowed_game_submenu_720p.png"))
    assert result is None or result[0]["screen_id"] != "launcher__game_library_tabs"
