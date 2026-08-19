# proxy_dll — DISABLED, kept as a shelved option

This was the original approach for accessibility: hook Dear ImGui inside
the game's own memory to read menu text directly. The Present-call hook
here worked reliably, but locating ImGui's internal `GImGui` context in
memory (no shipped debug symbols) was never solved - see `PROGRESS.md` in
the repo root. The project pivoted to the external OCR + reference-library
approach in `ocr_reader/` instead, which is what's actually live today.

**Current state (confirmed 2026-08-19): disabled and safe.** In the real
game folder (`...\Mortal Kombat Legacy Kollection\`), the genuine Windows
`dinput8.dll` is in place, and this proxy sits there renamed to
`dinput8_proxy_disabled.dll` - a name nothing will ever auto-load.

**Before ever re-enabling this** (renaming it back to `dinput8.dll` in the
game folder): a copy of the real system `dinput8.dll` must also be present
there as `dinput8_orig.dll`, which this proxy loads and forwards all six
DirectInput exports to. That file was removed when the proxy was disabled
and no longer exists anywhere in the game folder or this repo. Re-enabling
the proxy without restoring it first will silently break all gamepad/
DirectInput input for the whole session - see the warning comment on
`LoadRealDinput8` in `dllmain.cpp` for the failure mode.

Also note: the disabled copy currently sitting in the game folder predates
the 2026-08-14 bug-fix commit (startup race, render-thread log stutter,
module refcount leak). The corrected build only exists at
`proxy_dll/build/dinput8.dll` in this repo - don't assume the file already
in the game folder is the fixed one.
