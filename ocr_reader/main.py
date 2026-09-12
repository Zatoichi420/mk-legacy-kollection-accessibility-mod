"""
MK Legacy Kollection accessibility reader.

Continuously captures the game window and speaks its contents via NVDA.
On each poll, first tries to recognize the current screen against the
hand-verified reference library (known_screens/, matched by perceptual
image hash - see game_a11y_core/screen_library.py, "the hook"): a match
speaks that screen's pre-verified canonical_text instead of live OCR,
which is both faster and immune to this game's various OCR failure modes
(stylized/compressed fonts that Windows OCR mangles or misses entirely -
see PROGRESS.md section 5 for why this replaced the original OCR-only
design).

If no library entry matches, falls back to live OCR (today's original
behavior) as a best-effort read, and logs the miss to library_misses/ so
it can be reviewed and folded into the library later.

Within either mode, the currently-highlighted item (if the screen is a
list/tab style menu) is tracked separately via color: this game renders
the selected item in a distinct cyan/blue with a glow, vs. gold/yellow for
unselected items - see PROGRESS.md for the calibration.

2026-09-12: capture, OCR, NVDA speech, the screen library, process
lifecycle/locking, and hotkey handling moved into game_a11y_core/ (shared
with the MKX sister project - see mk-a11y-core's README for how that
package is kept in sync) as part of a Phase 0 shared-core extraction. Two
deliberate behavior changes came with it: the capture hotkey moved from
F10 to F2 and a toggle was added at F10 (unifying with MKX's convention -
this project previously had no on/off toggle at all), and a
screen-changed announcement now queues behind whatever NVDA is still
saying instead of cutting it off (the highlight-changed announcement
still interrupts, since it should stay terse and immediate). Everything
else is unchanged from the 2026-08-19 reliability pass.

F9 forces an immediate re-read of whatever's on screen right now (fallback
for screens/dialogs that don't fit the above). F2 captures the current
screen (screenshot + live OCR) into known_screens/ as a *candidate* new
library entry - it still needs a canonical_text field hand-verified from
the image before screen_library.py will treat it as trustworthy. F10
toggles the reader on/off without closing it - it always announces the
toggle itself even while "off", so silence never means "is this even
running?".
"""

import asyncio
import os
import time

import win32gui

from game_a11y_core.capture import PrintWindowCapture
from game_a11y_core.highlight import HighlightCalibration, find_highlighted_text, find_highlighted_text_from_entry
from game_a11y_core.hotkeys import HotkeyConfig, was_key_pressed_since_last_check
from game_a11y_core.lifecycle import acquire_single_instance_lock, find_window_for_process, release_single_instance_lock
from game_a11y_core.nvda_speaker import wait_for_nvda
from game_a11y_core.ocr import ocr_image
from game_a11y_core.screen_capture_tools import log_library_miss, save_known_screen
from game_a11y_core.screen_library import ScreenLibrary

PROCESS_NAME = "mk_legacy_kollection.exe"
POLL_INTERVAL_SECONDS = 0.5
HOTKEYS = HotkeyConfig(reread_vk=0x78, capture_vk=0x71, toggle_vk=0x79)  # F9, F2, F10
# When auto-started alongside the game (see run_reader.bat/start_reader.vbs),
# there's no terminal to Ctrl+C from, so exit on our own once the game window
# has been gone this long (covers "player closed the game").
EXIT_AFTER_WINDOW_GONE_SECONDS = 120
STABLE_POLLS_REQUIRED = 2  # OCR/highlight can be slightly noisy frame-to-frame; require it to settle before speaking
# Classic-game OCR can be noisy enough to never repeat two polls in a row
# identically (see PROGRESS.md) - without this, an uncatalogued screen could
# stay silent forever waiting for exact stability. After this many
# consecutive polls of "something changed, just not the same way twice",
# speak the latest OCR reading once as best-effort instead of waiting.
FORCE_SPEAK_AFTER_UNSTABLE_POLLS = 8
# A single bad poll is tolerated (see the try/except in the main loop), but
# if failures never stop (not just "the window is gone", which has its own
# handling above), the old crash-and-let-a-relaunch-recover behavior is
# restored here instead of retrying forever as a zombie that blocks any
# future relaunch's duplicate-instance check from ever starting a fresh,
# healthy reader.
EXIT_AFTER_CONSECUTIVE_POLL_FAILURES = 240

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NVDA_DLL_PATH = os.path.join(SCRIPT_DIR, "game_a11y_core", "nvda_controller_client", "x64", "nvdaControllerClient.dll")
KNOWN_SCREENS_DIR = os.path.join(SCRIPT_DIR, "known_screens")
LIBRARY_MISSES_DIR = os.path.join(SCRIPT_DIR, "library_misses")
LOCK_FILE_PATH = os.path.join(SCRIPT_DIR, "reader.lock")

