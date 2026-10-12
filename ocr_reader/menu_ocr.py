"""
Reading screens that aren't in the library, as well as live OCR can.

Added 2026-10-11 after the first live tests on the real game. Plain
Windows OCR of this game's menu font was reading "MOVES LIST" as "Mnws
LIST", dropping "QUIT" from "QUIT GAME" entirely, and splitting a setting
from its value ("ON-SCREEN MOVE LIST" ... "OFF"). Three things fix most of
that:

  1. Two OCR passes. The frame as-is, and a black-on-white version
     (bright text -> black, everything else -> white). The second reads
     the stylised menu font far better ("QUIT GAME", "MOVES LIST") but
     loses the cyan highlighted item, which the first pass keeps. Lines
     from the two passes are paired by position and the better reading
     of each pair is kept.
  2. Vocabulary snapping. Every line is compared with the words this game
     actually uses (every library entry's canonical text plus
     vocabulary.txt) and replaced by the closest one when it's close
     enough. Unknown text is left as read.
  3. Row merging. Pieces of text on the same row are joined
     ("ON-SCREEN MOVE LIST, OFF"), so a setting is read with its value and
     the highlight check sees the whole row.

same_screen() then decides whether two OCR readings are the same screen
(so a moved highlight is announced as just the new item, not a whole new
screen), and looks_like_text() rejects readings that are mostly noise.
"""

import asyncio
import difflib
import os

import numpy as np
from PIL import Image, ImageOps

BINARIZE_THRESHOLD = 110
SNAP_MIN_RATIO = 0.8
SAME_SCREEN_MIN_OVERLAP = 0.7
FOOTER_TOP = 990  # reference-frame y where the key-hint bar starts

_vocabulary = None


def _letters(text):
    return "".join(c for c in text.upper() if c.isalnum())


