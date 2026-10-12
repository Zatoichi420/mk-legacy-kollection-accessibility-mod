"""Reader.track_screen end to end, with speech captured and OCR faked.

Added 2026-10-11 after a live test found every library-matched screen
crashing (a function-local import shadowed the module) - nothing exercised
track_screen itself until then."""

import os
import types

import pytest
from PIL import Image

import frames
import main
import menu_ocr


class Recorder:
    def __init__(self):
        self.said = []

    def speak(self, text, interrupt=True):
        self.said.append(text)
        return True

    def wait_until_done(self, timeout_seconds=10):
        pass


@pytest.fixture
def reader(tmp_path, monkeypatch):
    monkeypatch.setenv("MK_LEGACY_ACCESS_DATA_DIR", str(tmp_path))
    args = types.SimpleNamespace(ignore_focus=True, dev=False)
    r = main.Reader(args, Recorder(), main.load_library(), None)
    return r


def _full_from_library(screen_id):
    path = os.path.join(os.path.dirname(main.__file__), "known_screens", screen_id + ".png")
    view = Image.open(path).convert("RGB")
    full = Image.new("RGB", frames.REFERENCE_SIZE)
    full.paste(view, (0, 0))
    return full


def test_library_screen_is_spoken_once_after_settling(reader, monkeypatch):
    monkeypatch.setattr(main.Reader, "verified_match", lambda self, full, view: self.library.match(view))
    full = _full_from_library("launcher__play_menu")
    view = frames.library_view(full)
    for _ in range(4):
        reader.track_screen(full, view, reader.verified_match(full, view))
    assert len(reader.speaker.said) == 1
    assert reader.speaker.said[0].startswith("PLAY. OFFLINE. QUICK MATCH")


def _lines(*texts, highlighted=None):
    out = []
    for i, t in enumerate(texts):
        out.append({"text": t, "bbox": (100, 200 + 60 * i, 400, 230 + 60 * i), "x": 100, "y": 200 + 60 * i, "parts": []})
    return out


def test_unknown_menu_moving_highlight_says_only_the_item(reader, monkeypatch):
    items = ["PAUSE", "RESUME", "MOVES LIST", "CONTROLS", "QUIT GAME"]
    state = {"hl": "RESUME"}
    monkeypatch.setattr(menu_ocr, "read_menu_text", lambda img, clean=None, vocabulary=None: _lines(*items))
    monkeypatch.setattr(menu_ocr, "find_highlight", lambda img, lines, cal, vocabulary=None: state["hl"])
    full = Image.new("RGB", frames.REFERENCE_SIZE)
    view = frames.library_view(full)
    for _ in range(3):
        reader.track_screen(full, view, None)
    assert reader.speaker.said == ["PAUSE. RESUME. MOVES LIST. CONTROLS. QUIT GAME. Selected: RESUME"]
    state["hl"] = "CONTROLS"
    for _ in range(3):
        reader.track_screen(full, view, None)
    assert reader.speaker.said[-1] == "CONTROLS"
    assert len(reader.speaker.said) == 2


def test_screen_that_never_settles_goes_quiet(reader, monkeypatch):
    counter = {"n": 0}

    def noisy(img, clean=None, vocabulary=None):
        counter["n"] += 1
        return _lines(f"00 WINS {counter['n']}", "FIGHT")

    monkeypatch.setattr(menu_ocr, "read_menu_text", noisy)
    monkeypatch.setattr(menu_ocr, "find_highlight", lambda *a, **k: None)
    monkeypatch.setattr(main.Reader, "unknown_screen_lines", lambda self, full: (noisy(full), False))
    full = Image.new("RGB", frames.REFERENCE_SIZE)
    view = frames.library_view(full)
    for _ in range(80):
        reader.track_screen(full, view, None)
    assert len(reader.speaker.said) <= 1
