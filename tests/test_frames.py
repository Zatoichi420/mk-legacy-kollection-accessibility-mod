"""The library was captured as the top-left 1280x720 of a 1920x1080 frame
(see frames.py). Rebuild such a full frame from each library screenshot,
show it at other window sizes, and check that normalize() + library_view()
still recognise it - i.e. the reader works for players whose resolution or
display scaling differs from the development PC's."""

import pytest
from PIL import Image

import app_paths
import frames
from game_a11y_core.screen_library import ScreenLibrary

WINDOW_SIZES = [(1920, 1080), (2560, 1440), (1600, 900), (1280, 720), (960, 540), (3840, 2160)]


@pytest.fixture(scope="module")
def library():
    return ScreenLibrary(app_paths.bundled_known_screens_dir())


def _live_entries(library):
    return [e for e in library.entries if tuple(e["capture_size"] or ()) == frames.LIBRARY_BOX[2:]]


def _full_frame_from(entry):
    with Image.open(entry["png_path"]) as img:
        view = img.convert("RGB")
    full = Image.new("RGB", frames.REFERENCE_SIZE)
    full.paste(view, (0, 0))
    return full


def test_live_library_entries_are_library_view_sized(library):
    assert _live_entries(library), "expected live-captured 1280x720 entries"


@pytest.mark.parametrize("window_size", WINDOW_SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_recognised_at_any_16_9_window_size(library, window_size):
    for entry in _live_entries(library):
        shown = _full_frame_from(entry).resize(window_size, Image.LANCZOS)
        result = library.match(frames.library_view(frames.normalize(shown)))
        assert result is not None, f"{entry['screen_id']} not recognised at {window_size}"
        assert result[0]["screen_id"] == entry["screen_id"]


def test_normalize_is_identity_at_reference_size():
    img = Image.new("RGB", frames.REFERENCE_SIZE, (10, 20, 30))
    assert frames.normalize(img).size == frames.REFERENCE_SIZE
    assert frames.library_view(frames.normalize(img)).size == (1280, 720)


def test_aspect_ratio_check():
    assert frames.aspect_ratio_ok((1920, 1080))
    assert frames.aspect_ratio_ok((1366, 768))  # 1.7786, within 2%
    assert not frames.aspect_ratio_ok((2560, 1080))
    assert not frames.aspect_ratio_ok((1280, 1024))
    assert not frames.aspect_ratio_ok((0, 0))
