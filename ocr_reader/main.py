"""
MK Legacy Kollection accessibility reader.

Continuously captures the game window and speaks its contents via NVDA.
On each poll, first tries to recognize the current screen against the
hand-verified reference library (known_screens/, matched by perceptual
image hash - see screen_library.py, "the hook"): a match speaks that
screen's pre-verified canonical_text instead of live OCR, which is both
faster and immune to this game's various OCR failure modes (stylized/
compressed fonts that Windows OCR mangles or misses entirely - see
PROGRESS.md section 5 for why this replaced the original OCR-only design).

If no library entry matches, falls back to live OCR (today's original
behavior) as a best-effort read, and logs the miss to library_misses/ so
it can be reviewed and folded into the library later.

Within either mode, the currently-highlighted item (if the screen is a
list/tab style menu) is tracked separately via color: this game renders
the selected item in a distinct cyan/blue with a glow, vs. gold/yellow for
unselected items - see PROGRESS.md for the calibration.

F9 forces an immediate re-read of whatever's on screen right now (fallback
for screens/dialogs that don't fit the above). F10 captures the current
screen (screenshot + live OCR) into known_screens/ as a *candidate* new
library entry - it still needs a canonical_text field hand-verified from
the image before screen_library.py will treat it as trustworthy.
"""

import asyncio
import ctypes
import io
import json
import os
import re
import time

import numpy as np
import win32api
import win32gui
import win32process
import win32ui
from PIL import Image
from winsdk.windows.graphics.imaging import BitmapDecoder
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

from screen_library import ScreenLibrary

PW_RENDERFULLCONTENT = 0x00000002
PROCESS_NAME = "mk_legacy_kollection.exe"
POLL_INTERVAL_SECONDS = 0.5
REREAD_HOTKEY_VK = 0x78  # VK_F9
CAPTURE_HOTKEY_VK = 0x79  # VK_F10
# When auto-started alongside the game (see run_reader.bat/start_reader.vbs),
# there's no terminal to Ctrl+C from, so exit on our own once the game window
# has been gone this long (covers "player closed the game").
EXIT_AFTER_WINDOW_GONE_SECONDS = 120
STABLE_POLLS_REQUIRED = 2  # OCR/highlight can be slightly noisy frame-to-frame; require it to settle before speaking

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NVDA_DLL_PATH = os.path.join(SCRIPT_DIR, "nvda_controller_client", "x64", "nvdaControllerClient.dll")
KNOWN_SCREENS_DIR = os.path.join(SCRIPT_DIR, "known_screens")
LIBRARY_MISSES_DIR = os.path.join(SCRIPT_DIR, "library_misses")


def find_window_for_process(process_name):
    target_hwnd = None

    def callback(hwnd, _):
        nonlocal target_hwnd
        if not win32gui.IsWindowVisible(hwnd):
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            handle = win32api.OpenProcess(0x0400 | 0x0010, False, pid)
            exe_name = win32process.GetModuleFileNameEx(handle, 0)
        except Exception:
            return True
        if exe_name.lower().endswith(process_name.lower()) and target_hwnd is None:
            rect = win32gui.GetWindowRect(hwnd)
            if rect[2] - rect[0] > 0 and rect[3] - rect[1] > 0:
                target_hwnd = hwnd
        return True  # always continue - returning False here triggers a spurious pywin32 exception

    try:
        win32gui.EnumWindows(callback, None)
    except Exception:
        pass  # some pywin32 versions raise a bogus error even on clean completion
    return target_hwnd


