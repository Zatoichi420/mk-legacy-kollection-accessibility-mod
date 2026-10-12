import io
import os

import pytest

import app_paths
import main


def test_prune_keeps_only_the_newest(tmp_path):
    for i in range(7):
        for ext in (".png", ".json"):
            (tmp_path / f"2026101{i}_120000_screen{ext}").write_text("x")
    main.prune_library_misses(str(tmp_path), keep=3)
    remaining = sorted(os.listdir(tmp_path))
    assert len(remaining) == 6
    assert remaining[0].startswith("20261014")


def test_prune_ignores_missing_folder(tmp_path):
    main.prune_library_misses(str(tmp_path / "nope"))


def test_args_defaults():
    args = main.parse_args([])
    assert not (args.stop or args.self_test or args.background or args.dev or args.ignore_focus)
    assert args.speech == "auto"


def test_stop_and_self_test_are_exclusive(capsys):
    with pytest.raises(SystemExit):
        main.parse_args(["--stop", "--self-test"])


def test_log_lines_are_timestamped():
    out = io.StringIO()
    tee = main._TimestampedTee(out)
    tee.write("first\nsec")
    tee.write("ond\n")
    lines = out.getvalue().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith(" first") and lines[1].endswith(" second")
    assert lines[0][:4].isdigit()


def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv(app_paths.DATA_DIR_ENV_VAR, str(tmp_path))
    assert app_paths.data_dir() == str(tmp_path)
    assert app_paths.log_file_path() == str(tmp_path / "reader.log")


def test_source_checkout_uses_one_library_folder():
    assert not app_paths.FROZEN
    assert app_paths.library_dirs() == [app_paths.bundled_known_screens_dir()]


def test_nvda_dll_is_where_the_build_expects_it():
    assert os.path.isfile(app_paths.nvda_dll_path())


def test_main_menu_highlight_is_found_below_the_library_view():
    """Live test 2026-10-11: OPTIONS and QUIT sit below y=720, outside the
    cropped library view, and highlighting them was never announced."""
    import json
    import os
    import types

    from PIL import Image, ImageDraw

    import main

    path = os.path.join(os.path.dirname(main.__file__), "known_screens", "launcher__main_menu.json")
    with open(path, encoding="utf-8") as f:
        entry = json.load(f)
    assert entry["canonical_text"][-2:] == ["OPTIONS", "QUIT"]

    from game_a11y_core.highlight import HighlightCalibration

    calibration = HighlightCalibration(main.HIGHLIGHT_BRIGHTNESS_THRESHOLD, main.HIGHLIGHT_BLUE_MINUS_RED_THRESHOLD)
    reader = types.SimpleNamespace(calibration=calibration)
    for item in ("OPTIONS", "QUIT"):
        full = Image.new("RGB", (1920, 1080))
        bbox = next(l["bbox"] for l in entry["ocr_lines_raw"] if l["text"] == item)
        ImageDraw.Draw(full).rectangle(bbox, fill=(105, 200, 230))  # the game's cyan "selected" text
        assert main.Reader.entry_highlight(reader, full, entry) == item


def test_clean_ocr_line_drops_highlight_ornaments_only():
    from main import clean_ocr_line

    assert clean_ocr_line("—4 ONLINE ARCADE") == "ONLINE ARCADE"
    assert clean_ocr_line("ONLINE ARCADE —4") == "ONLINE ARCADE"
    assert clean_ocr_line("1:36") == "1:36"
    assert clean_ocr_line("16") == "16"
    assert clean_ocr_line("HRS MINS") == "HRS MINS"
    assert clean_ocr_line("MORTAL KOMBAT 3") == "MORTAL KOMBAT 3"


def test_title_matches_tolerates_ocr_noise_but_not_other_titles():
    from main import title_matches

    assert title_matches("LEGACY KOLLECTION", ["LEGACY KOLL E CT ION"])
    assert title_matches("PLAY", ["PLAY"])
    assert title_matches("GAME LIBRARY", ["GAME LIBRARV"])
    assert not title_matches("PLAY", ["OPTIONS"])
    assert not title_matches("GAME LIBRARY", [])
