# Mortal Kombat Legacy Kollection — Accessibility Reader

Makes the menus of *Mortal Kombat Legacy Kollection* (the launcher, and the
menus of the emulated classic games inside it) speak through **NVDA**.
Gameplay itself is out of scope — only menu/UI screens.

**Status: early testing.** See `PROGRESS.md` for the full history, design
rationale, and known gaps. This is a private pre-release repo — please
don't share the link further until it's ready for a public release.

## How it works

1. It captures the game's window and recognizes the current screen against
   a hand-verified reference library (`ocr_reader/known_screens/`) using a
   perceptual image hash — no game modification or code injection involved.
2. A recognized screen is spoken using pre-verified text (accurate even
   where this game's fonts don't OCR cleanly).
3. An unrecognized screen falls back to live OCR as a best-effort read, and
   gets logged to `ocr_reader/library_misses/` so it can be reviewed and
   added to the library later.
4. Moving the cursor within a menu (e.g. between PLAY / THE KRYPT) is
   tracked separately via the color of the highlighted item, and announced
   as you navigate.

## Requirements

- Windows, with [NVDA](https://www.nvaccess.org/download/) installed and
  running.
- *Mortal Kombat Legacy Kollection* installed via Steam.
- Python 3.12+ (from python.org or the Microsoft Store).

## Setup

```
pip install -r requirements.txt
```

## Running it

1. Start NVDA if it isn't already running.
2. Launch the game normally from Steam.
3. Open a terminal in `ocr_reader/` and run:
   ```
   python main.py
   ```
   (or double-click `run_reader.bat`)
4. Navigate the menus. NVDA should announce screens as they change, and
   announce the highlighted item as you move the cursor.

Press **F9** at any time to force an immediate re-read of whatever's on
screen. Press **F10** to save the current screen into `known_screens/` as
a candidate library entry (it won't be read automatically until someone
reviews the screenshot and fills in its `canonical_text` field — this is
intentional, see `PROGRESS.md` §5 for why).

The reader doesn't need to be started before the game, and doesn't need to
be closed after — it waits for the game window if it isn't open yet, and
exits on its own a couple of minutes after the game window disappears.

## Reporting what you find

Since this is early testing, the most useful thing to report is:
- Which screen you were on (game + menu name) and what NVDA said, if
  anything.
- Whether it matched a known library entry (fast, accurate) or fell back
  to live OCR (slower, sometimes garbled) — the console window `main.py`
  runs in prints which path it took for each screen change.
- Anything in `ocr_reader/library_misses/` after your session — those are
  screens the library doesn't recognize yet.

## What's not included here

- `tools/` (a downloaded copy of radare2, used during early reverse-
  engineering attempts) and `proxy_dll/third_party/` (a vendored build
  dependency) are left out of this repo on purpose — see `.gitignore`.
- `proxy_dll/` itself is an abandoned experimental approach (hooking the
  game's rendering engine directly) that was superseded by the
  OCR/image-recognition approach actually in use. It's kept for reference
  but isn't needed to run the reader and isn't part of the tested path.
