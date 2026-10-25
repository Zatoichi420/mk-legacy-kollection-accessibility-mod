# Reading Legacy Kollection's menus natively (2026-10-21)

Short answer: it works. A 64-bit add-on (`native/legacyhook`, loaded as
`dinput8.dll`) speaks the selected menu item the moment it changes, with the
game's own text. This replaces an earlier draft of this file that guessed
the menus were Lua scripts; testing showed otherwise.

## What the game is made of (build of 2026-04, `mk_legacy_kollection.exe`)

- 64-bit, address randomisation on, no symbols, but a full function table
  (`.pdata`), so every function's start and end is known.
- **Dear ImGui 1.89.8 is linked in but doesn't draw the menus.** The live
  ImGui context has one window, the inactive fallback "Debug##Default".
  Its frame counter still ticks every frame, which the add-on uses.
  (Context pointer at RVA 0xDC8D80; this build's ImGuiIO/Style are 11,520
  bytes smaller than a default build, so FrameCount is at +4400.)
- **Lua 5.3.5 and a Lua UI binding layer are linked in but unused** by the
  launcher: hooks on `lua_load` and on the bindings (`localize`,
  `push_document`, …) never fire.
- **The menus are C++ code using Digital Eclipse's UI engine**
  (`bakesale/src/ui/ui_lua.cpp` names the same functions the Lua bindings
  wrap). Each menu is rebuilt every frame, immediate-mode style:
  - text create, RVA 0x145BC0: `rcx` = UI, `edx` = style number,
    `r9` = UTF-8 text, `xmm1` = y.
  - set colour, RVA 0x139720: `rcx` = UI, `edx` = ARGB; applies to the
    element just created.
  - text lookup, RVA 0x1086E0: key (`str_play_uc`) to text ("PLAY").
- The PlayStation games run in `pancake_libretro_windows.dll` (exports
  `retro_get_memory_data`); the arcade and other console games are emulated
  inside the exe. Screens inside the emulated games (fighter select) aren't
  drawn by the UI engine.

## How the add-on finds the selected item

Every text and colour call in a frame is recorded with its call site (the
return address). Texts from one call site are one list. The selected item
is:

1. **the one with its own style number** (main menu and sub-menus: 7 among
   6; two-item pop-ups like NO / YES use the same pair);
2. **the one whose following colour differs** from the others' (a game's
   menu, pause-menu settings: gold `FFF1AD2B` among `A02B529B`);
3. **the one followed by a colour call made once per frame** (Options).

A value-style text (style 11) right after the selected item is its value:
"MENU MUSIC, ON". Headings (style 8) and a new screen's other texts (a
pop-up's question, a game's description) are said first; a text that
changes as you move (the Game Library's game name, a fighter in the Krypt)
is said after the item. Lists wait one frame after they appear so the
heading comes first. Button placeholders such as `{menu_accept}` become
words, and the button-hint bar isn't read.

## Checked with scripted input, speech muted (2026-10-21 overnight)

Title prompt, intro text, main menu, PLAY sub-menu, Options (values and
changes), Online Options, Game Library (filter tabs, game names), a game's
menu and description, in-game pause menu, Additional Settings, the
Quit Game pop-up (question, message, NO / YES), the Krypt menu,
Kombatants gallery, Kombat Kard. Speech on was also run (inside the game,
with the PC muted) without problems.

## Not done yet

- Game Library: the platform (shown only as an icon) and the year. Several
  versions share a name ("Mortal Kombat"), so they currently sound alike.
- Moves List (needs a fight in progress to test), Controls, Flyers,
  Documentary and Lore viewers, the volume slider's value, emulator
  messages (rewind, save state).
- Kombat Kard's tabs and pairing its labels with values.
- Screens inside the emulated games (fighter select) still need the OCR
  reader; it should stay quiet on screens the add-on covers (named mutex),
  and the installer should copy the add-on into the game folder.
- Game updates move the addresses; each hook checks its function's first
  bytes and switches itself off if they don't match.

## Developer tools

`legacyhook_probe.txt` (RVAs, one per line; `t` after one logs every call's
raw arguments while `legacyhook_trace_on` exists), `legacyhook_frames.txt`
(log every new screen's texts), `legacyhook.ini` (`[speech] mute=1` logs
`SAY` lines without speaking).
