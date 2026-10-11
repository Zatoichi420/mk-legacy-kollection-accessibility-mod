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