CAPTURE = PrintWindowCapture()

# Calibrated against this game's menu highlight style: selected items are
# rendered cyan/blue (~RGB 105,200,230), unselected gold/yellow
# (~RGB 240,212,126). Blue-channel-exceeds-red-channel cleanly separates
# the two - see PROGRESS.md for the sampled values.
HIGHLIGHT_CALIBRATION = HighlightCalibration(brightness_threshold=300, blue_minus_red_threshold=30)


def main():
    print("MK Legacy Kollection accessibility reader starting...")

    if not acquire_single_instance_lock(LOCK_FILE_PATH):
        print("Another reader instance is already running; exiting.")
        return

    try:
        speaker = wait_for_nvda(NVDA_DLL_PATH)
        print("NVDA connection OK.")

        library = ScreenLibrary(KNOWN_SCREENS_DIR)
        print(f"Loaded {len(library.entries)} verified screens into the recognition library.")

        speaker.speak("Accessibility reader ready.")

        hwnd = None
        hwnd_ever_found = False
        window_missing_since = None
        consecutive_poll_failures = 0
        reader_enabled = True

        # screen_key identifies "what's currently on screen" for change detection:
        # ("lib", screen_id) when the library recognized it, ("ocr", tuple_of_lines)
        # when falling back to live OCR. screen_payload is the text to actually speak.
        last_spoken_screen_key = None
        pending_screen_key = None
        pending_screen_seen_count = 0
        pending_screen_unstable_count = 0

        last_spoken_highlight = None
        pending_highlight = None
        pending_highlight_seen_count = 0

        def reset_tracking():
            nonlocal last_spoken_screen_key, pending_screen_key
            nonlocal pending_screen_seen_count, pending_screen_unstable_count
            nonlocal last_spoken_highlight, pending_highlight, pending_highlight_seen_count
            last_spoken_screen_key = None
            pending_screen_key = None
            pending_screen_seen_count = 0
            pending_screen_unstable_count = 0
            last_spoken_highlight = None
            pending_highlight = None
            pending_highlight_seen_count = 0

        while True:
            try:
                if HOTKEYS.has_toggle and was_key_pressed_since_last_check(HOTKEYS.toggle_vk):
                    reader_enabled = not reader_enabled
                    # Bypass reader_enabled here on purpose - the toggle
                    # itself must always be audible, even when turning the
                    # reader off, or silence could mean either "it's off"
                    # or "it's broken" with no way to tell which.
                    speaker.speak("Reader on." if reader_enabled else "Reader off.")
                    reset_tracking()
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                if not reader_enabled:
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

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

                img = CAPTURE.grab(hwnd)
                if img is None:
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                force_reread = was_key_pressed_since_last_check(HOTKEYS.reread_vk)
                force_capture = was_key_pressed_since_last_check(HOTKEYS.capture_vk)

                if force_capture:
                    lines = asyncio.run(ocr_image(img))
                    highlighted_text = find_highlighted_text(img, lines, HIGHLIGHT_CALIBRATION)
                    name = save_known_screen(img, lines, highlighted_text, KNOWN_SCREENS_DIR)
                    print(f"Captured candidate library screen: {name}")
                    speaker.speak("Captured: " + name.replace("_", " ") + ". Needs review before it will be read automatically.")
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                match_result = library.match(img)

                if force_reread:
                    if match_result:
                        entry, distance = match_result
                        print(f"Manual re-read (F9): library match '{entry['screen_id']}' (distance={distance}).")
                        highlighted_text = find_highlighted_text_from_entry(img, entry, HIGHLIGHT_CALIBRATION)
                        to_speak = highlighted_text if highlighted_text else ". ".join(entry["canonical_text"])
                        screen_key = ("lib", entry["screen_id"])
                    else:
                        lines = asyncio.run(ocr_image(img))
                        screen_texts = [l["text"] for l in lines]
                        highlighted_text = find_highlighted_text(img, lines, HIGHLIGHT_CALIBRATION)
                        print("Manual re-read (F9): no library match, using live OCR.")
                        to_speak = highlighted_text if highlighted_text else (". ".join(screen_texts) if screen_texts else "No text detected.")
                        screen_key = ("ocr", tuple(screen_texts))
                    speaker.speak(to_speak)
                    last_spoken_screen_key = screen_key
                    pending_screen_key = None
                    pending_screen_seen_count = 0
                    pending_screen_unstable_count = 0
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
                    highlighted_text = find_highlighted_text_from_entry(img, entry, HIGHLIGHT_CALIBRATION)
                else:
                    lines = asyncio.run(ocr_image(img))
                    screen_texts = [l["text"] for l in lines]
                    screen_key = ("ocr", tuple(screen_texts))
                    screen_payload = ". ".join(screen_texts) if screen_texts else None
                    screen_ocr_texts = screen_texts
                    highlighted_text = find_highlighted_text(img, lines, HIGHLIGHT_CALIBRATION)

                # --- Screen-level change detection (e.g. main menu -> submenu) ---
                if screen_key == last_spoken_screen_key:
                    pending_screen_key = None
                    pending_screen_seen_count = 0
                    pending_screen_unstable_count = 0
                else:
                    pending_screen_unstable_count += 1
                    if screen_key == pending_screen_key:
                        pending_screen_seen_count += 1
                    else:
                        pending_screen_key = screen_key
                        pending_screen_seen_count = 1

                    stabilized = pending_screen_seen_count >= STABLE_POLLS_REQUIRED
                    # Classic-game OCR can be noisy enough that two consecutive
                    # polls of an uncatalogued screen never come back byte-for-byte
                    # identical, so "stabilized" alone can wait forever and the
                    # screen never gets announced at all. Once we've seen enough
                    # consecutive "something's different" polls without it ever
                    # settling, speak the latest OCR reading once as best-effort
                    # rather than staying silent - library matches don't need this,
                    # they're pre-verified text, not noisy live OCR.
                    gave_up_waiting = (
                        not stabilized
                        and screen_key[0] == "ocr"
                        and pending_screen_unstable_count >= FORCE_SPEAK_AFTER_UNSTABLE_POLLS
                    )
                    if (stabilized or gave_up_waiting) and screen_payload:
                        print(
                            "Screen changed (stable):" if stabilized
                            else "Screen changed (best-effort, OCR never stabilized):",
                            screen_key,
                        )
                        # interrupt=False: let a still-playing announcement
                        # finish rather than chopping it mid-sentence - see
                        # game_a11y_core/nvda_speaker.py.
                        speaker.speak(screen_payload, interrupt=False)
                        if screen_key[0] == "ocr":
                            log_library_miss(img, screen_ocr_texts, LIBRARY_MISSES_DIR)
                        last_spoken_screen_key = screen_key
                        pending_screen_key = None
                        pending_screen_seen_count = 0
                        pending_screen_unstable_count = 0
                        # The screen-read already covered whatever's highlighted on it.
                        last_spoken_highlight = highlighted_text
                        pending_highlight = None
                        pending_highlight_seen_count = 0

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
            except Exception as exc:
                # A single bad poll (e.g. the game window died mid-capture)
                # must never kill the whole reader - with no console attached
                # in normal use, an uncaught exception here means NVDA just
                # goes silent with no indication anything went wrong. Log it
                # and keep polling instead - but if failures never stop (not
                # just the window being gone, handled separately above), give
                # up and exit so a future relaunch's duplicate-instance check
                # can start a fresh, healthy reader instead of this one
                # retrying forever as a zombie that blocks it from doing so.
                consecutive_poll_failures += 1
                print(f"Poll cycle failed ({consecutive_poll_failures} in a row), skipping and continuing: {exc!r}")
                if consecutive_poll_failures >= EXIT_AFTER_CONSECUTIVE_POLL_FAILURES:
                    print("Too many consecutive poll failures; exiting so a relaunch can recover.")
                    return
                time.sleep(POLL_INTERVAL_SECONDS)
            else:
                consecutive_poll_failures = 0
    finally:
        release_single_instance_lock(LOCK_FILE_PATH)


if __name__ == "__main__":
    main()
