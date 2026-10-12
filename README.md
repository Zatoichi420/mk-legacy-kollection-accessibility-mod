# MK Legacy Kollection Accessibility Reader

Speaks the menus of **Mortal Kombat Legacy Kollection** (Windows, Steam) for blind and low-vision players. It reads each menu screen when it appears, and the highlighted item as you move through a menu. It speaks through NVDA or JAWS, and through the Windows voice for Narrator users or when no screen reader is running.

The game draws its menus as pictures, so screen readers can't see them on their own. This reader runs alongside the game, recognises the screen, and speaks it. It doesn't change the game or any of its files.

**Status:** early release (1.0). It has been tested by the developer only. Reports of what works and what doesn't are very welcome. See [Reporting problems](#reporting-problems).

## What it reads

- **The launcher**: main menu, Play menu, the Game Library, every game's own menu, Options (each setting with its value, and changes as you make them), The Krypt (Documentary, Lore, Kombatants, Music Player), Kombat Kard, and the Quit and Reset dialogs. Each new screen is read in full and ends with what's selected, for example "Selected: Play". Moving the cursor reads just the new item.
- **The Game Library carousel**: each game's name, year and platform, for example "Mortal Kombat. 1993. Sega Genesis". Switching tabs reads the tab, then the game.
- **Every game's pause menu** (Escape in a game): Resume, Moves List (with each fighter's moves), On-screen move list, Additional settings, Screen options, Controls, Save, Load, Reset and Quit, plus their confirmation dialogs.
- **Fighter names on character select** in arcade Mortal Kombat (1992) and arcade Mortal Kombat II. These games print no names, so the reader works out which portrait the selection box is on.
- Screens the reader doesn't know are read with Windows' text recognition, cleaned up against a list of the words this game uses. The older games' pixel fonts still come out garbled at times, for example their story screens. Press **F9** to hear a screen again.

The reader stays quiet during fights and on attract-mode score tables, which only produce noise.

### Known limits

- Character select in the other games (Mortal Kombat 3 onward and the console versions) doesn't name the fighter yet.
- A very short highlighted value, such as "TV" in Screen options, sometimes isn't read; you hear just the setting's name.
- Online modes (Quick Match, Online Arcade) haven't been tested.

## What you need

- Windows 10 or 11, 64-bit.
- Mortal Kombat Legacy Kollection.
- A screen reader is optional. How each one works with the reader:
  - **NVDA**: the reader speaks through NVDA, in your NVDA voice and settings.
  - **JAWS**: the reader speaks through JAWS, in your JAWS voice and settings.
  - **Windows Narrator**: Narrator doesn't let other programs speak through it, so the reader uses the Windows voice. You'll hear two voices: Narrator for Windows itself, and the Windows voice for the game's menus.
  - **No screen reader**: the reader uses the Windows voice.
  - If NVDA or JAWS starts, stops or restarts while you play, the reader switches voice on its own. No restart is needed.
- **Windows text recognition** (OCR), for screens the reader doesn't already know. It's normally installed along with English. If it's missing, the reader tells you; see [Troubleshooting](#troubleshooting).

## Install

