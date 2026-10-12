"""The Game Library's platform icons, from live captures (2026-10-11).
Each fixture is the title band of one carousel item, named <n>_<platform>."""

import glob
import os

import pytest
from PIL import Image

import platform_icons

FIXTURES = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "fixtures", "carousel", "*.png")))


@pytest.mark.parametrize("path", FIXTURES, ids=[os.path.basename(p) for p in FIXTURES])
def test_icon_is_named(path):
    expected = os.path.basename(path)[3:-4]
    band = Image.open(path).convert("RGB")
    full = Image.new("RGB", (1920, 1080))
    full.paste(band, platform_icons.BAND[:2])
    assert platform_icons.classify(full) == expected


def test_no_icon_means_no_guess():
    assert platform_icons.classify(Image.new("RGB", (1920, 1080))) is None
