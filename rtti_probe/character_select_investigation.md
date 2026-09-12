# Character-select memory hunt (2026-09-12) - inconclusive, resume point

Attempted to locate the live "which fighter is highlighted" value on MK2's
**Choose Your Fighter** screen, using a snapshot-diff technique layered on
top of `rtti_probe.py`'s findings (see that folder's `README.md`) rather
than the RTTI locate-vtable technique itself. Result: **narrowed to a
promising region, did not conclusively identify the variable.** Recording
this so the next session doesn't have to redo the narrowing from scratch.

## Method

1. `snapshot_writable.py` dumps every writable (heap) region of the live
   process to a file.
2. Take a snapshot, have a human move the character-select cursor one
   step, take another snapshot, `diff_snapshots.py` the two.
3. A whole-heap diff (~1.1GB) for "changed by exactly +1" alone produced
   **18.5 million hits** - useless on its own; too much else ticks by 1
   every frame (timers, animation, audio) even at rest.
4. Narrowed by restricting the diff to just the memory region containing
   the `Moo_CPU_TMS34010` instance found via `rtti_probe.py` (that CPU
   object has a pointer field at +0x10 into a ~1.1MB writable region,
   base `0x23eda010000` at the time - **ASLR/heap-layout dependent, will
   differ next session**). Diffing *within just that region* dropped the
   noise from millions of hits to single digits.

## What was found

Two offsets *within that region* (offsets relative to the region's own
base that session, not durable addresses) changed on every cursor move:

| Screen | `+0x58a72` | `+0x58c32` |
|---|---|---|
| Liu Kang | 13 | 0 |
| Kung Lao | 6 | 13 |
| Johnny Cage | 13 | 6 |

`+0x58c32` at each step equals `+0x58a72` from the step before - it's a
one-deep history/shift register, not an independent value. The "live"
value itself only ever takes **two** values (13 and 6), alternating,
across three different characters - it does not count 0, 1, 2. That's
the reason this is flagged inconclusive rather than solved: a value that
only toggles between two numbers regardless of which of three characters
is selected looks more like a highlight-blink/animation-phase counter
that happened to correlate with the timing of each snapshot, than like
an actual "selected character" variable. Three samples isn't enough to
rule that out.

## Resume point

- Don't trust `+0x58a72`/`+0x58c32` as the selection index without more
  evidence. A clean test: snapshot repeatedly *without* moving the cursor
  at all, several times a second - if these bytes still change on their
  own, they're an animation/timer artifact, not selection state, and can
  be ruled out entirely.
- If they turn out to be an artifact, keep widening the search radius
  within the same ~1.1MB region (or check the other candidate pointer
  field from the CPU object, the ~192KB region, which wasn't tested this
  session) using the same snapshot-diff technique, ideally across *many*
  more than 3 samples so real signal (small integer, tracks 1:1 with
  actual position, monotonic under repeated same-direction moves)
  separates from noise (ticks regardless of input, or oscillates between
  few values regardless of true state).
- A cleaner alternative to blind snapshot-diffing, if available next
  time: actual disassembly (radare2 is already vendored in
  `tools/radare2-6.1.8-w64/` from earlier ImGui work) of a function that
  reads controller input on this screen, to find the real selection
  variable by code reference instead of guessing from memory diffs.