1. Go to the [Releases page](https://github.com/Zatoichi420/mk-legacy-kollection-accessibility-mod/releases/latest) and download the file whose name starts with `MK-Legacy-Kollection-Access-Setup`.
2. Your browser may warn that the file isn't commonly downloaded. Choose to keep it.
3. Run the file. Because the installer isn't code-signed, Windows may show a **"Windows protected your PC"** screen. Move to the **More info** link and activate it, then move to the **Run anyway** button that appears and activate it.
4. Follow the setup wizard. It doesn't ask for administrator rights. There's one option, a checkbox that is ticked by default: **Start the reader automatically when I sign in to Windows**. Leave it ticked unless you'd rather start the reader yourself each time. The reader stays silent until the game is open.
5. On the last page, leave **Start the accessibility reader now** ticked and choose **Finish**. You should hear "Accessibility reader ready. Waiting for the game."

## Using it

1. Start the game from Steam as usual. When the reader finds the game you'll hear **"Game window found."**
2. Each new menu screen is read in full. In the launcher's menus, the highlighted item is read as you move through them.

Keys. These only work while the game is the focused window:

- **F9** reads the current screen, or the highlighted item, again.
- **F10** turns the reader off or on. It always tells you which.

If you switch away from the game (for example with Alt+Tab), the reader pauses. When you switch back, it reads the current screen again.

On some laptops the F keys control volume or brightness unless you hold **Fn**. If F9 and F10 do nothing, try Fn+F9 and Fn+F10.

### Start menu entries

Press the Windows key and type **accessibility reader** to find these:

- **Start accessibility reader**: starts the reader if it isn't running, and tells you if it already is.
- **Stop accessibility reader**: stops it until you start it again, or until you next sign in if it starts automatically.
- **Check accessibility reader**: runs a quick check and reports which voice is in use, whether text recognition is installed, whether the reader and the game are running, and whether it starts at sign-in. The result is shown in a standard message box, which your screen reader will read.
- **Read me**: opens this page.
- **Uninstall accessibility reader**.

## Troubleshooting

**Nothing is spoken at all.** Run **Check accessibility reader** from the Start menu. If it says the reader isn't running, run **Start accessibility reader**.

**You hear a low beep instead of speech.** No voice was available: neither NVDA nor JAWS was running, and the Windows voice couldn't be started either. Start NVDA or JAWS. The reader switches to it automatically, with no restart needed.

**With JAWS, you hear the Windows voice instead of JAWS.** The reader couldn't connect to JAWS. Restart JAWS, then switch back to the game. If it keeps happening, please report it and include the log file, which says why the connection failed.

**"Windows text recognition is not installed".** Known screens still work. To read the others, install English text recognition. Open **PowerShell as administrator** and run:

```
Add-WindowsCapability -Online -Name "Language.OCR~~~en-US~0.0.1.0"
```

Then restart the reader: use **Stop accessibility reader**, then **Start accessibility reader**.

**A screen is read wrongly, or not at all.** Press F9 to try again. Unrecognised screens are saved in the reader's data folder (see below) so they can be added later. Attaching one to a problem report helps a lot.

**Run the game at a 16:9 resolution** (for example 1920 by 1080, 2560 by 1440, or 1280 by 720). The reader recognises screens at any size but expects that shape.

**"The accessibility reader stopped after repeated errors."** Start it again from the Start menu. If it keeps happening, please report it and include the log file.

**The log file** records what the reader did and everything it said. To open its folder, press **Windows+R**, type `%LOCALAPPDATA%\MKLegacyKollectionAccess` and press Enter. The log is `reader.log`, and unrecognised screens are in `library_misses`.

## Uninstall

Use **Uninstall accessibility reader** in the Start menu, or Settings, Apps, Installed apps. This also turns off starting at sign-in, and removes the log and saved screens.

## Privacy

The reader works entirely on your PC and never connects to the internet. It takes screenshots of the game window only. It keeps the 50 most recent screens it didn't recognise, in its data folder, so they can be reviewed if you choose to share them. Nothing is sent anywhere.

## Reporting problems

Open an issue on [GitHub](https://github.com/Zatoichi420/mk-legacy-kollection-accessibility-mod/issues). Please say which game and screen you were on, and what you heard or expected to hear. If you can, attach `reader.log` and any relevant images from `library_misses`.

## Command-line options

The program is `mk-legacy-access.exe` in the install folder. The Start menu entries use these options:

- `--stop`: ask a running reader to stop, and wait until it has.
- `--self-test`: run the check described above. Add `--quiet` for no dialog or speech, and `--report-file PATH` to save the results as JSON.
- `--background`: don't announce startup. This is what start-at-sign-in uses.
- `--speech auto|nvda|jaws|sapi|none`: choose the voice. The default, `auto`, uses NVDA if it's running, then JAWS if it's running, and the Windows voice otherwise. `sapi` always uses the Windows voice. `none` only writes speech to the log.
- `--ignore-focus`: keep reading even when the game isn't the focused window.
- `--dev`: developer mode; see below.
- `--version`.

## For developers

The reader is Python 3.12, Windows only. The code is in `ocr_reader/`. `main.py` is the entry point, and `game_a11y_core/` is the capture, OCR, speech and screen-matching core, which is shared with the MKX accessibility mod. `docs/PROGRESS.md` is the full development history, covering why the design is what it is and what was tried and abandoned.

```
py -3.12 -m pip install -r requirements.txt -r requirements-dev.txt
py -3.12 -m pytest tests
py -3.12 ocr_reader\main.py --dev
py -3.12 packaging\build.py
```

`packaging\build.py` produces the program folder, Setup.exe (needs [Inno Setup 6](https://jrsoftware.org/isinfo.php)), a portable zip and checksums in `dist\`. GitHub Actions does the same on every push, then runs `packaging\ci\smoke_test.py`. Pushing a `v*` tag that matches `ocr_reader\version.py` publishes a release.

**Adding a screen to the library:** run with `--dev`, go to the screen in the game, and press **F2**. That saves `<name>.png` (what the matcher compares against), `<name>.full.png` (the whole screen, for review only) and `<name>.json` with raw OCR text and `canonical_text: null`. A screen isn't spoken until someone checks the image and fills in `canonical_text` with the exact on-screen text. Then run the tests: `test_no_two_screens_are_confusable` fails if the new screen is too similar to an existing one. If it is, add an `roi` that covers the part of the screen that differs, as the two MK2 continue screens do.

`proxy_dll/` and `rtti_probe/` are research into reading the game's memory directly. They aren't part of the reader.

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to contribute.

## Licence

MIT; see [LICENSE](LICENSE). See [NOTICE](NOTICE) for trademarks and the bundled NVDA Controller Client, which is under the LGPL 2.1. Not affiliated with Warner Bros., NetherRealm Studios, Digital Eclipse or Atari.