def load_vocabulary(library=None, extra_path=None):
    """Known phrases, longest first. Cached after the first call."""
    global _vocabulary
    words = set()
    if extra_path is None:
        import app_paths

        extra_path = os.path.join(app_paths.RESOURCE_DIR, "vocabulary.txt")
    try:
        with open(extra_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    words.add(line)
    except OSError:
        pass
    if library is not None:
        for entry in library.entries:
            for text in entry.get("canonical_text") or ():
                words.add(text)
            for line in entry.get("ocr_lines_raw") or ():
                if line.get("text"):
                    words.add(line["text"])
    _vocabulary = sorted(words, key=len, reverse=True)
    return _vocabulary


def snap(text, vocabulary=None):
    """The vocabulary phrase `text` most likely is, or `text` unchanged."""
    vocabulary = _vocabulary if vocabulary is None else vocabulary
    if not vocabulary:
        return text
    key = _letters(text)
    if len(key) < 3:
        return text
    best, best_ratio = None, 0.0
    for phrase in vocabulary:
        pkey = _letters(phrase)
        if not pkey or abs(len(pkey) - len(key)) > max(3, len(pkey) // 2):
            continue
        ratio = difflib.SequenceMatcher(None, key, pkey).ratio()
        if ratio > best_ratio or (ratio == best_ratio and best is not None and len(phrase) < len(best)):
            best, best_ratio = phrase, ratio
    if best is not None and best_ratio >= SNAP_MIN_RATIO:
        return best
    return expand_fragment(text, vocabulary)


def expand_fragment(text, vocabulary=None):
    """A fragment that is part of exactly one known phrase becomes that
    phrase ("VOLUME" -> "AUDIO VOLUME": the stylised "AUDIO" never OCRs).
    Only for fragments of 5+ letters made of whole words, and only when
    the phrase is unique - "DISPLAY" (DISPLAY MODE or MOVE LIST DISPLAY)
    is left alone."""
    vocabulary = _vocabulary if vocabulary is None else vocabulary
    words = [w for w in text.upper().split() if w]
    if not words or sum(len(w) for w in words) < 5 or not all(w.isalpha() for w in words):
        return text
    hits = []
    for phrase in vocabulary or ():
        pw = phrase.upper().replace(",", " ").split()
        if len(pw) <= len(words):
            continue
        for i in range(len(pw) - len(words) + 1):
            if pw[i:i + len(words)] == words:
                hits.append(phrase)
                break
    return hits[0] if len(set(hits)) == 1 else text


def binarize(img, threshold=BINARIZE_THRESHOLD):
    gray = np.asarray(img.convert("L"))
    out = np.where(gray > threshold, 0, 255).astype("uint8")
    return Image.fromarray(out).convert("RGB")


def _quality(text, vocabulary):
    """Higher is a better reading of a line."""
    if not text:
        return -1.0
    snapped = snap(text, vocabulary)
    letters = sum(c.isalpha() for c in text)
    odd = sum(not (c.isalnum() or c in " -',.:!?&/") for c in text)
    lower_in_upper = sum(c.islower() for c in text) if sum(c.isupper() for c in text) > 2 else 0
    score = letters - 3 * odd - 2 * lower_in_upper
    if snapped != text:
        score += 50
    return score


def _overlap(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix = max(0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    if not inter:
        return 0.0
    smaller = min((ax2 - ax1) * (ay2 - ay1), (bx2 - bx1) * (by2 - by1)) or 1
    return inter / smaller


def merge_passes(first, second, vocabulary=None):
    """Pair lines from two OCR passes by position; keep the better reading."""
    vocabulary = _vocabulary if vocabulary is None else vocabulary
    used = set()
    merged = []
    for line in first:
        partner = None
        for i, other in enumerate(second):
            if i not in used and _overlap(line["bbox"], other["bbox"]) > 0.5:
                partner = i
                break
        if partner is None:
            merged.append(line)
            continue
        used.add(partner)
        other = second[partner]
        better = other if _quality(other["text"], vocabulary) > _quality(line["text"], vocabulary) else line
        merged.append(dict(better, bbox=tuple(
            f(a, b) for f, a, b in zip((min, min, max, max), line["bbox"], other["bbox"]))))
    for i, other in enumerate(second):
        # A second-pass piece lying inside an already-kept line is that
        # line split differently ("GAME" + "OPTIONS"), not new text.
        if i not in used and not any(_overlap(other["bbox"], kept["bbox"]) > 0.5 for kept in merged):
            merged.append(other)
    return merged


ROW_JOIN_GAP = 60          # px: pieces this close are one phrase split by OCR
VALUE_JOIN_GAP = 650       # px: a short value this far right is the row's setting value
COLUMN_GAP = 220           # px between x-start clusters that makes a new column


def _value_like(text):
    words = text.split()
    return len(text) <= 8 and len(words) <= 2 or any(c.isdigit() for c in text)


def _icon_junk(text):
    """Button icons OCR as a single stray letter ('z', 'x')."""
    letters = [c for c in text if c.isalnum()]
    return len(letters) <= 1 and not any(c.isdigit() for c in letters)


def merge_rows(lines):
    """Join pieces of text on the same row: a phrase OCR split in two, or a
    setting and its value ("ON-SCREEN MOVE LIST" ... "OFF"). Text in a
    separate column on the same row (the Moves List panel beside the pause
    menu) is not joined."""
    rows = []
    for line in sorted(lines, key=lambda l: (l["bbox"][0], l["bbox"][1])):
        if _icon_junk(line["text"]):
            continue
        x1, y1, x2, y2 = line["bbox"]
        mid = (y1 + y2) / 2
        for row in rows:
            rx1, ry1, rx2, ry2 = row["bbox"]
            gap = x1 - rx2
            if not (ry1 <= mid <= ry2) or gap < -20:
                continue
            if gap <= ROW_JOIN_GAP or (gap <= VALUE_JOIN_GAP and _value_like(line["text"])):
                row["parts"].append(line)
                row["bbox"] = (min(rx1, x1), min(ry1, y1), max(rx2, x2), max(ry2, y2))
                break
        else:
            rows.append({"bbox": (x1, y1, x2, y2), "parts": [line]})
    out = []
    for row in rows:
        parts = sorted(row["parts"], key=lambda l: l["bbox"][0])
        joined = []
        for i, p in enumerate(parts):
            gap = p["bbox"][0] - parts[i - 1]["bbox"][2] if i else 0
            joined.append((" " if gap <= ROW_JOIN_GAP else ", ") + p["text"] if i else p["text"])
        out.append({"text": "".join(joined), "bbox": row["bbox"], "x": row["bbox"][0], "y": row["bbox"][1],
                    "parts": [{"text": p["text"], "bbox": p["bbox"]} for p in parts] if len(parts) > 1 else []})
    return order_for_reading(out)


def order_for_reading(lines):
    """Top to bottom - or, for a true multi-column layout (two or more
    columns of at least four lines each, like the Moves List beside the
    pause menu), column by column, left to right."""
    lines = sorted(lines, key=lambda l: (l["y"], l["x"]))
    body = [l for l in lines if l["y"] < FOOTER_TOP]
    footer = [l for l in lines if l["y"] >= FOOTER_TOP]
    starts = sorted({round(l["x"]) for l in body})
    columns = []
    for x in starts:
        if columns and x - columns[-1][-1] <= COLUMN_GAP:
            columns[-1].append(x)
        else:
            columns.append([x])
    if len(columns) < 2:
        return lines
    groups = [[l for l in body if col[0] <= round(l["x"]) <= col[-1]] for col in columns]
    if sum(len(g) >= 4 for g in groups) < 2:
        return lines
    ordered = []
    for g in groups:
        ordered.extend(sorted(g, key=lambda l: l["y"]))
    return ordered + footer


def _clean_footer(line):
    """Key-hint bar at the bottom: the key icons OCR as junk like '14' or
    'Esc'. Keep only real words, and the bar's own grouping."""
    if line["bbox"][1] < FOOTER_TOP:
        return line
    groups = []
    for segment in line["text"].split(","):
        words = [w for w in segment.split() if sum(c.isalpha() for c in w) >= 2]
        if words:
            groups.append(" ".join(words))
    return dict(line, text=", ".join(groups)) if groups else None


def read_menu_text(img, clean=None, vocabulary=None):
    """OCR `img` (a full reference-size frame) the best way we know.
    `clean` is applied to each raw line first (main.clean_ocr_line)."""
    from game_a11y_core.ocr import ocr_image

    vocabulary = _vocabulary if vocabulary is None else vocabulary

    def prep(lines):
        out = []
        for line in lines:
            text = clean(line["text"]) if clean else line["text"]
            if text:
                out.append(dict(line, text=text))
        return out

    first = prep(asyncio.run(ocr_image(img)))
    second = prep(asyncio.run(ocr_image(binarize(img))))
    lines = merge_passes(first, second, vocabulary)
    for line in lines:
        line["text"] = snap(line["text"], vocabulary)
    lines = repair_lines(img, lines, vocabulary)
    vocab = set(vocabulary or ())
    lines = [l for l in lines if l["text"] in vocab or plausible_line(l["text"])]
    lines = merge_rows(lines)
    lines = [l for l in (_clean_footer(l) for l in lines) if l and l["text"]]
    return lines


def plausible_line(text):
    """False for OCR noise like "r ATA' ITV 1 nec" (text fading in or out,
    background art): most words must look like real words or numbers."""
    words = text.replace(",", " ").split()
    if not words:
        return False

    def ok(w):
        core = w.strip(".,:;!?'\"()-")
        if not core:
            return False
        if core.isdigit() or (core[:-1].isdigit() and core[-1] in "%x"):
            return True
        if not all(c.isalpha() or c in "-'" for c in core) or len(core) < 2:
            return False
        if len(core) >= 3 and not any(c in "AEIOUYaeiouy" for c in core):
            return False
        return core.isupper() or core.islower() or core.istitle() or core[0].isupper()

    good = sum(ok(w) for w in words)
    numeric = all(w.strip(".,%x").replace(":", "").isdigit() for w in words)
    return numeric or (good * 10 >= 7 * len(words) and sum(c.isalpha() for c in text) >= 2)


def same_screen(lines_a, lines_b):
    """True if two readings (tuples/lists of line texts) are most likely the
    same screen - e.g. the same menu with the highlight moved, which can
    change how one or two lines OCR."""
    a, b = set(lines_a), set(lines_b)
    if not a or not b:
        return False
    return len(a & b) / max(len(a), len(b)) >= SAME_SCREEN_MIN_OVERLAP


def looks_like_text(lines, vocabulary=None):
    """False for readings that are mostly OCR noise (fight HUDs, attract
    animations): fewer than half the lines snap to the vocabulary or read
    as plain words."""
    vocabulary = _vocabulary if vocabulary is None else vocabulary
    if not lines:
        return False
    vocab = set(vocabulary or ())
    good = 0
    for text in lines:
        words = text.replace(",", " ").split()
        plain = words and all(w.isalpha() and (w.isupper() or w.istitle() or w.islower()) and len(w) >= 2 for w in words)
        if text in vocab or plain:
            good += 1
    return good * 2 >= len(lines)


# --- Highlight -----------------------------------------------------------------

def _highlight_mask(img, calibration):
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    bright = a.sum(axis=2) > calibration.brightness_threshold
    blue = (a[:, :, 2] - a[:, :, 0]) > calibration.blue_minus_red_threshold
    return bright & blue


def highlight_boxes(img, calibration, min_pixels=40):
    """Boxes around clusters of the game's highlight colour (bright cyan
    text), largest first. Rows of mask pixels are grouped into bands, and
    each band's columns into clusters."""
    mask = _highlight_mask(img, calibration)
    rows = np.where(mask.sum(axis=1) >= 3)[0]
    boxes = []
    if not len(rows):
        return boxes
    bands, start, prev = [], rows[0], rows[0]
    for r in rows[1:]:
        if r - prev > 6:
            bands.append((start, prev))
            start = r
        prev = r
    bands.append((start, prev))
    for y1, y2 in bands:
        cols = np.where(mask[y1:y2 + 1].sum(axis=0) > 0)[0]
        if not len(cols):
            continue
        c_start, c_prev = cols[0], cols[0]
        for c in list(cols[1:]) + [None]:
            if c is None or c - c_prev > 40:
                box = (int(c_start), int(y1), int(c_prev) + 1, int(y2) + 1)
                if mask[box[1]:box[3], box[0]:box[2]].sum() >= min_pixels:
                    boxes.append(box)
                if c is not None:
                    c_start = c
            if c is not None:
                c_prev = c
    boxes.sort(key=lambda b: -int(mask[b[1]:b[3], b[0]:b[2]].sum()))
    return boxes


def _line_highlighted(arr, bbox, calibration):
    from game_a11y_core.highlight import is_line_highlighted

    return is_line_highlighted(arr, bbox, calibration)


def find_highlight(img, lines, calibration, vocabulary=None):
    """Text of the highlighted item: a whole row if the row reads as
    highlighted, else one piece of a merged row ("NO" of "NO, YES"), else
    whatever OCR can make of the highlight-coloured area itself."""
    arr = np.asarray(img.convert("RGB"))
    for line in lines:
        if _line_highlighted(arr, line["bbox"], calibration):
            pieces = [p for p in line.get("parts") or () if _line_highlighted(arr, p["bbox"], calibration)]
            if len(pieces) == 1 and len(line.get("parts") or ()) > 1 and not _value_row(line):
                return pieces[0]["text"]
            return with_glowing_value(img, line, calibration, vocabulary)
        for piece in line.get("parts") or ():
            if _line_highlighted(arr, piece["bbox"], calibration):
                return piece["text"]
    return rescue_highlight(img, calibration, lines, vocabulary)


def _value_row(line):
    """A setting row ("ON-SCREEN MOVE LIST, OFF"): report it whole."""
    parts = line.get("parts") or ()
    return len(parts) == 2 and _value_like(parts[1]["text"]) and not _value_like(parts[0]["text"])


def rescue_highlight(img, calibration, lines=(), vocabulary=None):
    """OCR the largest highlight-coloured area directly. Glowing highlighted
    text often doesn't OCR as part of the whole screen; on its own, enlarged
    and turned black-on-white, it usually does."""
    from game_a11y_core.ocr import ocr_image

    vocabulary = _vocabulary if vocabulary is None else vocabulary
    full_mask = _highlight_mask(img, calibration)
    for box in highlight_boxes(img, calibration)[:2]:
        x1, y1, x2, y2 = box
        w, h = x2 - x1, y2 - y1
        # Text-shaped only: a band of sky or water isn't a menu item.
        if not (12 <= h <= 120 and 20 <= w <= 900 and w >= h):
            continue
        density = full_mask[y1:y2, x1:x2].mean()
        if not 0.05 <= density <= 0.9:
            continue
        key = (box, hash(img.crop(box).tobytes()))
        if key in _rescue_cache:
            return _rescue_cache[key]
        # A line that already covers this area names it.
        for line in lines:
            if _overlap(line["bbox"], box) > 0.5:
                return line["text"]
        pad = 12
        crop = img.crop((max(0, x1 - pad), max(0, y1 - pad), x2 + pad, y2 + pad))
        big = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
        mask = Image.fromarray((_highlight_mask(big, calibration) == 0).astype("uint8") * 255).convert("RGB")
        for candidate in (mask, binarize(big, 140), big):
            found = asyncio.run(ocr_image(ImageOps.expand(candidate, 30, fill=candidate.getpixel((0, 0)))))
            text = " ".join(l["text"] for l in found).strip()
            if not text:
                continue
            snapped = snap_short(text, vocabulary)
            if snapped != text or plausible_line(text):
                if len(_rescue_cache) > 64:
                    _rescue_cache.clear()
                _rescue_cache[key] = snapped
                return snapped
        if len(_rescue_cache) > 64:
            _rescue_cache.clear()
        _rescue_cache[key] = None
    return None


_rescue_cache = {}


def snap_short(text, vocabulary=None):
    """snap(), plus exact matches for 1-2 letter vocabulary words (NO, ON)."""
    vocabulary = _vocabulary if vocabulary is None else vocabulary
    key = _letters(text)
    if len(key) < 3:
        for phrase in vocabulary or ():
            if _letters(phrase) == key:
                return phrase
        return text
    return snap(text, vocabulary)


# --- Speech text -----------------------------------------------------------------

KEY_HINT_WORDS = {"SELECT", "BACK", "RESUME", "FILTER", "CONFIRM", "CANCEL", "CHANGE TAB"}


def drop_key_icons(text):
    """Key-hint rows ("[Enter] SELECT [Esc] BACK") OCR the key icons as
    small numbers ("14 SELECT BACK"); drop those numbers."""
    words = text.replace(",", " ").split()
    if not any(w.upper() in KEY_HINT_WORDS for w in words):
        return text
    kept = [w for w in words if not (w.isdigit() and len(w) <= 2)]
    return ", ".join(kept) if kept != words else text


def join_for_speech(lines):
    """Lines (dicts with text and bbox, in reading order) to one string.
    Separate items get a full stop between them; the lines of one wrapped
    paragraph (same column, tight spacing, no sentence end, next line
    continuing it) are joined with a space so speech doesn't pause
    mid-sentence."""
    out = ""
    prev = None
    for line in lines:
        text = drop_key_icons(line["text"]).strip()
        if not text:
            continue
        if prev is None:
            out = text
        else:
            px1, py1, px2, py2 = prev["bbox"]
            x1, y1, x2, y2 = line["bbox"]
            height = max(py2 - py1, 1)
            overlap = min(px2, x2) - max(px1, x1)
            continues = (
                overlap >= 0.5 * min(px2 - px1, x2 - x1)
                and 0 <= y1 - py2 <= height * 0.9
                and out[-1] not in ".?!:"
                and abs((y2 - y1) - height) <= 0.3 * height
            )
            if continues:
                out += " " + text
            elif out[-1] in ".?!:":
                out += " " + text
            else:
                out += ". " + text
        prev = line
    return out


def join_texts(texts):
    """Plain list of phrases (library canonical text) to one string,
    without doubling punctuation ("QUIT GAME?. YOU'LL...")."""
    out = ""
    for text in texts:
        text = text.strip()
        if not text:
            continue
        if not out:
            out = text
        elif out[-1] in ".?!:":
            out += " " + text
        else:
            out += ". " + text
    return out


MAX_REPAIRS_PER_FRAME = 8


def repair_lines(img, lines, vocabulary=None):
    """Re-read lines that don't match any known phrase, one row at a time,
    enlarged and black-on-white. A re-read that does match a known phrase
    (and covers what was read) replaces the line. Cached per row image."""
    from game_a11y_core.ocr import ocr_image

    vocabulary = _vocabulary if vocabulary is None else vocabulary
    vocab = set(vocabulary or ())
    out = []
    repairs = 0
    for line in lines:
        text = line["text"]
        if text in vocab or repairs >= MAX_REPAIRS_PER_FRAME or sum(c.isalpha() for c in text) < 3:
            out.append(line)
            continue
        x1, y1, x2, y2 = line["bbox"]
        right = x2 + 260
        for other in lines:
            ox1, oy1, ox2, oy2 = other["bbox"]
            if other is not line and ox1 > x2 and oy1 < y2 and oy2 > y1:
                right = min(right, ox1 - 4)
        box = (int(max(0, x1 - 10)), int(max(0, y1 - 8)), int(max(right, x2 + 4)), int(y2 + 8))
        crop = img.crop(box)
        key = (box, hash(crop.tobytes()))
        if key in _repair_cache:
            fixed = _repair_cache[key]
        else:
            repairs += 1
            fixed = None
            big = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
            for candidate in (binarize(big, 90), binarize(big, 110), big):
                found = asyncio.run(ocr_image(ImageOps.expand(candidate, 30, fill=candidate.getpixel((0, 0)))))
                for piece in found:
                    snapped = snap(piece["text"], vocabulary)
                    if snapped in vocab and _letters(text)[:3] in _letters(snapped):
                        if fixed is None or len(snapped) > len(fixed):
                            fixed = snapped
                if fixed:
                    break
            if len(_repair_cache) > 256:
                _repair_cache.clear()
            _repair_cache[key] = fixed
        out.append(dict(line, text=fixed) if fixed else line)
    return out


_repair_cache = {}


def with_glowing_value(img, line, calibration, vocabulary=None):
    """A highlighted setting row's value glows too and often doesn't OCR,
    so "MENU MUSIC" came out without its "ON", and changing it said
    nothing. Read any highlight-coloured text right of the row's label and
    add it, unless the row already has a value."""
    from game_a11y_core.ocr import ocr_image

    parts = line.get("parts") or []
    if len(parts) > 1 and not _value_row(line):
        return line["text"]
    # Always re-read the value of the highlighted row fresh - a remembered
    # reading of the row would still say the old value after a change.
    label = parts[0] if len(parts) > 1 else line
    x1, y1, x2, y2 = label["bbox"]
    band = (int(x2 + 40), int(max(0, y1 - 10)), int(min(img.width, x2 + VALUE_JOIN_GAP + 120)), int(y2 + 10))
    if band[2] - band[0] < 20:
        return line["text"]
    crop = img.crop(band)
    mask = _highlight_mask(crop, calibration)
    cols = np.where(mask.sum(axis=0) > 0)[0]
    if len(cols) < 6:
        return line["text"]
    vx1, vx2 = max(0, cols.min() - 8), min(crop.width, cols.max() + 9)
    value_crop = crop.crop((vx1, 0, vx2, crop.height))
    key = hash(value_crop.tobytes())
    if key in _value_cache:
        value = _value_cache[key]
    else:
        value = None
        big = value_crop.resize((value_crop.width * 3, value_crop.height * 3), Image.LANCZOS)
        glow = Image.fromarray((_highlight_mask(big, calibration) == 0).astype("uint8") * 255).convert("RGB")
        for candidate in (binarize(big, 140), glow, big):
            found = asyncio.run(ocr_image(ImageOps.expand(candidate, 30, fill=candidate.getpixel((0, 0)))))
            text = " ".join(l["text"] for l in found).strip(" <>()[]|")
            text = "".join(c for c in text if c.isalnum() or c in " -%:'.").strip()
            if text and (plausible_line(text) or text.isdigit()):
                value = snap_short(text, vocabulary)
                break
        if len(_value_cache) > 256:
            _value_cache.clear()
        _value_cache[key] = value
    return f"{label['text']}, {value}" if value else line["text"]


_value_cache = {}
