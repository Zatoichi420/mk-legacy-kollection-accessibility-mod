# Can Legacy Kollection's menus be read natively? (analysis, 2026-10-21)

Short answer: yes, and much better than with OCR. The earlier conclusion
("immediate-mode ImGui, no widget tree, dead end") was wrong about which
system draws the menus.

## What the game is made of (build of 2026-04, `mk_legacy_kollection.exe`)

- 64-bit, address randomisation on, no symbols, but a full function table
  (`.pdata`), so every function's start and end is known.
- **Dear ImGui 1.89.8 is linked in but does not draw the menus.** Reading
  the live ImGui context showed one window, ImGui's built-in fallback
  "Debug##Default", inactive. (Context pointer: global at RVA 0xDC8D80.
  The game's ImGuiIO/Style are 11,520 bytes smaller than a default build,
  so FrameCount is at +4400, not +15920. Gamepad navigation is on.)
- **The menus are a Lua 5.3.5 UI**, from Digital Eclipse's own engine
  (`bakesale/src/ui/ui_lua.cpp`). The program names the scripts
  `init.lua`, `ui/constants.lua` and `ui/functions.lua`; they and the
  screen scripts live in the 12 GB `assets.pie`, compressed.
- The UI works like a web page: **documents** made of **elements** with
  tags, text, layout and **navigation** (`set_nav`, `navigate`), and
  **focus events** (`enter`, `leave`, `move`, `click`). Functions the
  scripts call include `localize`, `push_document`, `pop_document`,
  `show_modal`, `find_element`, `get_tag`, `text_set_color`.
- Menu text styles are named after their state:
  `fullscreen_menu_item_selected` / `_unselected`, `fullscreen_menu_title`,
  `fullscreen_menu_description`, `fullscreen_menu_toggle_value_selected`,
  `fullscreen_menu_slider_text_selected`, `game_pause_menu_progress`. So
  the game itself knows which item is selected when it draws it.
- The three PlayStation games run in `pancake_libretro_windows.dll`, a
  libretro core that exports `retro_get_memory_data`, so their RAM can be
  read. The arcade and other console games are emulated inside the exe.

## Why the current reader feels slow

Each full-screen OCR pass takes 0.5–1.3 s (reader.log), and a screen is
only spoken once two passes agree, so a menu move is heard 1–3 s later,
and OCR misreads or cuts off stylised text. The MK9 native hook built on
2026-10-20 speaks within ~0.1 s with the game's exact text; the same is
possible here.

## Plan

1. **Loader.** The game imports DINPUT8, so the same proxy-DLL approach as
   MK9 works, built for x64. (The old proxy in the game folder is disabled
   and must not be re-enabled as is; see `proxy_dll/README.md`.)
2. **Find Lua 5.3.5's API in the exe.** Anchor strings are present
   ("attempt to load a %s chunk", "C stack overflow", "stack traceback",
   "_ENV"); compile Lua 5.3.5 with MSVC x64 and match functions
   (`lua_load`, `lua_pcallk`, `lua_pushcclosure`, `lua_setglobal`,
   `lua_getglobal`), and find `localize` and the UI's C functions from the
   `ui_lua.cpp` registration table.
3. **Dump the UI scripts** as the game loads them (hook `lua_load`). This
   shows exactly how each screen builds its menu, names its items and
   moves the selection. Read-only, safe first step.
4. **Speak from inside the UI.** Either hook the C side of focus changes
   (the `enter` event / `navigate`), reading the focused element's text,
   or register a `speak()` function in the game's Lua and wrap the menu
   functions in Lua so each selection change calls it with the localized
   label, value and description. Both give the exact text, instantly, with
   the real selection: launcher menus, Game Library, settings, the in-game
   pause menus and move lists.
5. **Keep OCR for what Lua doesn't draw**: fighter select and other
   screens inside the emulated games. Later, read the PlayStation games'
   RAM through `retro_get_memory_data` for fighter names (RetroAchievements
   memory notes may already map the cursor addresses).
6. Make the OCR reader stay quiet on screens the hook covers (named mutex),
   and add the DLL to Setup.exe.

Risks: online features use PlayFab (the hook must only read and speak);
game updates move addresses, so the hook should find functions by byte
patterns and switch itself off safely if a pattern isn't found.
