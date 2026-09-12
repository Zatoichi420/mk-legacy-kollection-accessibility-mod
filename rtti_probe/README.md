# rtti_probe

Phase 1 memory-reading prototype (see the project's `PROGRESS.md` and
memory). Locates *live* instances of any named C++ class inside
`mk_legacy_kollection.exe` by walking standard MSVC x64 RTTI structures -
no PDB, no Ghidra/IDA, no code injection. Read-only throughout
(`PROCESS_VM_READ` only).

## Why this exists

The launcher's own Dear ImGui UI has no accessibility hook and was a
confirmed dead end. But the classic titles run on two real emulator
cores with intact (unstripped-at-the-symbol-name-level) C++ RTTI: the
open-source `ares` (in `pancake_libretro_windows.dll`, for the 3 PS1
titles) and an in-house `Moo` core inside the main exe (for the
Genesis/Game Gear ports and the Midway arcade boards). This toolkit is
the first working prototype for the `Moo` side.

## What it proved, 2026-09-12

Against a live arcade **Mortal Kombat II** session:

```
python rtti_probe.py find-class "Moo::DevGroup"
#   COL RVA=0x00ce3238  vtable VA=0x7ff74ff44ba0

python rtti_probe.py find-instances 0x7ff74ff44ba0
#   Found 1 instance: 0x023edaa48178

python rtti_probe.py identify 0x23edaa48178 0x23edaa69a50 0x23edaa9bcf8 0x23edaa9bf00 0x23edaa9bdc8
#   0x023edaa48178  class=Moo::DevGroup
#   0x023edaa69a50  class=Moo::Moo_CPU_TMS34010
#   0x023edaa9bcf8  class=Moo::Moo_Glue_Midway_Blit_T
#   0x023edaa9bf00  class=Moo::Moo_CPU_ADSP2105
#   0x023edaa9bdc8  class=Moo::Moo_Sub_DCS
```

The `DevGroup` instance's first 4 pointer-sized fields (at +0x18/+0x20/
+0x28/+0x30, after a vfptr and what looks like a sentinel/count at +0x08)
are exactly the real, documented hardware of a Midway **T-Unit** arcade
board - the actual board MK1/MK2 ran on. That's not a guess the
technique produced by luck: it's ground truth, which validates the
whole approach end-to-end.

## How it works

1. **Dump** the module's image straight from live process memory (already
   correctly relocated/laid out - reading the file from disk and doing
   your own RVA math is unnecessary and error-prone by comparison).
2. **find-class**: locate the mangled TypeDescriptor name string for a
   class (`.?AVDevGroup@Moo@@`), then the Complete Object Locator (COL)
   structures that reference it by RVA (validated via the COL's own
   signature/pSelf fields), then the vtable(s) that point back at those
   COLs - a QWORD pointer to the COL sits 8 bytes before the actual
   vtable in memory.
3. **find-instances**: given a vtable VA, scan writable/heap memory for
   QWORD values equal to it. Each hit's address is a live instance - the
   vfptr field sits at offset 0 of any polymorphic C++ object.
4. **identify**: the inverse of (2) - given an arbitrary address, read
   its vfptr and walk backwards to the class name. This is how the four
   `DevGroup` child pointers above got labeled: dump the object's raw
   bytes, then run every pointer-shaped field back through `identify`.

## Important caveats

- **Every address is only valid for the current process instance.** ASLR
  means the module base (and everything derived from it) changes on
  each relaunch - re-run `find-class`/`find-instances` each session.
  Only the technique and the mangled class-name strings are durable.
- **This finds structure, not yet narration-usable state.** Locating
  `DevGroup` and naming its children is a floor to stand on, not the
  goal - the next step is finding *which* field, on *which* device,
  actually holds something like a menu-selection index. `identify` plus
  a raw hex dump of a located object is the toolset for that hunt.
- Requires `mk_legacy_kollection.exe` to already be running.
