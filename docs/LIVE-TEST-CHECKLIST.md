# Live test checklist (before tagging a release)

CI checks the built program against a stand-in game window, but it can't
cover the real game, real speech, or 150% display scaling. Do this pass on
the Windows PC with the real game before pushing a `v*` tag. It takes about
15 minutes. Report anything that fails, including what you heard.

The log is at `%LOCALAPPDATA%\MKLegacyKollectionAccess\reader.log` (press
Windows+R, paste the folder path, press Enter). Each item below says which
log line confirms it, for when speech alone isn't conclusive.

## Before you start

- [ ] Remove the old Steam launch option if it's still set: the game's
      Properties, General, Launch Options, which held a line containing
      `start_reader.vbs`. Leave the box empty. The installed reader replaces
      it, and the old script no longer exists in the repo.
- [ ] Close any old `python main.py` reader that's still running.

## 1. Install

- [ ] Download Setup.exe from the CI run's artifact or the draft release,
      and run it. Note whether SmartScreen appears and whether the README's
      steps got you past it.
- [ ] The wizard reads sensibly with NVDA, and the start-at-sign-in checkbox
      is announced as checked.
- [ ] On Finish you hear "Accessibility reader ready. Waiting for the game."

## 2. Check

- [ ] Start menu, **Check accessibility reader**: NVDA reads the message box.
      It should say Self-test passed, Voice NVDA, a text recognition
      language, 18 known screens, Reader running, Start at sign-in on.

## 3. The game, with NVDA (most important)

- [ ] Start the game from Steam: you hear "Game window found."
- [ ] Log: `Game capture size: 1920x1080` (**not** 1280x720). This confirms
      the scaling fix. Note the size you actually got.
- [ ] Main menu is read in full.
- [ ] Play menu, Game Library, and the tabs (All/Arcade/Console): each
      screen is read, and moving between tabs speaks the selected tab.
- [ ] MK1 and MK2 game menus: screen read, and moving the cursor speaks each
      item (Play Game, Versus, Training, ...).
- [ ] Quit Game dialog (open it, then cancel).
- [ ] MK2 arcade: Choose Your Fighter, pause menu. If you can, also the
      continue screen and Prepare For Your Next Kombat. These two used to be
      too similar; check each is read as itself.
- [ ] A screen that isn't in the library (Options, Extras or Credits) gets a
      best-effort read. It should now include text from the right side and
      bottom of the screen that used to be cut off.
- [ ] F9 re-reads. F10 says "Reader off.", F10 again says "Reader on."
- [ ] Alt+Tab to another window: the reader goes quiet (log: `Game is not
      the focused window`). Alt+Tab back: the current screen is read again.
- [ ] Press F10 while in another app (Notepad, say): nothing happens, and it
      doesn't toggle the reader later when you return to the game.

## 3b. Added overnight 2026-10-11 (check these especially)

- [ ] Game Library: move left and right with the controller stick and the
      d-pad. Each game is read as name, year and platform, once it stops
      moving. The four "Mortal Kombat, 1993" versions each say their own
      platform.
- [ ] Any game's pause menu (Escape): read in full, then each item as you
      move. Moves List reads each fighter's moves. Reset Game and Quit Game
      dialogs read "No" and "Yes" as you move between them.
- [ ] Options: each setting is read with its value; changing a value with
      left or right announces the new value.
- [ ] Arcade Mortal Kombat and Mortal Kombat II character select: moving the
      selection reads each fighter's name.
- [ ] During a fight the reader stays quiet.
- [ ] The Krypt: Documentary, Lore, Kombatants and Music Player are read.

## 4. Without NVDA

- [ ] If the display scaling is not 100%, note it here. The reader now
      captures each window at its own scaling, which fixed a stand-in game
      window being cut to its top-left corner at 150%.

- [ ] Quit NVDA (NVDA+Q) while the game is open: the next screen change is
      spoken in the Windows voice. Restart NVDA: speech moves back to NVDA.

## 4b. JAWS (if a JAWS licence or 40-minute demo is available)

- [ ] Quit NVDA and start JAWS. Start the game: "Game window found." is
      spoken by JAWS, in the JAWS voice, with no Windows voice on top.
      Log: `Speech output is now: JAWS`.
- [ ] Move through the launcher menus: each item is spoken by JAWS.
- [ ] Start menu, **Check accessibility reader**: says Voice JAWS. The result
      is read once, by JAWS, not twice.
- [ ] Quit JAWS while the game is open: speech moves to the Windows voice.
      Start JAWS again: speech moves back to JAWS.
- [ ] F9 and F10 still work with JAWS running.

## 4c. Narrator

- [ ] With NVDA and JAWS both closed, turn on Narrator (Ctrl+Windows+Enter).
      Start the game: menus are spoken in the Windows voice. Note whether
      Narrator and the Windows voice talking at once is a problem.
- [ ] Turn Narrator off again (Ctrl+Windows+Enter).

## 5. Start, stop, restart

- [ ] Quit the game. Log: `Game window closed`. The reader keeps running.
      Start the game again: "Game window found." and reading resumes.
- [ ] Start menu, **Stop accessibility reader**: "Accessibility reader
      stopped."
- [ ] **Start accessibility reader** twice: the second time says "The
      accessibility reader is already running."
- [ ] Sign out and back in, or restart Windows: no announcement at sign-in.
      Start the game: "Game window found."

## 6. Uninstall

- [ ] Start menu, **Uninstall accessibility reader**: completes, and nothing
      is spoken at the next sign-in.
