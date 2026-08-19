# MK Legacy Kollection — Screen Reader Accessibility Project

Goal: make the **launcher/front-end menus** of Mortal Kombat Legacy Kollection
(main menu + all submenus) speak their contents through NVDA.

**Scope update (2026-07-05):** the three emulated PS1 games' own **menus**
(title/main menu, options, password/save, pause) are now also in scope,
since they're static screens just like the launcher's. Actual **gameplay**
(fighting/levels) inside Trilogy, Mythologies, and Special Forces remains
explicitly **out of scope** — only their menu screens are targeted, same
boundary as the launcher.

Status key: `[ ]` not started · `[~]` in progress · `[x]` done

---

## 1. Analysis (2026-07-04)

### 1.1 Folder layout

```
Mortal Kombat Legacy Kollection/
├── mk_legacy_kollection.exe      <- the launcher/front-end (OUR TARGET)
├── assets.pie                    <- 12 GB packed asset blob (textures, fonts, audio, UI data)
├── pancake_libretro_windows.dll  <- PS1 emulator core ("pancake" libretro core)
├── steam_api64.dll, PlayFab*.dll, PartyWin.dll, libHttpClient.Win32.dll  <- Steam/online/party-chat plumbing
└── pancake/                      <- OUT OF SCOPE: raw PS1 game images + emulator support files
    ├── MortalKombatTrilogy_SLUS00330_SCEA.bin/.cue
    ├── MortalKombatMythologies_SLUS00476_SCEA.bin/.cue
    ├── MortalKombatSpecialForces_SLUS00824_SCEA.bin/.cue
    ├── libmipsaot-*.dll (MIPS ahead-of-time recompilers), openbios.bin, *.hle files
```

There are no loose config/localization/JSON/INI files anywhere — every UI
string, font, and texture the launcher uses lives inside the single
`assets.pie` blob in an opaque, undocumented format.

### 1.2 What `mk_legacy_kollection.exe` actually is

Version info / embedded PDB path identify it as an internal build called
**"Project Dragon"**, built with Digital Eclipse's internal
**"Bakesale/Dragon"** tooling (`C:\Bakesale\bakesale-project-dragon\...`).
This is the same shared front-end engine Digital Eclipse uses across their
other "Kollection"/anniversary compilations (Capcom Fighting Collection, SF
30th Anniversary Collection, TMNT Cowabunga Collection, etc.) — so anything
we build here is likely reusable if you ever want to do this for one of
those too.

Key facts confirmed by string/import analysis of the exe:

| Finding | Detail |
|---|---|
| UI toolkit | **Dear ImGui 1.89.8** (found literal version string) — this is the library actually drawing the main menu, submenus, buttons, etc. |
| Renderer | DirectX 11 / DirectX 12 (both present) |
| Audio | FMOD |
| Existing accessibility hooks | **None.** No UI Automation, MSAA/IAccessible2, SAPI, or NVDA references anywhere in the binary. |
| Anti-cheat/DRM | **None detected** (no EasyAntiCheat, BattlEye, Denuvo, VMProtect, Themida strings). Low risk for injection-based tooling. |
| Debug symbols | Referenced PDB path exists but the .pdb itself is not shipped — no symbol names available to us directly. |

### 1.3 Why this matters for accessibility

The menus are **not** standard Windows controls (no HWND-per-button, no
native accessibility tree at all) — they're painted every frame by Dear
ImGui as textured triangles. Windows' built-in accessibility APIs see none
of this; that's why NVDA is silent on this screen today, and why something
like "just turn on a Windows accessibility setting" can't fix it. Getting
NVDA to speak this UI requires building a small companion tool that reads
the menu state directly out of the game's own memory/rendering and forwards
it to NVDA.

The good news: **Dear ImGui is open source**, and this game is using a
stock, unmodified 1.89.8 build (confirmed by the version string). That
means the internal data structures (window stack, currently-focused/
navigated item, item labels) match the public ImGui source exactly, even
without the game's own PDB. That's what makes this tractable rather than a
guessing game against a fully custom, undocumented engine.

---

## 2. Proposed approach (for discussion)

**Primary plan: a small companion DLL that hooks Dear ImGui and speaks
through NVDA's official Controller Client API.**

Rough pipeline:
1. Get the DLL loaded into `mk_legacy_kollection.exe`'s process (either a
   classic injector, or a "proxy DLL" that sits next to the exe and
   piggybacks on a DLL the game already loads at startup — the latter means
   it just works whenever you launch the game normally, no separate
   injector step).
2. Hook the relevant Dear ImGui entry points (e.g. `Selectable`, `MenuItem`,
   `Button`, `TreeNodeEx`) using known 1.89.8 struct layouts/signatures —
   no game PDB needed, since ImGui's own source covers this.
