// v4: for each of the (few) raw DisplaySize-shaped matches found by v3,
// scan a wide byte window around it for an int32 value close to our own
// ground-truth frame counter (read from the proxy DLL's own Present hook,
// passed in via argv). This empirically locates FrameCount's real offset
// relative to DisplaySize instead of trusting a guessed branch layout.

'use strict';

function log(msg) { console.log('[find_gimgui4] ' + msg); }

function floatBytesLE(f) {
    const buf = new ArrayBuffer(4);
    new Float32Array(buf)[0] = f;
    return Array.from(new Uint8Array(buf)).map(b => ('0' + b.toString(16)).slice(-2)).join(' ');
}

function main() {
    const groundTruthFrame = (typeof GROUND_TRUTH_FRAME !== 'undefined') ? GROUND_TRUTH_FRAME : 10000;
    const clientSize = { width: 1280, height: 720 };
    const pattern = floatBytesLE(clientSize.width) + ' ' + floatBytesLE(clientSize.height);
    log('Ground-truth frame count (approx, from our own Present hook): ' + groundTruthFrame);
    log('Searching for DisplaySize pattern: ' + pattern);

    const MAX_RANGE_SIZE = 8 * 1024 * 1024;
    const ranges = Process.enumerateRanges('rw-').filter(r => !r.file && r.size <= MAX_RANGE_SIZE);

    let allMatches = [];
    for (const range of ranges) {
        try {
            const matches = Memory.scanSync(range.base, range.size, pattern);
            for (const m of matches) allMatches.push(m.address);
        } catch (e) { /* skip */ }
    }
    log('Found ' + allMatches.length + ' raw DisplaySize-shaped match(es). Scanning window around each for a plausible frame counter...');

    const WINDOW_BEFORE = 200;   // FrameCount lives *before* IO in ImGuiContext (IO is far from struct start)
    const WINDOW_AFTER = 30000;  // IO/DisplaySize sits early-ish; struct is ~24KB, FrameCount often appears later in some layouts too
    const TOLERANCE = 3000; // frames - generous, since our counter and ImGui's start at slightly different times

    for (const addr of allMatches) {
        log('--- Candidate DisplaySize @ ' + addr + ' ---');
        let hits = [];
        // Search both directions relative to the match address, 4-byte aligned.
        for (let off = -WINDOW_BEFORE; off <= WINDOW_AFTER; off += 4) {
            const candidateAddr = addr.add(off);
            let v;
            try { v = candidateAddr.readS32(); } catch (e) { continue; }
            if (Math.abs(v - groundTruthFrame) <= TOLERANCE && v > 0) {
                hits.push({ off, v });
            }
        }
        if (hits.length === 0) {
            log('  no plausible frame-counter-like int32 found in [-' + WINDOW_BEFORE + ', +' + WINDOW_AFTER + ']');
        } else {
            for (const h of hits) {
                log('  offset ' + h.off + ' (0x' + (h.off < 0 ? '-' + (-h.off).toString(16) : h.off.toString(16)) +
                    ') from DisplaySize: value = ' + h.v);
            }
        }
    }
}

setTimeout(main, 0);