def capture_window(hwnd):
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()

    save_bitmap = win32ui.CreateBitmap()
    save_bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(save_bitmap)

    ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)

    bmpinfo = save_bitmap.GetInfo()
    bmpstr = save_bitmap.GetBitmapBits(True)
    img = Image.frombuffer(
        "RGB",
        (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
        bmpstr, "raw", "BGRX", 0, 1,
    )

    win32gui.DeleteObject(save_bitmap.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    return img


async def ocr_image(img: Image.Image):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(buf.getvalue())
    await writer.store_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        return []

    result = await engine.recognize_async(bitmap)
    lines = []
    for line in result.lines:
        text = line.text.strip()
        if not text or not line.words:
            continue
        xs = [w.bounding_rect.x for w in line.words]
        ys = [w.bounding_rect.y for w in line.words]
        rights = [w.bounding_rect.x + w.bounding_rect.width for w in line.words]
        bottoms = [w.bounding_rect.y + w.bounding_rect.height for w in line.words]
        bbox = (min(xs), min(ys), max(rights), max(bottoms))
        lines.append({"text": text, "bbox": bbox, "y": min(ys), "x": min(xs)})
    lines.sort(key=lambda l: (l["y"], l["x"]))
    return lines


# Calibrated against this game's menu highlight style: selected items are
# rendered cyan/blue (~RGB 105,200,230), unselected gold/yellow
# (~RGB 240,212,126). Blue-channel-exceeds-red-channel cleanly separates
# the two - see PROGRESS.md for the sampled values.
BRIGHTNESS_THRESHOLD = 300  # sum of R+G+B, to isolate text pixels from dark background
BLUE_MINUS_RED_THRESHOLD = 30  # margin required to call it "selected", avoids borderline noise


def is_line_highlighted(img_array, bbox):
    x1, y1, x2, y2 = (int(round(v)) for v in bbox)
    pad = 4
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(img_array.shape[1], x2 + pad)
    y2 = min(img_array.shape[0], y2 + pad)
    crop = img_array[y1:y2, x1:x2].reshape(-1, 3)
    if crop.size == 0:
        return None
    brightness = crop.sum(axis=1)
    bright_pixels = crop[brightness > BRIGHTNESS_THRESHOLD]
    if len(bright_pixels) < 10:
        return None
    mean_r = bright_pixels[:, 0].mean()
    mean_b = bright_pixels[:, 2].mean()
    return (mean_b - mean_r) > BLUE_MINUS_RED_THRESHOLD


def find_highlighted_text(img: Image.Image, lines):
    img_array = np.array(img.convert("RGB"))
    for line in lines:
        if is_line_highlighted(img_array, line["bbox"]):
            return line["text"]
    return None


def find_highlighted_text_from_entry(img: Image.Image, entry):
    """Same idea as find_highlighted_text, but sampling colors at the
    reference library's stored bbox positions instead of running live OCR -
    works because highlight detection is pure pixel-color sampling, not
    text recognition. Skips any stored line missing a bbox, or explicitly
    flagged "skip_highlight" (e.g. a decorative/logo line with an
    unconfirmed, estimated bbox not safe to sample)."""
    img_array = np.array(img.convert("RGB"))
    for line in entry.get("ocr_lines_raw", []):
        bbox = line.get("bbox")
        text = line.get("text")
        if not bbox or not text or line.get("skip_highlight"):
            continue
        if is_line_highlighted(img_array, bbox):
            return text
    return None


def slugify(text, max_words=6):
    words = re.findall(r"[a-z0-9]+", text.lower())[:max_words]
    return "_".join(words) if words else "blank_screen"


def save_known_screen(img, lines, highlighted_text):
    """Save a screenshot + its live OCR text into known_screens/ as a
    *candidate* library entry. It won't be used for recognition/speech by
    screen_library.py until a canonical_text field is added by hand after
    reviewing the saved image (this is deliberate - see PROGRESS.md
    section 5 on why raw OCR text is not trusted for speech anymore)."""
    os.makedirs(KNOWN_SCREENS_DIR, exist_ok=True)
    screen_texts = [l["text"] for l in lines]
    slug = slugify(" ".join(screen_texts))

    name = slug
    suffix = 2
    while os.path.exists(os.path.join(KNOWN_SCREENS_DIR, name + ".png")):
        name = f"{slug}_{suffix}"
        suffix += 1

    img.convert("RGB").save(os.path.join(KNOWN_SCREENS_DIR, name + ".png"))
    data = {
        "screen_id": name,
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "live_capture",
        "canonical_text": None,  # needs hand verification before this entry is used for recognition
        "highlighted": highlighted_text,
        "ocr_lines_raw": [{"text": l["text"], "bbox": l["bbox"]} for l in lines],
    }
    with open(os.path.join(KNOWN_SCREENS_DIR, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return name


def log_library_miss(img, screen_texts):
    """A screen was stably read via live OCR because it didn't match
    anything in the library. Save it so it can be reviewed and folded into
    known_screens/ (with hand-verified canonical_text) later."""
    os.makedirs(LIBRARY_MISSES_DIR, exist_ok=True)
    slug = slugify(" ".join(screen_texts)) if screen_texts else "blank_screen"
    name = f"{time.strftime('%Y%m%d_%H%M%S')}_{slug}"
    img.convert("RGB").save(os.path.join(LIBRARY_MISSES_DIR, name + ".png"))
    with open(os.path.join(LIBRARY_MISSES_DIR, name + ".json"), "w", encoding="utf-8") as f:
        json.dump({"ocr_text": screen_texts}, f, indent=2)


class NvdaSpeaker:
    def __init__(self):
        self.lib = ctypes.windll.LoadLibrary(NVDA_DLL_PATH)
        res = self.lib.nvdaController_testIfRunning()
        if res != 0:
            raise RuntimeError(f"NVDA does not appear to be running: {ctypes.WinError(res)}")

    def speak(self, text):
        self.lib.nvdaController_cancelSpeech()
        self.lib.nvdaController_speakText(text)


def was_key_pressed_since_last_check(vk):
    """Edge-triggered, not level-triggered: GetAsyncKeyState's low-order bit
    latches "this key was pressed at some point since the last call for this
    vk" and clears on read. A plain "is it down right now" check (the high
    bit alone) can miss a real keypress entirely if it happens to fall
    between two ~0.5s polls - a normal keyboard tap is often under 150ms,
    well inside that gap. The latch bit can't miss it: it stays set across
    any number of polls until someone reads it."""
    return (win32api.GetAsyncKeyState(vk) & 0x1) != 0


def main():
    print("MK Legacy Kollection accessibility reader starting...")
    speaker = NvdaSpeaker()
    print("NVDA connection OK.")

    library = ScreenLibrary()
    print(f"Loaded {len(library.entries)} verified screens into the recognition library.")

    speaker.speak("Accessibility reader ready.")

    hwnd = None
    hwnd_ever_found = False
    window_missing_since = None

    # screen_key identifies "what's currently on screen" for change detection:
    # ("lib", screen_id) when the library recognized it, ("ocr", tuple_of_lines)
    # when falling back to live OCR. screen_payload is the text to actually speak.
    last_spoken_screen_key = None
    pending_screen_key = None
    pending_screen_payload = None
    pending_screen_ocr_texts = None
    pending_screen_seen_count = 0

    last_spoken_highlight = None
    pending_highlight = None
    pending_highlight_seen_count = 0

    def reset_tracking():
        nonlocal last_spoken_screen_key, pending_screen_key, pending_screen_payload
        nonlocal pending_screen_ocr_texts, pending_screen_seen_count
        nonlocal last_spoken_highlight, pending_highlight, pending_highlight_seen_count
        last_spoken_screen_key = None
        pending_screen_key = None
        pending_screen_payload = None
        pending_screen_ocr_texts = None
        pending_screen_seen_count = 0
        last_spoken_highlight = None
        pending_highlight = None
        pending_highlight_seen_count = 0

    while True:
        if hwnd is None or not win32gui.IsWindow(hwnd):
            hwnd = find_window_for_process(PROCESS_NAME)
            if hwnd is None:
                if hwnd_ever_found:
                    if window_missing_since is None:
                        window_missing_since = time.monotonic()
                    elif time.monotonic() - window_missing_since > EXIT_AFTER_WINDOW_GONE_SECONDS:
                        print("Game window gone for a while; exiting.")
                        return
                print("Waiting for game window...")
                time.sleep(2)
                continue
            hwnd_ever_found = True
            window_missing_since = None
            print(f"Found game window: hwnd={hwnd}")
            speaker.speak("Game window found.")
            reset_tracking()

        img = capture_window(hwnd)
        if img is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        force_reread = was_key_pressed_since_last_check(REREAD_HOTKEY_VK)
        force_capture = was_key_pressed_since_last_check(CAPTURE_HOTKEY_VK)

        if force_capture:
            lines = asyncio.run(ocr_image(img))
            highlighted_text = find_highlighted_text(img, lines)
            name = save_known_screen(img, lines, highlighted_text)
            print(f"Captured candidate library screen: {name}")
            speaker.speak("Captured: " + name.replace("_", " ") + ". Needs review before it will be read automatically.")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        match_result = library.match(img)

        if force_reread:
            if match_result:
                entry, distance = match_result
                print(f"Manual re-read (F9): library match '{entry['screen_id']}' (distance={distance}).")
                highlighted_text = find_highlighted_text_from_entry(img, entry)
                to_speak = highlighted_text if highlighted_text else ". ".join(entry["canonical_text"])
                screen_key = ("lib", entry["screen_id"])
            else:
                lines = asyncio.run(ocr_image(img))
                screen_texts = [l["text"] for l in lines]
                highlighted_text = find_highlighted_text(img, lines)
                print("Manual re-read (F9): no library match, using live OCR.")
                to_speak = highlighted_text if highlighted_text else (". ".join(screen_texts) if screen_texts else "No text detected.")
                screen_key = ("ocr", tuple(screen_texts))
            speaker.speak(to_speak)
            last_spoken_screen_key = screen_key
            pending_screen_key = None
            pending_screen_seen_count = 0
            last_spoken_highlight = highlighted_text
            pending_highlight = None
            pending_highlight_seen_count = 0
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        # --- Determine what's on screen this poll, library-first ---
        if match_result:
            entry, distance = match_result
            screen_key = ("lib", entry["screen_id"])
            screen_payload = ". ".join(entry["canonical_text"])
            screen_ocr_texts = None  # not applicable in library mode
            highlighted_text = find_highlighted_text_from_entry(img, entry)
        else:
            lines = asyncio.run(ocr_image(img))
            screen_texts = [l["text"] for l in lines]
            screen_key = ("ocr", tuple(screen_texts))
            screen_payload = ". ".join(screen_texts) if screen_texts else None
            screen_ocr_texts = screen_texts
            highlighted_text = find_highlighted_text(img, lines)

        # --- Screen-level change detection (e.g. main menu -> submenu) ---
        if screen_key == last_spoken_screen_key:
            pending_screen_key = None
            pending_screen_seen_count = 0
        elif screen_key == pending_screen_key:
            pending_screen_seen_count += 1
            if pending_screen_seen_count >= STABLE_POLLS_REQUIRED and screen_payload:
                print("Screen changed (stable):", screen_key)
                speaker.speak(screen_payload)
                if screen_key[0] == "ocr":
                    log_library_miss(img, screen_ocr_texts)
                last_spoken_screen_key = screen_key
                pending_screen_key = None
                pending_screen_seen_count = 0
                # The screen-read already covered whatever's highlighted on it.
                last_spoken_highlight = highlighted_text
                pending_highlight = None
                pending_highlight_seen_count = 0
        else:
            pending_screen_key = screen_key
            pending_screen_ocr_texts = screen_ocr_texts
            pending_screen_seen_count = 1

        # --- Highlight-change detection (cursor moved within the same screen) ---
        screen_just_changed = screen_key != last_spoken_screen_key
        if not screen_just_changed:
            if highlighted_text == last_spoken_highlight:
                pending_highlight = None
                pending_highlight_seen_count = 0
            elif highlighted_text == pending_highlight:
                pending_highlight_seen_count += 1
                if pending_highlight_seen_count >= STABLE_POLLS_REQUIRED and highlighted_text:
                    print("Highlight changed (stable):", highlighted_text)
                    speaker.speak(highlighted_text)
                    last_spoken_highlight = highlighted_text
                    pending_highlight = None
                    pending_highlight_seen_count = 0
            else:
                pending_highlight = highlighted_text
                pending_highlight_seen_count = 1

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