3. Each frame, determine which item currently has keyboard/gamepad focus
   (ImGui's `NavId`/`NavWindow`) and capture its label text.
4. When the focused item's label changes (user moved the cursor), send that
   text to NVDA using **`nvdaControllerClient64.dll`** — this is NVDA's own
   officially supported "speak this text" API, distributed in the free NVDA
   SDK, designed for exactly this kind of external-app-to-screen-reader use
   case. No NVDA add-on needed on your end beyond having NVDA running.

Fallback if the ImGui-hooking route hits a wall: an OCR-based approach
(periodically screenshot the highlighted menu item's screen region, OCR it,
speak the result). More fragile and slower to react, but needs no reverse
engineering — kept in reserve.

### Suggested first milestone (low-risk proof of concept)
Before wiring up NVDA at all: get the injected DLL to dump every visible
menu label + which one is focused to a **log file** each time it changes,
while you navigate the real menu. If that lines up correctly with what's
actually on screen, the hard part is solved and wiring in
`nvdaControllerClient64.dll` afterward is comparatively simple.

### 2.1 What's actually hard about the next phase

Milestone 0 (proxy DLL loading — see §4) was the easy, well-documented part.
The next phase — actually reading Dear ImGui's menu text out of the game's
memory — is genuine reverse engineering with no shortcuts, because:

- The game has **no shipped debug symbols** (only a leftover PDB *path*
  string, not the PDB itself), so we can't just look up
  "ImGui::Selectable" by name in the binary.
- ImGui is **statically compiled into the exe**, not a separate DLL, so we
  can't hook it the easy way (import-table/IAT hooking). We have to find
  the actual machine code of the relevant functions in memory and detour
  them, or find the single global `GImGui` context pointer and read its
  fields directly using our own copy of the (public, open-source) ImGui
  1.89.8 struct layouts.
- Finding either of those requires either (a) attaching a debugger/dynamic
  instrumentation tool to the running game and hunting for known
  byte-patterns or string cross-references, or (b) static analysis of the
  exe on disk with a disassembler. This is inherently trial-and-error —
  expect a number of dead ends before something reliable is found.

Planned tooling for this phase: **Frida** (scriptable dynamic
instrumentation — can attach to the running game process, scan memory for
byte patterns, and hook arbitrary addresses, all from a script rather than
a manual debugger GUI), plus MinHook (lightweight C hooking library) inside
our proxy DLL once we know what to hook. Next concrete steps once you're
ready to continue:
1. Add a D3D11/D3D12 `Present`-call hook to our proxy DLL (standard
   technique, gives us a callback synced to every rendered frame —
   needed regardless of how we end up reading ImGui state).
2. Use Frida to search the running process for the ImGui context /
   relevant function signatures.
3. Once found, read+log the focused menu item's text every frame it
   changes (the milestone-1 log-file proof of concept described above).

---

## 3. Decisions (2026-07-04)

- **Load method:** proxy DLL sitting next to `mk_legacy_kollection.exe`,
  piggybacking on a DLL the game already loads at startup, so it loads
  automatically on every normal Steam launch — no manual injection step.
- **Dev environment:** user has no C++ toolchain installed yet. Plan must
  include setting up a build environment (Visual Studio Build
  Tools/Community + CMake) from scratch before any code can be compiled.
- **Scope:** everything pre-game — main menu, game/mode select, extras/
  bonus vault, options & settings, credits, any profile/store prompts.
  Everything up until a PS1 game actually boots inside the emulator core.

---

## 4. Task log

- [x] 2026-07-04 — Surveyed game folder structure, identified launcher exe
      vs. emulator/PS1-image files, confirmed scope boundary.
- [x] 2026-07-04 — Identified UI toolkit (Dear ImGui 1.89.8), renderer
      (D3D11/D3D12), no existing accessibility hooks, no anti-cheat/DRM.
- [x] 2026-07-04 — Discussed plan with user, settled load method / dev
      environment / scope decisions (see §3).
- [x] 2026-07-04 — C++ build environment confirmed working: MSVC compiler
      (cl.exe 19.44, VS 2022 Build Tools, VCTools workload) was already
      present at `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools`;
      CMake 4.3.4 installed fresh via winget to
      `C:\Program Files\CMake\bin`. New terminal sessions will pick up
      `cmake` on PATH automatically.
- [x] 2026-07-04 — Confirmed load-mechanism target: game directly imports
      `DINPUT8.dll` (small, 6-export surface: `DirectInput8Create`,
      `DllCanUnloadNow`, `DllGetClassObject`, `DllRegisterServer`,
      `DllUnregisterServer`, `GetdfDIJoystick`) — the standard proxy-DLL
      technique (same one ReShade uses) applies cleanly here.
- [x] 2026-07-04 — Built `proxy_dll/` (CMake + MSVC) milestone-0 proof of
      concept: a `dinput8.dll` that on load resolves the real system DLL
      (expected alongside it as `dinput8_orig.dll`), re-exports thin
      pass-through stubs for all 6 functions so input is unaffected, and
      writes one line to `mk_accessibility.log` next to itself to prove it
      loaded. Note: MSVC's `.def`-file cross-DLL export forwarding does
      **not** work as commonly documented (`LNK2001` even with correct
      syntax) — had to hand-write forwarding stub functions instead, and
      `DllCanUnloadNow`/`DllGetClassObject` needed a
      `#pragma comment(linker, "/export:Name=InternalName")` workaround
      because `<combaseapi.h>` pre-declares those two names and directly
      redefining them under `__declspec(dllexport)` errors as a linkage
      conflict. All 6 exports verified present via `dumpbin /exports` on
      the built DLL.
      Built artifact: `proxy_dll/build/dinput8.dll` (not yet copied into
      the game folder — that's the next step, pending confirmation).
- [x] 2026-07-04 — Deployed milestone-0 proxy DLL into the live game
      folder: `dinput8_orig.dll` (renamed copy of the real
      `C:\Windows\System32\dinput8.dll`) and `dinput8.dll` (our proxy)
      both copied into `Mortal Kombat Legacy Kollection\`.
- [x] 2026-07-04 — **User launched the game normally via Steam — CONFIRMED
      WORKING.** `mk_accessibility.log` appeared with:
      `"mk_accessibility proxy dinput8.dll loaded into host process; real
      dinput8_orig.dll resolved."` This proves the injection/auto-load
      mechanism works end-to-end with zero manual steps. (User expected
      NVDA to speak at this point — clarified that milestone 0 is a pure
      load-mechanism test with no text-reading or NVDA output yet; that's
      milestones 1–2 below.)
- [x] 2026-07-04 — Installed Frida 17.15.3 + frida-tools via pip (Python
      3.12 already present on the machine). Will be used to attach to the
      running game and hunt for Dear ImGui's internal state in memory
      (scripted, no manual debugger GUI needed). CLI tools land in
      `...\LocalCache\local-packages\Python312\Scripts` (not on PATH by
      default — invoke by full path or add to PATH later for convenience).
- [x] 2026-07-04 — Added D3D11/D3D12 `Present` hook to proxy DLL: vendored
      MinHook (github.com/TsudaKageyu/minhook) into `proxy_dll/third_party/`,
      built as a static lib via CMake subdirectory. `present_hook.cpp`
      creates a throwaway D3D11 device+swapchain to read the real
      `IDXGISwapChain::Present` vtable slot (index 8, shared by DXGI
      regardless of D3D11 vs D3D12 backend), hooks it with MinHook, and
      logs "first frame observed" + every 600th frame. Also refactored
      logging into shared `log.h`/`log.cpp`, and moved DLL init work out
      of `DllMain` into a background thread (`InitThread`) since creating
      a D3D11 device under the loader lock risks deadlock.
      Deployed to game folder, awaiting user to launch + report back
      whether `mk_accessibility.log` shows the Present-hook lines.
- [x] 2026-07-04 — **User ran the game for ~90 seconds — CONFIRMED
      WORKING.** Log shows `"Present hook: installed successfully"`,
      `"first frame observed"`, then a steady frame counter incrementing
      by 600 every ~10 seconds (i.e. a rock-solid 60 FPS) for the whole
      session, with no crash and normal gameplay. We now have a reliable
      per-frame callback inside the game's render loop to build on.
- [~] 2026-07-04 — **In progress / not yet successful: locating ImGui's
      `GImGui` context in memory via Frida.** Extensive attempts so far:
      - Found that launching the exe directly (bypassing Steam's own launch
        wrapper) causes the game to auto-exit after roughly 5–15 minutes —
        workable for testing (just relaunch), but means each Frida session
        has a limited window.
      - **Signature-scan approach (find the tiny `mov rax,[rip+X]; ret]`
        body of `ImGui::GetCurrentContext()`)**: found 29 byte-pattern
        candidates in `.text`, zero validated. Likely inlined away entirely
        under `/O2` (no shipped PDB to confirm either way).
      - **Brute-force pointer scan** of the exe's own writable `.data`
        for any QWORD pointing at a validated `ImGuiIO::DisplaySize` +
        plausible `FrameCount`: 0/1,050,624 candidates matched.
      - **Key discovery**: the game's real DXGI swapchain buffer is
        **1280×720**, not the window's 1920×1080 client rect — Windows is
        upscaling via ~150% display scaling. Confirmed directly from our
        own Present hook's `IDXGISwapChain::GetDesc()` (ground truth, not
        a guess). All earlier scans had been searching for the wrong
        DisplaySize value.
      - **Branch mismatch discovery**: computed exact `ImGuiContext`
        offsets from real ImGui headers for both the mainline v1.89.8 tag
        and the separate **v1.89.8-docking** tag (docking adds viewport
        support and changes struct size: 24168 vs 24712 bytes,
        `FrameCount` at +15920 vs +16240). Neither offset validated any
        candidate.
      - **Direct byte-pattern search for `1280.0f,720.0f`** across private
        heap memory (correct resolution this time): only 9 raw matches
        (much more specific than the 58-74 false hits under the wrong
        1920×1080 pattern) — promising, but empirical validation (search
        each candidate's surrounding ~30KB for an int matching our own
        ground-truth frame counter from the Present hook log) found:
        - One candidate with a plausible-ish nearby value (12659 vs true
          ~13000) but at a structurally implausible offset (-24 bytes,
          whereas real `ImGuiContext.FrameCount` should be ~15900+ bytes
          *after* `IO.DisplaySize` in either branch) — likely a
          coincidental match against some other small engine struct that
          happens to store a frame index next to a resolution pair, not
          the true ImGui context.
        - Several other candidates showed the *same* repeating pair of
          unrelated values (12032/14080) at many different offsets,
          strongly suggesting those particular "1280×720" hits are just
          a **design-reference resolution reused throughout the game's
          own UI/layout data** (common technique: define button/panel
          positions at a canonical reference resolution, then scale to
          actual screen size) — i.e. false positives unrelated to ImGui's
          live runtime state.
      - Checked whether the game-hacking community has already solved
        this: found only Cheat Engine tables for the *emulated PS1 games'*
        memory (health, etc. — via FearLess Revolution), nothing for the
        launcher's own front-end/ImGui state. No shortcut available there.
      - **Bottom line so far**: the render-loop hook (Present) is rock
        solid, but pinpointing the exact `ImGuiContext` in memory purely
        by pattern/heuristic scanning has not yet succeeded. This is a
        harder reverse-engineering problem than initially hoped.
      - User chose to try heavier static analysis next (rather than the
        OCR fallback) — switched tools from blind runtime scanning
        (Frida) to static disassembly (radare2), to trace forward from
        the embedded ImGui version string to the real `GImGui` global.
      - **radare2 setup**: no radare2/Ghidra available via winget; used
        `gh release download` to pull `radare2-6.1.8-w64.zip` directly
        from `radareorg/radare2` on GitHub (winget's own package search
        was rate-limiting/empty), extracted to
        `MK-Legacy-Kollection-Accessibility/tools/radare2-6.1.8-w64/`.
        Confirmed working (`radare2.exe -v`).
      - Found the exact version string location: `"Dear ImGui 1.89.8
        (18980)"` lives at virtual address **0x140c48b10** in
        `mk_legacy_kollection.exe` (via `iz~ImGui`).
      - Ran full auto-analysis (`aaa`) on the 14MB exe (takes several
        minutes) then tried `axt 0x140c48b10` (cross-reference lookup) —
        **zero xrefs found**, even after the full analysis pass
        (`aa`→`aac`→`aar`→`avrr`→`aaft`→`aanr`). This means r2's own
        auto-discovered code coverage never reached whatever function
        loads that string's address, OR the compiler didn't emit a
        classic pattern (`lea reg,[rip+X]`) at that reference — needs
        the more brute-force raw byte/pointer search (`/r <addr>`,
        which scans for *any* addressing form pointing at that address,
        independent of prior analysis coverage) instead of relying on
        `axt`'s analysis-database lookup.
      - Hit the same MSYS/Git-Bash path-mangling gotcha we saw earlier
        with `dumpbin /imports` — any argument starting with `/` (like
        the r2 search command `/r 0x140c48b10`) gets silently rewritten
        into a Windows path by Git Bash, producing a confusing
        `"Invalid `:` subcommand"` error that has nothing to do with r2
        itself. Fix is `MSYS_NO_PATHCONV=1` prefixed on the command (as
        already used successfully for dumpbin earlier in this project).
      - **Paused here at user's request, mid-retry of the `/r` search
        with the path-conversion fix applied but not yet run.**

### Resume-here checklist for next session
1. Re-run (with the MSYS fix):
   `MSYS_NO_PATHCONV=1 "<repo>/tools/radare2-6.1.8-w64/bin/radare2.exe" -q -e bin.relocs.apply=true -c "/r 0x140c48b10" "<game dir>/mk_legacy_kollection.exe"`
   (drop the earlier `-e bin.relocs.apply=true`/`aaa` step first if this alone is fast enough — `/r` is a raw scan and doesn't need analysis to have run first).
2. That should surface the address(es) of instructions referencing the
   version string. Disassemble the containing function
   (`pdf @ <addr>`) to find the call to `ImGui::CreateContext()`
   nearby and trace where its return value (in `rax`) gets stored to a
   fixed global (`mov [rip+X], rax` pattern) — that target address
   (module base + rip-relative offset) is the real `GImGui` global.
3. Convert that RVA to a live address in Frida (`moduleBase + RVA`) and
   validate the same way as before (dereference, check
   `IO.DisplaySize` == 1280x720 and `FrameCount` advances over time).
4. If `/r` also comes up empty, next fallback is Ghidra (better auto-
   analysis and an actual decompiler), or manually walking from
   `ImGui::NewFrame`/`ImGui::Render` call sites instead of the version
   string.
5. If static analysis stalls too, the OCR-based fallback (screenshot the
   focused-item region, OCR, speak) remains available as a less
   elegant but more guaranteed-to-work option — see §2.

### Session paused (2026-07-04), then resumed same day

User decided to switch to the **OCR-based approach** (§2's fallback)
rather than continue the memory-forensics/static-analysis path. This is
a significant simplification: OCR requires **no code injection into the
game at all** — it's a fully external tool that captures the game
window's pixels and reads text out of the image, so the entire
`proxy_dll` C++/MinHook/radare2 effort becomes optional going forward
(kept as a possible precision upgrade later, not a dependency). New
project subfolder: `ocr_reader/` (Python-based).

- [x] 2026-07-04 — **NVDA speech pipeline confirmed working end-to-end,
      independent of everything else.** Downloaded the official NVDA
      Controller Client SDK (matching the installed NVDA 2026.1.1)
      directly from `download.nvaccess.org/releases/stable/` (GitHub
      releases only ship the installer, not the controller client zip —
      had to get it from NV Access's own download server instead).
      Extracted to `ocr_reader/nvda_controller_client/`; using the
      `x64/nvdaControllerClient.dll`. Wrote
      `ocr_reader/test_nvda_speech.py` (simple ctypes wrapper per NV
      Access's own `example_python.py`) calling
      `nvdaController_testIfRunning()` then `nvdaController_speakText()`.
      **User confirmed they heard NVDA speak the test message.** This is
      the easy half of the OCR approach — reliable and done. The
      remaining work is entirely about capturing the window and reading
      text out of it accurately.

### Resume-here checklist for the OCR approach
1. Window capture: use `PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)`
   (not plain `BitBlt`, which typically produces a black image for
   GPU/DirectX-rendered windows) to grab the game's client area as a
   bitmap. Need the game's HWND (findable by process name/title, same
   technique used in the earlier Frida scripts' `EnumWindows` helper,
   but this time from plain Python via `pywin32`/`ctypes` — no Frida
   needed).
2. OCR: use Windows' own built-in OCR engine (`Windows.Media.Ocr` WinRT
   API, via the `winsdk` pip package) rather than installing a separate
   Tesseract binary — avoids an extra dependency and reads UI-style text
   reasonably well. Returns per-word bounding boxes, which we'll need
   later for focus-region detection.
3. First proof of concept: capture + OCR once, print recognized text to
   console, and visually confirm it matches what's actually on screen in
   the real menu.
4. Then build the polling loop: capture + OCR every ~300-500ms, diff
   against the previous OCR result, and speak newly-appeared/changed
   text via the now-working NVDA pipeline.
5. Harder/later problem: identifying *which* item is currently
   highlighted/focused (vs. reading the whole screen every time) —
   likely via color-based heuristics (ImGui highlight bars are usually a
   distinct accent color) on the captured bitmap, cropping to just that
   region before OCR. Until that's built, the simpler "read everything
   that changed" behavor is the working fallback.
- [x] 2026-07-04 — **Window capture confirmed working.** `PrintWindow`
      with `PW_RENDERFULLCONTENT` (not plain `BitBlt`, which would give a
      black image for this DirectX-rendered window) correctly captures
      the game's main menu at its true 1280×720 render resolution.
      Verified visually (`capture_test.py` → `capture_test_output.png`):
      clean image showing "PLAY", "OFFLINE", "QUICK MATCH".
- [x] 2026-07-04 — **OCR confirmed working** using Windows' built-in
      `Windows.Media.Ocr` engine via the `winsdk` pip package (no
      Tesseract/extra binary needed). `ocr_test.py` correctly read
      "PLAY", "OFFLINE", "MATCH" with bounding boxes. Note: missed the
      word "QUICK" specifically — inspected the crop and it's a very
      tightly-kerned stylized display font where letters nearly touch;
      tried 2x upscaling as a fix but that instead introduced garbage
      characters from a nearby decorative icon glyph, so kept scale=1.0.
      **Known accuracy limitation**: stylized/tightly-kerned game-UI
      fonts won't always OCR perfectly — accepted as a v0 limitation,
      not blocking.
- [x] 2026-07-04 — **Built and successfully tested the full
      capture→OCR→speak loop** (`ocr_reader/main.py`). Finds the game
      window by process name, polls every 0.5s, OCRs each capture,
      and speaks via the NVDA controller client whenever the detected
      text changes from the previous poll. Also wired an F9 hotkey
      (checked via `GetAsyncKeyState`, no extra hotkey library needed)
      to force a manual re-read of the current screen on demand.
      **User confirmed hearing NVDA say "PLAY. OFFLINE. MATCH."** during
      a live 15-second test run against the real running game — the
      whole pipeline works end to end.
- [x] 2026-07-04 — Hardened the polling loop against false triggers:
      new OCR content must appear identically on 2 consecutive polls
      (~1s) before being spoken, so transient OCR noise (animated
      backgrounds/glow effects) doesn't cause repeated announcements.
      Re-tested live — still reliably speaks the menu, with the expected
      ~1s added settle delay.
- [x] 2026-07-05 — **Solved highlight/focus-region detection for
      list-style menus via color.** Had the user freely navigate the
      real menu while a capture script recorded a sequence of frames
      (`capture_sequence.py`); found a clean example on the per-game
      submenu list (PLAY GAME / VERSUS / TRAINING / FATALITY TRAINING /
      CONTROLS / FLYERS): the currently-selected item is rendered in a
      distinct cyan/blue with a glow underline, unselected items in
      gold/yellow. Sampled exact pixel colors to confirm:
      - Unselected (gold): mean RGB ≈ (240, 212, 126) — R > G > B
      - Selected (cyan): mean RGB ≈ (105, 200, 230) — B > G > R
      A simple **"mean blue channel exceeds mean red channel by >30,
      among sufficiently bright pixels"** test cleanly separates the two
      with a wide margin. Implemented in `main.py`:
      `ocr_image()` now returns each line's full bounding box (not just
      text); `is_line_highlighted()`/`find_highlighted_text()` sample
      pixel colors within each line's box (+4px padding for the glow)
      to identify the selected item. Verified correct against the saved
      frames (`sequence/frame_000.png`, `frame_027.png`) — both
      correctly identified "FATALITY-TRAINING" as highlighted (OCR adds
      a stray hyphen from the underline glow — cosmetic, TTS reads fine).
      Rewired the main loop to track **two independent signals**:
      screen-level text changes (existing behavior, reads the whole
      screen) and highlight changes *within* an unchanged screen (speaks
      just the newly-highlighted item's text, debounced the same way).
- [x] 2026-07-05 — Fixed a pywin32 gotcha hit while building the capture
      sequence tool: `win32gui.EnumWindows`'s callback raises a spurious
      `pywintypes.error: (18, 'EnumWindows', 'There are no more files.')`
      when the callback returns `False` to stop enumeration early on
      some pywin32 versions. Fixed by always returning `True` (never
      stopping early, just skipping once already found) and wrapping the
      call in `try/except` as a defensive backstop. Fixed in both
      `capture_test.py` and `main.py`.
- [x] 2026-07-05 — **Safety note from live testing**: sending synthetic
      keyboard input to test navigation (`keybd_event`) once
      unexpectedly opened a **"Quit Game?" confirmation dialog** after
      pressing Enter — the game maps Enter to something like a
      Start/pause action rather than menu-confirm, likely because it
      expects gamepad input primarily (user confirmed they play with a
      gamepad/controller, not keyboard). Safely cancelled with Escape,
      no harm done, but **do not send synthetic Enter key presses to
      this game** in future testing — stick to observing real user
      navigation instead (which is what we switched to).
- [x] 2026-07-05 — **Known gap found live**: the "Game Library" tab bar
      (ALL / ARCADE / CONSOLE, navigated via horizontal tabs rather than
      a vertical list) does **not** use the cyan/gold color scheme —
      all tabs render in the same off-white color regardless of
      selection state, confirmed by both live testing (no highlight
      announcement occurred while the user was on that screen) and by
      visually inspecting a capture (all three tabs look identical).
      This UI style needs separate handling (likely a different visual
      signal — subtle background shading, or the small diamond marker
      between tabs might track position — not yet investigated) or
      just relies on the F9 manual re-read fallback for now.

### Current status / how to run it yourself
1. Make sure NVDA is running and the game is running.
2. Open a terminal in `ocr_reader/` and run: `python main.py`
3. Navigate the game's menus normally:
   - Moving to a **different screen** (e.g. main menu → a submenu):
     NVDA speaks the whole new screen's text, ~1s after it settles.
   - Moving the **cursor within a list-style menu** (confirmed working
     on per-game submenus like PLAY GAME/VERSUS/TRAINING/...): NVDA
     speaks just the newly-highlighted item, ~1s after it settles.
   - On **tab-bar style screens** (e.g. Game Library's ALL/ARCADE/
     CONSOLE filter): only the initial screen-level read happens;
     moving between tabs is currently silent (known gap, see above).
4. Press **F9** any time to force an immediate re-read of whatever's
   currently on screen — useful as a fallback wherever highlight
   detection doesn't apply yet (tab bars, dialogs, etc.).
5. Ctrl+C in the terminal to stop the reader. It doesn't need to be
   running before the game launches or closed after — it finds the
   window whenever it appears and just waits if the game isn't open.

## What's solid vs. what's next
Window capture, OCR, NVDA speech, screen-change detection, and
list-style highlight detection are all done and verified (screen-change
detection live end-to-end; highlight detection verified against real
captured data with exact color calibration — live confirmation on that
exact list was skipped since the static validation was already
conclusive and re-navigating there took the user through a controller
control scheme that wasn't behaving as expected). Nothing here depends
on the earlier `proxy_dll`/Frida/radare2 work — that remains untouched
on disk if a future session wants to revisit the higher-precision
approach instead, but isn't required for this OCR path to work.

**Next steps, roughly in priority order:**
1. ~~Handle tab-bar style selectors~~ — done, see below.
2. Broader testing across the rest of the menu tree (options, extras,
   credits, confirmation dialogs) to catch other UI styles/edge cases.
3. Packaging/launch convenience so the reader starts automatically
   alongside the game (small launcher script or similar) rather than
   needing a manual `python main.py` each session.

- [x] 2026-07-05 — **Tab-bar selectors (Game Library ALL/ARCADE/CONSOLE)
      confirmed already working — correcting the earlier "known gap" note
      above.** Captured a fresh frame sequence
      (`ocr_reader/sequence_tabbar/`) navigating the tab bar and found it
      **does** use the same cyan/gold highlight scheme as list menus
      (contrary to the 2026-07-05 note claiming all tabs render
      off-white) — the earlier live test likely just didn't have the
      cursor actually move across tabs, or the reader wasn't running
      yet. Verified two ways:
      1. Offline replay: ran `ocr_image()` + `find_highlighted_text()`
         against all 22 captured frames — Windows OCR splits "ALL",
         "ARCADE", "CONSOLE" into three separate line results (not
         merged into one row), so the existing per-line color check
         tracked the true selection correctly across every transition
         (CONSOLE -> ALL -> ARCADE).
      2. Live test: ran `main.py` against the real running game, user
         navigated ALL -> ARCADE -> CONSOLE and **confirmed NVDA
         announced all three correctly**.
      **No code changes were needed** — `main.py`'s existing
      color-highlight heuristic already generalizes to this screen.
      Minor supporting change: `capture_sequence.py` now takes an
      optional 3rd arg for output directory, so new calibration
      captures don't overwrite the earlier verified `sequence/` frames.

- [x] 2026-07-05 — Attempted a broader live test (2-minute session,
      user asked to freely explore Options/Extras/Credits). Result: user
      reported hearing little/nothing new. Checked the actual screen
      afterward and found the user had ended up **inside actual PS1
      gameplay** (a rainy in-game scene, likely Mortal Kombat
      Mythologies: Sub-Zero) — they had selected "PLAY GAME" from the
      per-game submenu, which launched the emulated title itself. This
      is expected/correct behavior: gameplay inside the emulated PS1
      games is explicitly **out of scope** for this project (per the
      original ask — only the launcher's own menus need to be
      accessible), so of course there was no menu text for the reader to
      announce there. Confirms the scope boundary holds up in practice;
      next broader-testing attempt should stick to the launcher's own
      menu screens (Options, Extras, Credits, back out before pressing
      anything that would start actual gameplay).

- [x] 2026-07-05 — **Built the auto-start/packaging convenience layer**,
      chosen over a Windows-login startup shortcut since it ties the
      reader's lifetime to actually launching the game rather than
      running all the time:
      - `ocr_reader/run_reader.bat` — runs `main.py` with the concrete
        Python 3.12 path (not the WindowsApps alias, to avoid alias-
        resolution issues outside an interactive shell) and `-u`
        (unbuffered) so `reader_log.txt` updates live instead of sitting
        in a stdout buffer.
      - `ocr_reader/start_reader.vbs` — meant to be wired into the
        **Steam launch options** as:
        `wscript.exe "<full path>\ocr_reader\start_reader.vbs" & %command%`
        (Steam launch options are passed through `cmd.exe` on Windows,
        so `&` chaining works — this is a widely-used community
        pattern). Before launching, queries WMI for any existing
        `python.exe` whose command line already contains
        `ocr_reader...main.py`, and skips starting a second copy if
        found — so relaunching the game after a crash doesn't stack
        duplicate reader instances. Runs `run_reader.bat` hidden (no
        console window).
      - `main.py` — added an auto-exit: once the game window has been
        found at least once, if it then goes missing for more than
        `EXIT_AFTER_WINDOW_GONE_SECONDS` (120s), the process exits on
        its own. Needed because headless/no-console mode has no
        Ctrl+C — otherwise it'd run forever after you quit the game.
        (Before the window is ever found, it still waits indefinitely,
        same as before — covers the game taking a while to start up
        after Steam launch.)
      - **Not yet live-tested**: manually ran `start_reader.vbs` from
        this session's sandboxed shell as a smoke test, but that shell
        turned out to run in a Windows *service* session (Session 0),
        not the normal interactive desktop session Steam/the game runs
        in — so the spawned `python.exe` landed somewhere it could
        never find the game window, WMI reported a blank command line
        for it (session-boundary effect), and it couldn't even be
        killed from that shell (access denied). This means the
        "already running" dedup check and the hidden-window behavior
        are implemented but **not yet validated against a real Steam
        launch** — that's the next step.

### Resume-here checklist for auto-start
1. Set Steam launch options for the game (right-click in Steam library
   → Properties → General → Launch Options) to:
   `wscript.exe "F:\SteamLibrary\steamapps\common\MK-Legacy-Kollection-Accessibility\ocr_reader\start_reader.vbs" & %command%`
2. Launch the game normally from Steam. Check
   `ocr_reader\reader_log.txt` appears/updates, and confirm NVDA speaks
   the main menu shortly after it loads — no manual `python main.py`
   needed.
3. Quit the game, wait ~2 minutes, then check Task Manager to confirm
   the `python.exe` reader process exited on its own (validates the
   `EXIT_AFTER_WINDOW_GONE_SECONDS` logic).
4. Relaunch the game again while a reader instance might still be
   winding down, to sanity-check the "already running" dedup doesn't
   either miss a stale instance or wrongly block a legitimate new one.
5. If `wscript`/VBScript is blocked by any security software, the
   fallback is to point Steam's launch options directly at
   `run_reader.bat` instead (loses the dedup check and hidden window,
   but is simpler): `"...\ocr_reader\run_reader.bat" & %command%`
   (accepting a briefly-visible console window as a tradeoff).

- [x] 2026-07-05 — **Added a "known screens" capture tool** (F10 hotkey
      in `main.py`) since the launcher's menus of interest are static —
      worth building a one-time reference library of screenshot + OCR
      text per screen, rather than only ever reading them live.
      Press **F10** while on any screen: saves the current frame to
      `ocr_reader/known_screens/<slug>.png` plus a matching `.json`
      (OCR'd line text + bounding boxes + whichever line was detected as
      highlighted), named from the screen's own recognized text (e.g.
      `play_offline_quick_match.png`), with a numeric suffix if that
      name's already taken. Speaks "Captured: <name>" as confirmation
      since there's no terminal to watch during normal play. Syntax/
      unit-tested the slug function only (`slugify` on sample strings) —
      not live-tested against the real game yet, since that requires
      navigating the actual menus.
      **Next step**: navigate to each static menu of interest (main
      menu, per-game submenu, Game Library tabs, Options, Extras,
      Credits, any confirmation dialogs) and press F10 once at each,
      then report back so the results in `known_screens/` can be
      reviewed for OCR accuracy.

- [x] 2026-07-05 — **User completed the launcher F10 capture pass**
      (files now in `ocr_reader/known_screens/`, not yet individually
      reviewed for OCR accuracy in this session).

- [~] 2026-07-05 — **Scope expanded to the 3 emulated games' own menus**
      (see updated goal statement above). User initially asked to source
      screenshots from the web for all games' menus rather than live-
      capturing them. Built `ocr_reader/capture_web_reference.py` (OCRs
      an arbitrary local image file via the same pipeline as `main.py`
      and saves it into `known_screens/` as `<game_slug>__<ocr_slug>.png`
      /`.json`, tagged `"source": "web"`, `"verified_against_live_game":
      false`, plus the source URL) to support this.
      **Web-sourcing results, after extensive searching**
      (MobyGames, Fandom, Spriters-Resource, uvlist.net, psxdatacenter,
      IGN, Atari's own product page, mksecrets.net, multiple review
      sites):
      - **One clean win**: Mortal Kombat Mythologies: Sub-Zero's main
        menu, sourced from the Mortal Kombat Wiki (Fandom) — cross-
        checked against archive.org's `psx_subzero` listing to confirm
        it's the same SLUS-00476 USA release used in this Kollection.
        OCR correctly read "START" / "OPTIONS" / "X - SELECT" (missed
        the stylized logo text itself — same kind of kerning miss seen
        on the launcher). Saved as
        `known_screens/mythologies__start_options_x_select.png`/`.json`.
      - **Trilogy character-select screens** (the most commonly
        screenshotted images online) turned out to have **no visible
        text at all** in most versions found — just portrait icons; the
        fighter's name only appears on-screen once actually highlighted
        during live navigation. So even where an image was gettable, it
        often wasn't useful for OCR.
      - **Special Forces** has almost no public menu screenshots at all
        — nearly everything findable is cutscene/gameplay stills.
      - **MobyGames blocks scraping outright** (403 on every gallery
        page, both via `WebFetch` and Exa's fetch tool).
      - **Fandom/Spriters-Resource galleries are JS-rendered** in a way
        that strips real `<img>` URLs from both fetch tools available
        (they return markdown with the surrounding text/captions but no
        image src). Worked around this once via Fandom's public
        MediaWiki `api.php` (`action=query&prop=imageinfo&iiprop=url`),
        which returns real static-CDN URLs — but that's a one-file-at-
        a-time workaround, not a way to browse a gallery.
      - The Claude-in-Chrome browser extension was not connected in
        this session, so a visual approach (would likely have unlocked
        MobyGames thumbnails and full Spriters-Resource sprite sheets)
        wasn't available either.
      - **User's decision**: given the low yield, switch to the
        already-recommended **live F10 capture** approach for the
        remaining games rather than continuing to grind web sources.

### Resume-here checklist for the games' own menus
1. Launch each game from the launcher (with the reader running, same as
   any other session) and navigate its **menus only** — title/main menu,
   options, password/save screen, pause menu if one exists. Do **not**
   proceed into actual fights/levels (still out of scope) — back out
   once a menu's been captured.
2. Press **F10** on each distinct menu screen, same as the launcher
   capture pass. Since these are a different resolution/rendering style
   than the ImGui launcher (original PS1-era graphics), keep an eye out
   for whether the cyan/gold highlight-color heuristic (calibrated only
   against the launcher's own UI skin) produces any false highlight
   detections here — it's untested against this content and may need
   its own per-game calibration later if it misbehaves.
3. Trilogy specifically: since the character-select screen shows no
   names until a fighter is highlighted, F10 alone on that screen may
   capture little useful text — worth checking the saved OCR result and
   flagging if a different approach (e.g. reading whichever name
   appears when highlighted, like the launcher's list-menu handling)
   is needed there instead.
4. Report back which screens got captured so results in
   `known_screens/` can be reviewed together (web-sourced Mythologies
   entry plus whatever's newly captured live).

- [~] 2026-07-05 — **Scope expanded again: the full ~23-game/platform
      roster, not just the 3 PS1 games.** User confirmed (by checking
      the launcher's own Game Library ARCADE/CONSOLE tabs live) that
      this installed copy really does contain the full Digital Eclipse
      "Legacy Kollection" lineup — MK1, MK2, MK3, Ultimate MK3 (arcade,
      + SNES etc.), MK4, MK Advance/Deadly Alliance/Tournament Edition
      (GBA), plus the 3 PS1 games already covered. A disk/string-level
      check of the install folder found no separate arcade/SNES/GBA
      core files or ROMs (only the `pancake` PS1 core) — those other
      cores/ROMs must be embedded inside the 12GB `assets.pie` blob
      and/or statically linked into `mk_legacy_kollection.exe`, invisible
      to a surface-level file scan. **Decisions**: cover one
      representative version per game (11 distinct games total, not all
      23 platform variants) - e.g. Arcade for MK1-4, PS1 for the 3
      spinoffs. Include hidden dev/test menus where reachable (Atari's
      own marketing for this Kollection advertises "buried developer
      menus").
      **Web-sourcing results for the arcade classics** (much higher
      yield than the PS1 spinoffs, as expected - these are far more
      documented):
      - **MK1** (arcade): title screen ("PRESS START" OCR'd correctly;
        the stylized "MORTAL KOMBAT"/"MIDWAY" logo text and copyright
        line did not OCR) and select screen ("CHOOSE YOUR FIGHTER" /
        "CREDITS: 0" - OCR badly mangled both, e.g. "CHOOSE youn
        FICHTE-R", "CREOiTS: O"). Saved as `mk1__press_start.png`/json
        and `mk1__choose_youn_fichte_r_creoits_o.png`/json.
      - **MK2** (arcade): title screen downloaded, but OCR came back
        completely blank on both the stylized logo and the plain
        copyright text underneath it - likely too low-res/blurry at
        this image's resolution. Saved as `mk2__blank_screen.png`/json
        (image is fine, just no OCR text extracted - worth re-trying
        live against the actual running game rather than this web
        image).
      - **MK4** (arcade): select screen downloaded ("SELECT YOUR
        FIGHTER" / "RANDOM" / "GROUP" / "HIDDEN" visible to the eye),
        but OCR came back blank here too. Saved as
        `mk4__blank_screen.png`/json.
      - **UMK3**: two real wins - the "Choose Your Destiny" difficulty-
        select screen and the arcade "Select Your Fighter" screen both
        OCR'd their header text correctly. Saved as
        `umk3__choose_your_destiny.png`/json and
        `umk3__select_your_fighter.png`/json.
      - **Confirmed pattern holds across all these games** (same as
        Trilogy): character-select screens show portraits only, no
        name labels, until a fighter is actually highlighted during
        live play - only the screen's header/footer text (e.g. "SELECT
        YOUR FIGHTER", "CREDITS: 0", "RANDOM/GROUP/HIDDEN") is present
        in a static capture.
      - **New finding, worth flagging clearly**: OCR accuracy on these
        classic games' fonts is noticeably worse and more inconsistent
        than either the modern launcher or Mythologies - blocky sans-
        serif headers ("SELECT YOUR FIGHTER", "CHOOSE YOUR DESTINY")
        read fine, but stylized/gradient logo-style text and some
        low-res captures failed outright or got mangled. Live capture
        against the actual running (sharper, non-recompressed) game
        window may do better than these compressed web screenshots -
        untested either way yet.
      - **MK3 (non-Ultimate arcade) and the 3 GBA titles**: user said to
        keep web-sourcing. Result: **MK3 has no cataloged title/select
        screenshot on the Fandom wiki at all** — its Gallery page only
        has cover-art thumbnails for its various console ports, no
        attract-mode/menu images. Since MK3 and UMK3 share the same
        engine/UI (UMK3 is a ROM-upgrade of MK3 - same "SELECT YOUR
        FIGHTER" header style, same "CHOOSE YOUR DESTINY" screen),
        treating the UMK3 captures above as a stand-in for MK3's menu
        style is reasonable, but it isn't a real MK3-specific capture.
        For the GBA titles: Mortal Kombat Advance has "Menu Screens" and
        "Introduction Screens" sprite-sheet rips on Spriters-Resource,
        and Deadly Alliance's own Fandom gallery mentions a "GBA version
        select screen" — but both are gated behind JS-rendered pages
        deep enough (Spriters-Resource's viewer; Deadly Alliance's
        gallery sections beyond what a single fetch reached) that
        extracting the actual image URL wasn't achieved before
        stopping. Mortal Kombat: Tournament Edition turned up nothing
        beyond ending/gameplay stills.
      User asked to keep trying rather than switch to live capture.
      Found a workaround for the JS-gated dead ends: **Fandom's
      `list=search` API with `srnamespace=6`** (searches File: page
      titles/text directly) surfaced image files that gallery-page
      scraping had missed - e.g. searching "GBA" found
      `File:MK-DA-Arcade-Screen-GBA.jpeg` (a Deadly Alliance VS-screen
      capture), and searching "Selection" found
      `File:Selection_Advance.PNG` and
      `File:Selection_Tournament_Edition.PNG` (both from the same 2007
      upload batch as the earlier MK4 select-screen file). Downloaded
      and OCR'd all three:
      - **MK Advance select screen**: portrait grid downloaded fine,
        but **no header text visible in this particular crop** (unlike
        the arcade games) and OCR came back blank.
      - **MK Tournament Edition select screen**: same - portrait grid
        only, OCR blank.
      - **MK Deadly Alliance (GBA)**: this turned out to be a **VS
        screen**, not a menu - clearly shows "KITANA VS. SONYA" and
        "THE SWAMP" to the eye, but **OCR still came back completely
        blank** despite the text being legible.
      **MK3 (non-Ultimate)**: no image found via this search technique
      either (searched "Mortal Kombat 3 title" in namespace 6 - only
      video/clip files matched, no stills).
      **Conclusion after this round**: the blank-OCR pattern is now
      consistent across MK2, MK4, and all 3 GBA titles - including a
      case (Deadly Alliance VS screen) where the text is clearly legible
      to a human but the OCR engine extracted nothing at all. This
      points at a real limitation of Windows' built-in OCR against
      these classic games' small/stylized/compressed fonts, not just a
      sourcing problem. **Stopping web-sourcing here.** Saved images
      with blank OCR results are kept in `known_screens/` (tagged
      `"source": "web"`) as a visual record, but they don't yet provide
      usable text - **live F10 capture against the actual sharp running
      game window is now the clearly-indicated next step** for MK3, MK
      Advance, Deadly Alliance, Tournament Edition, and re-tries of
      MK2/MK4, since it's untested whether OCR does better against a
      sharp native capture than these old compressed web screenshots.

- [x] 2026-07-05 — **User scoped down**: drop the GBA/handheld titles
      (MK Advance, MK: Deadly Alliance GBA, MK: Tournament Edition)
      entirely - not a concern going forward. Remaining target list for
      the "every game's menus" effort is now: **MK3** (via live capture,
      since web-sourcing found nothing at all for it), plus the
      already-agreed live-capture items from earlier in the session
      (Trilogy, Special Forces - both still outstanding, never actually
      done yet since the conversation detoured into the web-sourcing
      side-quest). MK1, MK2, MK4, UMK3, Mythologies are considered
      handled for now (MK2/MK4's web images have blank OCR - low
      priority re-capture candidates, not blocking).

### Resume-here checklist (current)
1. Launch **Mortal Kombat 3** (non-Ultimate, arcade version) from the
   Game Library, with the reader (`python main.py`) running. Navigate
   its title screen, character-select screen, and (if reachable as a
   player) the "Choose Your Destiny" difficulty screen and Kombat Kode
   entry at the VS screen - press **F10** on each. Same rule as always:
   don't proceed into an actual match/fight.
2. Do the same for **Mortal Kombat Trilogy** and **Mortal Kombat:
   Special Forces** (their own menus only - title, options, password/
   save, pause - gameplay itself stays out of scope).
3. Report back so the live captures can be compared against the
   web-sourced ones already in `known_screens/` - specifically worth
   checking whether OCR does better against the sharp live window than
   it did against the compressed web images (which repeatedly came back
   blank for MK2/MK4/the GBA titles).

- [x] 2026-07-05 — **Added spoken startup confirmations to `main.py`**,
      since the user (blind, relying entirely on NVDA) had no way to
      tell whether the reader had actually started or found the game -
      previously the only feedback was printed text in a terminal they
      can't see. Now speaks **"Accessibility reader ready."** right
      after connecting to NVDA, and **"Game window found."** the moment
      it detects the running game, in addition to the existing F9/F10
      spoken confirmations.
      **Path confusion, resolved**: `ocr_reader/` (and `run_reader.bat`/
      `start_reader.vbs`) live in this separate project folder
      (`MK-Legacy-Kollection-Accessibility`), not inside the actual game
      install folder (`Mortal Kombat Legacy Kollection`, which only has
      the game's own 13 files plus our deployed proxy `dinput8.dll` -
      confirmed by listing it directly, no `ocr_reader` there). User was
      looking in the game folder and understandably found nothing.
      Correct launch path is:
      `F:\SteamLibrary\steamapps\common\MK-Legacy-Kollection-Accessibility\ocr_reader\run_reader.bat`
      - not yet confirmed launched successfully as of this note.

---

## 5. Course correction (2026-07-06)

### 5.1 Diagnosis: what got miscommunicated

Restating the original ask, in the user's own words: source images from
well-known websites/public forums, OCR the menus out of them, and use
**some sort of hook that NVDA would recognize** to read the screens. The
intent was a **reference-library-driven** design: build a known-good bank
of screen → text mappings up front, then have the runtime tool recognize
which screen is currently showing and speak the pre-verified text for it.

What got built instead (§2–§4 above) is a **pure live-OCR loop**:
`main.py` re-runs Windows OCR on every 0.5s poll, unconditionally, and
speaks whatever it gets back that poll. The `known_screens/` folder (built
from both the F10 live-capture hotkey and the web-sourcing side quest) is
written to but **never read back at runtime** — it's an archive, not a
lookup table. There is no "hook" in the sense originally described; the
web-sourcing effort's OCR output was dead data as far as the running tool
is concerned.

This explains why several logged "failures" weren't really blockers: MK2/
MK4/GBA web images coming back with blank OCR only mattered if that OCR
result was going to be used live — it wasn't. Re-fighting stylized/classic
game fonts on every single poll (instead of solving each screen's text
once) was the wrong place to spend reliability effort.

**Additional discrepancy found while reviewing for this correction**: the
2026-07-05 entry claiming the user "completed the launcher F10 capture
pass" into `known_screens/` does not match what's on disk — there are
**zero launcher screens** in `known_screens/` today (only the 3 PS1 games'
+ arcade classics' entries). The launcher — the original primary target —
currently has no reference-library coverage at all. This needs to be
redone; see checklist below.

### 5.2 Revised architecture

1. **The reference library (`known_screens/`) becomes the runtime source
   of truth**, not a side archive. Each entry = one canonical screen:
   an image + hand-verified text + notes on what's dynamic (e.g.
   highlightable lists) vs. static.
2. **Text verification no longer depends on Windows OCR being right.**
   Claude (vision-capable) reviews each screenshot directly and writes the
   correct text once per screen — this permanently fixes the exact
   failures already logged (mangled arcade-font OCR, blank results on
   MK2/MK4/UMK3-style screens) instead of re-encountering them on every
   poll forever.
3. **The actual "hook"**: on each poll, compute a cheap perceptual-hash
   fingerprint of the captured frame and compare it against the library.
   - Match found → speak the stored `canonical_text` for that screen
     (plus live highlight-color detection for whichever item is currently
     selected, when the screen is a list/tab style — same cyan/gold
     heuristic as before, just now scoped to a known screen instead of
     driving everything).
   - No match → fall back to live OCR (today's behavior) as a best-effort
     read, and log the miss so it can be reviewed and folded into the
     library later (either as a genuinely new screen, or a sign the
     fingerprint threshold needs tuning).
4. Live F10 capture remains the acquisition method for screens with no
   usable web source (Trilogy, Special Forces, MK3) — unchanged — but
   every capture now gets a Claude-vision correction pass before being
   trusted, the same as the 8 entries corrected in §5.3.

### 5.3 known_screens/ JSON schema (revised)

Each entry now carries:
- `screen_id`, `game`, `screen_type` — identity/classification.
- `canonical_text` — ordered list of strings, **hand-verified**, this is
  what actually gets spoken on a library match.
- `notes` — free text on anything non-obvious (portraits-only screens,
  dynamic elements, likely-highlightable lists, etc.).
- `verified_by` / `verified_at` — provenance of the canonical text.
- `ocr_lines_raw` — the original OCR output kept for reference/debugging,
  not used for speech once `canonical_text` exists.
- (still to add, see checklist) a stored perceptual-hash fingerprint field
  once the matching module exists.

**Done 2026-07-06**: applied this schema and hand-corrected
`canonical_text` for all 8 in-scope existing entries by direct visual
inspection: `mk1__press_start`, `mk1__choose_your_fighter` (was
"CHOOSE youn FICHTE-R"/"CREOiTS: O" → corrected to "CHOOSE YOUR FIGHTER"/
"CREDITS: 0"), `mk2__title` (was blank → "MORTAL KOMBAT II" + copyright
line), `mk4__select_your_fighter` (was blank → "SELECT YOUR FIGHTER" +
"RANDOM"/"GROUP"/"HIDDEN"), `mythologies__main_menu` (added the logo title
missed by OCR), `umk3__choose_your_destiny` (added "MASTER" badge text),
`umk3__select_your_fighter` (confirmed as-is). The 3 GBA-title entries
(`mk_advance`, `mk_deadly_alliance`, `mk_tournament_edition`) were left
untouched — out of scope per the 2026-07-05 scope-down decision, kept on
disk only as a visual record.

### 5.4 Implementation done (2026-07-06)

- **`ocr_reader/screen_library.py`** — new module. `compute_dhash()`
  (16×16 difference-hash, 256-bit) + `ScreenLibrary` class that loads
  every `known_screens/*.json` with a non-empty `canonical_text`
  (entries without one — e.g. fresh F10 captures not yet reviewed — are
  silently skipped, not spoken) and exposes
  `match(frame) -> (entry, hamming_distance) | None` against a
  conservative distance threshold (24 out of 256 bits).
  **Validated** against the 7 corrected library entries: every entry
  self-matches at distance 0, and the closest *cross*-screen distance
  among them is 94 (mk2 title vs. Mythologies main menu) — a wide margin
  above the match threshold, so no false-positive risk between the
  screens currently in the library.
- **`ocr_reader/main.py`** rewired: each poll now calls
  `library.match(img)` first. A match speaks the entry's `canonical_text`
  and checks highlight state by sampling colors at the entry's *stored*
  bbox positions (`find_highlighted_text_from_entry` — reuses the
  existing color heuristic without needing fresh OCR at all, since
  highlight detection was always pixel-color sampling, never text
  recognition). No match falls back to the original live-OCR path
  unchanged, and additionally saves the frame + OCR text to
  `library_misses/` once the screen-change debounce fires, so misses
  accumulate for review instead of vanishing. F10 capture now writes
  `"canonical_text": null` explicitly, so a freshly captured screen is
  inert (never auto-spoken) until someone reviews the image and fills
  that field in — this is what keeps raw OCR out of the speech path
  going forward.
- Confirmed via `python -m py_compile` and a direct import that both
  modules load without error and the library populates (7 entries) — **not
  yet tested against the live running game**, see checklist below.

**Known open risk, not yet validatable without a live capture**: dHash
resizes the whole input frame to a fixed small grid, so it implicitly
assumes consistent framing between the library image and the live
capture. The library's web-sourced images are often tightly cropped to
just the menu; a live capture will be the full game window (whatever
letterboxing/border the emulator core renders). If live matches come back
as unexpected misses, this framing mismatch is the first thing to check —
fix would be cropping both to a consistent central region before hashing,
not raising the distance threshold (which would risk false positives
instead).

### 5.5 Session continued while user was away (2026-07-06)

User asked to keep building without live-game access (away at work).
Everything below was done using **already-captured frames already sitting
on disk** from earlier sessions' dev/testing (`sequence/`,
`sequence_tabbar/`, and loose root-level PNGs like `title_before.png`,
`enter_after.png`) — none of it required the game to be running.

- **Found and fixed a real bug in the matching design before it ever
  shipped**: the launcher's main menu renders a rotating/ambient
  background image behind the static PLAY/THE KRYPT/KOMBAT KARD text,
  unrelated to menu state. Measured it directly: 5 captures of the
  *identical* menu (different moments) hashed 39-66 bits apart at
  full-frame (out of 256) — comfortably *above* the 24-bit match
  threshold, meaning the matcher would have silently failed to recognize
  its own main menu almost every time. Fix: `screen_library.py` now
  supports an optional per-entry `"roi"` (`[x1,y1,x2,y2]`) that both
  storage and match-time hashing crop to first. Cropped to just the
  static left-hand text column, the same 5 captures dropped to 3-7 bits
  apart. Re-verified end to end after the fix: all 5 background variants,
  plus one frame each of the per-game submenu, tab bar, and quit dialog,
  now correctly match their true library entry (distances 0-12, all
  comfortably under threshold, all comfortably separated from each other
  - see the checked-in cross-distance test in this session's log).
- **Fixed a schema bug caught during this same work**: an early draft
  used a `"note"` field on `ocr_lines_raw` entries both to mean "this bbox
  is unsafe to sample" and to mean "here's provenance for a text
  correction" — which would have silently made real, live-selectable menu
  items (e.g. "KOMBAT KARD") permanently unannounceable as highlighted,
  since the highlight lookup treated *any* `note` as an exclusion signal.
  Split into two real fields: `skip_highlight` (only for decorative/
  logo/unconfirmed-bbox lines) and `ocr_original` (pure provenance, no
  behavioral effect). Applied consistently across every existing
  `known_screens/*.json`.
- **Built 4 new launcher library entries from recovered captures**
  (`screen_library.py`'s `roi` support made these possible - see each
  file's `roi_reason` for specifics):
  - `launcher__main_menu` (from `title_before.png`) - PLAY / THE KRYPT /
    KOMBAT KARD. **Known incomplete**: this particular capture cuts off
    at the window's 720px height right after KOMBAT KARD - there may be
    more items below (Extras/Options/Credits/Exit?) never captured. Needs
    a fresh, deliberate F10 pass to confirm the full list.
  - `launcher__game_library_tabs` (from `sequence_tabbar/frame_000.png`)
    - GAME LIBRARY header + ALL/ARCADE/CONSOLE, ROI'd to the header band
      so the box-art grid underneath (which legitimately varies by tab/
      scroll position) doesn't affect screen identity.
  - `launcher__quit_game_dialog` (from `enter_after.png`, the same frame
    from the original Enter-key safety incident) - "QUIT GAME?" +
    the confirmation body text. **Known incomplete**: cropped before any
    YES/NO button text, which likely exists below this capture's edge.
  - `launcher__mk1_game_library_submenu` (from `sequence/frame_000.png`)
    - GAME LIBRARY + PLAY GAME/VERSUS/TRAINING/FATALITY TRAINING/
      CONTROLS/FLYERS. **Known incomplete and unvalidated**: the right-
      side panel's game-description text is truncated mid-sentence by the
      1280px capture width, so it was deliberately left out of
      `canonical_text` (a broken sentence is worse than no sentence).
      Also unvalidated: whether this same 6-item list template is reused
      verbatim for every other game (if so, other games' submenus should
      still hash differently overall thanks to the differing right-panel
      art/text, but this has only been tested against this one capture -
      if MK2/MK4/etc. submenus get misidentified as this MK1 entry once
      live-tested, that's the first thing to check).
- Library is now **11 verified entries** (up from 7): re-ran the full
  cross-distance validation and every entry is still comfortably
  separated from every other same-ROI entry (all ≥94 bits) with no
  false-positive risk currently visible.

### Resume-here checklist (current)

1. **Live-test the rewired reader against the actual running game** —
   nothing above has touched a live game session yet; everything in §5.5
   was validated by replaying already-saved image files through the
   matcher directly, not by running the actual capture/NVDA loop. Run
   `main.py` for real and confirm: (a) library-matched screens speak the
   corrected `canonical_text` instead of raw OCR, (b) highlight tracking
   works via stored bboxes (no live OCR) for the Mythologies main menu
   (START/OPTIONS) and the Game Library tab bar (ALL/ARCADE/CONSOLE),
   (c) an unmatched screen still falls back to live OCR and shows up in
   `library_misses/`.
2. **Complete the launcher main menu and quit dialog entries** - both are
   flagged above as capturing an incomplete list/dialog (items likely
   exist below what was captured). F10 on the real main menu and the real
   quit dialog, scrolled/confirmed to see everything, then update those
   two JSON files' `canonical_text` and `ocr_lines_raw`.
3. **Re-capture the launcher's remaining screens via F10**: Options,
   Extras, Credits, per-game submenus for at least one more game (to
   validate the submenu-template question above), and any other
   confirmation dialogs - then Claude reviews and fills in
   `canonical_text` for each before it goes live, same as every entry
   so far.
4. Do the outstanding live captures (MK3, Trilogy, Special Forces menus —
   still never done, see §4's earlier checklist) using F10, then run the
   same Claude-vision correction pass on them before folding them into
   the library.

### 5.6 F10 captures went missing (2026-07-06 evening) — found and fixed a real bug

User ran `main.py` and pressed F10 across MK2/MK3/UMK3 arcade main menus and
several submenus. Terminal looked completely normal (no errors), but
**nothing showed up anywhere**: `known_screens/`, `library_misses/`, the
whole project tree (checked every file modified in the last 6 hours - zero
results), and Steam's own screenshot folder were all empty of anything new.

**Root cause found**: `is_key_pressed()` sampled `GetAsyncKeyState`'s
"currently held down" bit once per poll (~0.5-1.5s depending on whether
that poll also ran live OCR) and compared it to the *previous* poll's
sample to detect a fresh press. A real keyboard tap is often under 150ms -
comfortably short enough to start and end entirely between two polls and
never be seen at all. This isn't a rare edge case; it's a coin-flip (or
worse) every single press, which fully explains a 100% miss rate across
many attempts.

**Fix**: switched to `GetAsyncKeyState`'s *other* bit - the low-order bit
is a proper edge-triggered latch ("this key was pressed at some point
since the last time anyone checked"), maintained by Windows itself, that
cannot miss a press between polls the way a manual before/after comparison
can. `is_key_pressed()` replaced with `was_key_pressed_since_last_check()`;
the manual `hotkey_was_down`/`capture_hotkey_was_down` bookkeeping is gone
since the OS now does that bookkeeping for us. This requires **restarting
the reader** to take effect - the running process has the old code loaded
in memory.

**Not yet ruled out as a secondary factor**: some laptop keyboards route
F10 through an Fn-lock/media-key layer by default, in which case the
physical keypress may never generate a standard VK_F10 code at all
regardless of any polling fix. If F10 still doesn't register after
restarting with the fix above, try Fn+F10, or check for an Fn-lock toggle.

**Unrelated, harmless discovery made while investigating**: there's a
long-lived orphaned `python.exe` (PID visible via `tasklist`) stuck running
in Windows Session 0 (a service session, not the interactive desktop) -
almost certainly the same stray process noted on 2026-07-05 when a
sandboxed shell's spawned process ended up in the wrong session and
couldn't be killed from there either. It can never find the game window
(wrong session) and is not related to tonight's issue - left alone, not
worth chasing further unless it causes actual confusion later (e.g. two
processes fighting over the same log file).

**Next step**: restart `main.py` (stop the currently-running one, run it
again to pick up the fix) and retry F10 on the MK2/MK3/UMK3 screens.

### 5.7 Checkpoint (2026-07-06, later same evening)

Fix from §5.6 is committed and pushed to the private GitHub repo
(`mk-legacy-kollection-accessibility`, commit `28d3a5e`). As of this
checkpoint: **not yet re-tested live** - no new files have appeared in
`known_screens/` or `library_misses/` since the fix went in, so the
restart-and-retry step above is still outstanding. Resume there: restart
`main.py` and retry F10 on MK2/MK3/UMK3's main menu and submenus, then
report back what got captured (or whether F10 still doesn't register, in
which case check the Fn-lock possibility noted in §5.6).

---

## 6. Full agent-based audit + alternatives research (2026-08-19)

Three parallel agents were run: a fresh full audit of `ocr_reader/`'s
Python code (independent of the 2026-08-14 audit, re-verifying its fixes
rather than trusting them), a full audit of the dormant `proxy_dll/` code,
and research into whether a better overall approach exists than the
current OCR + reference-library design.

### 6.1 Research verdict: keep the current design

No better approach was found - the harder route already abandoned (hooking
Dear ImGui directly in memory) is a confirmed dead end, not just
unexplored: the real technology for exposing an immediate-mode UI's widget
tree to Windows accessibility APIs (AccessKit) only works for apps built
with it from source, and this game ships a stripped binary with no such
hooks. No sibling Digital Eclipse "Kollection" title has a known
accessibility fix either - this project is first-of-its-kind for this
engine. Two cheap, optional *additions* (not replacements) were identified:
**NVDA+R** (NVDA's own built-in OCR command) as a free manual fallback for
any screen not yet in the library, and the **"AI Content Describer" NVDA
add-on** (github.com/cartertemm/AI-content-describer) - install the
`.nvda-addon` release, configure a Claude API key under NVDA Settings → AI
Content Describer → Manage models, then **NVDA+Shift+I → "Describe the
entire screen"** sends a screenshot to Claude and speaks the description.
Useful specifically for a screen the automatic reader is staying silent on
(see 6.2 finding 6's fix below - this is a good manual complement to it),
not for real-time play (multi-second API latency).

### 6.2 Python reader audit: 7 findings, all fixed same day

The 2026-08-14 fixes (GDI/process-handle leaks, poll-loop try/except,
absolute-path launch fix, blank-`canonical_text` rejection) were confirmed
to hold up. But this fresh pass found real gaps, mostly forms of
**silent** failure - the worst outcome for someone who can't see a log:

1. **`NvdaSpeaker()` construction had no retry and ran outside the
   hardened poll loop.** If NVDA was still finishing its own startup when
   Steam launched the game (a plausible race, especially with voice packs
   loading), the reader crashed immediately with zero reading for the
   whole session. **Fixed**: `wait_for_nvda()` retries for up to 60s
   before giving up, and now beeps audibly (via `winsound`, works even
   without NVDA) if it never connects - a distinguishable "something's
   wrong" signal instead of pure silence.
2. **`NvdaSpeaker.speak()` never checked NVDA's own return codes.**
   `nvdaController_speakText`/`_cancelSpeech` return an error code that
   ctypes never raises on - so if NVDA restarted or the RPC channel
   dropped mid-session, every future `speak()` call became a silent
   no-op forever, with nothing for the existing try/except to catch.
   **Fixed**: `speak()` now checks the return code, tracks consecutive
   failures, beeps (rate-limited, not spammed) on failure, and
   self-heals automatically the next time NVDA accepts a call - no
   restart needed.
3. **The 2026-08-14 hardening introduced a zombie-process regression.**
   Before that fix, an uncaught exception killed the process and the next
   game relaunch would start a fresh, healthy reader. After it, the loop
   retries forever on *any* persistent failure (not just the window being
   gone, which already had its own exit timer), blocking any future
   relaunch's duplicate-instance check from ever spawning a working
   reader. **Fixed**: a new `EXIT_AFTER_CONSECUTIVE_POLL_FAILURES` counter
   (240 polls, reset on any successful poll) restores the "let a relaunch
   recover" behavior for genuinely persistent failures while still
   tolerating transient ones.
4. **The `capture_size` resolution-mismatch guard (added 2026-08-14) was
   dead on arrival** - all 11 live library entries predated that field, so
   it protected nothing. **Fixed**: backfilled `capture_size` on all 11
   `known_screens/*.json` entries with canonical text, from each PNG's
   actual pixel dimensions (verified: the 4 launcher entries are
   1280x720, matching the live game window; the 7 web-sourced arcade/PS1
   entries are various smaller sizes, correctly making them ineligible
   for highlight-bbox sampling against a live 1280x720 frame, which is
   the safe direction).
5. **The core screen-*recognition* path (dHash matching, not just
   highlight sampling) had no resolution-mismatch protection at all** -
   worse than silence, since PIL's `crop()` doesn't raise on an
   out-of-bounds box, a wrongly-sized frame could hash the wrong region
   and coincidentally match a *different* library entry, confidently
   speaking the wrong screen's text (e.g. announcing the main menu while
   a quit dialog is actually up). **Fixed**: `ScreenLibrary.match()` now
   skips any entry with an `roi` whose `capture_size` doesn't match the
   live frame, rather than risking a bad crop. Verified: matching a
   resized (960x540) copy of the main menu now correctly returns no
   match at all (falls back to safe live OCR) instead of a bogus one.
6. **Screen-change debounce could starve indefinitely on any uncatalogued
   screen.** Classic-game OCR is noisy enough that two consecutive polls
   rarely come back byte-for-byte identical, and the old logic required
   exact stability before speaking anything - so a screen not yet in the
   library could flicker forever and never get announced, with no way
   for the user to know something changed. **Fixed**: after
   `FORCE_SPEAK_AFTER_UNSTABLE_POLLS` (8) consecutive "something's
   different" polls without ever stabilizing, the reader now speaks the
   latest OCR reading once as best-effort rather than staying silent
   (library-matched screens don't need this - they're pre-verified text,
   not noisy live OCR). The AI Content Describer add-on (6.1) is a good
   manual complement for these cases too.
7. **`start_reader.vbs`'s WMI-based duplicate-instance check could
   silently stop protecting against duplicates** if WMI itself became
   persistently (not just transiently) unavailable - `On Error Resume
   Next` treated any failure as "assume nothing's running," which could
   spawn a second reader on top of an already-running one, both talking
   over each other on NVDA. **Fixed properly rather than patched**: moved
   duplicate-instance protection into `main.py` itself as a PID lock file
   (`acquire_single_instance_lock`/`release_single_instance_lock`,
   `ocr_reader/reader.lock`, gitignored) with stale-lock detection (a
   lock naming a PID that's no longer running is safely taken over, so
   even a hard kill self-heals). This has no WMI dependency at all, so
   `start_reader.vbs` was simplified to just launch `run_reader.bat`
   unconditionally - `main.py` now exits immediately, before ever
   touching NVDA, if another instance already holds the lock. Unit-tested
   directly: fresh acquire, re-acquire from the same PID, taking over a
   stale lock, correctly refusing to acquire over a real running PID, and
   correctly refusing to release a lock it doesn't own.

All fixes verified via `py_compile`, a JSON-validity pass over every
`known_screens/*.json`, and a direct import/functional test of
`ScreenLibrary.match()` against both a native-resolution and an
artificially-resized frame. **Not yet live-tested against the actual
running game** - that remains the next step (see 6.4).

### 6.3 proxy_dll audit: confirmed safe, two documentation fixes applied

Verdict: genuinely safe sitting disabled in the game folder today (the
real Windows `dinput8.dll` is confirmed correctly restored there, and the
disabled proxy sits under a filename nothing will ever load). All three
claimed 2026-08-14 fixes (startup race, render-thread log stutter, module
refcount leak) were independently re-verified as real and correct, not
just trusted from the commit message. One low-severity code issue found
(`InstallPresentHook` marks itself "installed" before confirming success,
so an uninitialized MinHook instance could be torn down on detach - MinHook
tolerates this today, not currently exploitable, left as-is since the code
path is dormant). Two real risks were documentation-only (no code bug, just
missing warnings for a future session): the proxy's fallback file
(`dinput8_orig.dll`) no longer exists, so re-enabling it without restoring
that file first would silently break all gamepad input; and the disabled
copy currently in the game folder predates the 2026-08-14 fixes. **Both
addressed**: added `proxy_dll/README.md` and a warning comment on
`LoadRealDinput8` in `dllmain.cpp`.

### 6.4 Resume-here checklist (current)

1. **Live-test everything from today's session together** - launch the
   real game with NVDA running, confirm: normal screens still speak
   correctly, F9/F10 still work, and ideally force a failure (e.g.
   temporarily close NVDA mid-session) to confirm the new beep-and-
   self-heal behavior actually fires and recovers once NVDA reopens.
   Nothing above has touched a live game session - all six code fixes
   were verified by direct unit/functional testing of the code in
   isolation, not by running the actual capture/NVDA loop against the
   game.
2. Once confirmed, push the accumulated local commits (now more than the
   2 that were already ahead of `origin/master`) to the private GitHub
   repo.
3. Everything still outstanding from §5.5's resume checklist remains
   open, unchanged by today's session: complete the launcher main-menu
   and quit-dialog entries (both known to be cut off), capture
   Options/Extras/Credits and a second game's submenu, and do the
   long-outstanding live captures for MK3, Trilogy, and Special Forces
   (never done - see §4/§5 checklists).
4. Optional, low-effort: install the "AI Content Describer" NVDA add-on
   (6.1) as a standing manual fallback - no project code changes needed,
   just NVDA-side setup.
