// v3: search directly for the literal byte pattern of ImGuiIO::DisplaySize
// (the two floats matching the game's actual client resolution), instead of
// guessing at pointer locations. This sidesteps uncertainty about which
// ImGui branch (mainline vs "docking", which has a different ImGuiContext
// layout) the game was built against, since DisplaySize sits at a very
// early, structurally stable offset within ImGuiIO in both branches.

'use strict';

const IO_within_Context = 8;      // offsetof(ImGuiContext, IO) - two bools precede it in both branches
const DisplaySize_within_IO = 8;  // offsetof(ImGuiIO, DisplaySize)
const FRAME_COUNT_CANDIDATES = [
    { name: 'mainline v1.89.8', offset: 15920 },
    { name: 'docking v1.89.8-docking', offset: 16240 },
];

function log(msg) { console.log('[find_gimgui3] ' + msg); }

function floatBytesLE(f) {
    const buf = new ArrayBuffer(4);
    new Float32Array(buf)[0] = f;
    const bytes = new Uint8Array(buf);
    return Array.from(bytes).map(b => ('0' + b.toString(16)).slice(-2)).join(' ');
}

function getClientSize() {
    const user32 = Process.getModuleByName('user32.dll');
    const kernel32 = Process.getModuleByName('kernel32.dll');
    const GetClientRect = new NativeFunction(user32.getExportByName('GetClientRect'), 'int', ['pointer', 'pointer']);
    const GetCurrentProcessId = new NativeFunction(kernel32.getExportByName('GetCurrentProcessId'), 'uint32', []);
    const EnumWindows = new NativeFunction(user32.getExportByName('EnumWindows'), 'int', ['pointer', 'pointer']);
    const GetWindowThreadProcessId = new NativeFunction(user32.getExportByName('GetWindowThreadProcessId'), 'uint32', ['pointer', 'pointer']);
    const IsWindowVisible = new NativeFunction(user32.getExportByName('IsWindowVisible'), 'int', ['pointer']);

    const myPid = GetCurrentProcessId();
    let found = null;
    const cb = new NativeCallback((hwnd) => {
        const pidBuf = Memory.alloc(4);
        GetWindowThreadProcessId(hwnd, pidBuf);
        if (pidBuf.readU32() === myPid && IsWindowVisible(hwnd)) { found = hwnd; return 0; }
        return 1;
    }, 'int', ['pointer', 'pointer']);
    EnumWindows(cb, ptr(0));
    if (!found) { log('WARNING: no visible window found.'); return null; }

    const rect = Memory.alloc(16);
    GetClientRect(found, rect);
    const left = rect.readS32(), top = rect.add(4).readS32();
    const right = rect.add(8).readS32(), bottom = rect.add(12).readS32();
    return { width: right - left, height: bottom - top };
}

function main() {
    // Ground truth from our own Present hook's DXGI_SWAP_CHAIN_DESC log:
    // the game's actual swapchain buffer is 1280x720, NOT the 1920x1080
    // client rect (Windows is compositing/scaling it - 150% DPI scale).
    const clientSize = { width: 1280, height: 720 };
    log('Using real swapchain buffer size (from Present hook log): ' + clientSize.width + 'x' + clientSize.height);

    const pattern = floatBytesLE(clientSize.width) + ' ' + floatBytesLE(clientSize.height);
    log('Searching all rw- memory for byte pattern: ' + pattern);

    const MAX_RANGE_SIZE = 8 * 1024 * 1024; // a ~24KB struct won't live in a huge buffer
    const allRanges = Process.enumerateRanges('rw-');
    const privateRanges = allRanges.filter(r => !r.file);
    const ranges = privateRanges.filter(r => r.size <= MAX_RANGE_SIZE);
    const totalVolume = ranges.reduce((sum, r) => sum + r.size, 0);
    const skippedVolume = privateRanges.filter(r => r.size > MAX_RANGE_SIZE).reduce((sum, r) => sum + r.size, 0);
    log('Total rw- ranges: ' + allRanges.length + ', private: ' + privateRanges.length +
        ', private+size-capped: ' + ranges.length + ' (' + (totalVolume / (1024 * 1024)).toFixed(1) + ' MB to scan, ' +
        (skippedVolume / (1024 * 1024)).toFixed(1) + ' MB skipped as oversized)');

    let totalScanned = 0;
    let allMatches = [];
    let processed = 0;
    const t0 = Date.now();
    for (const range of ranges) {
        try {
            const matches = Memory.scanSync(range.base, range.size, pattern);
            for (const m of matches) allMatches.push(m.address);
            totalScanned += range.size;
        } catch (e) { /* skip unreadable */ }
        processed++;
        if (processed % 100 === 0) {
            log('  progress: ' + processed + '/' + ranges.length + ' ranges, ' +
                (totalScanned / (1024 * 1024)).toFixed(1) + ' MB scanned, ' +
                ((Date.now() - t0) / 1000).toFixed(1) + 's elapsed...');
        }
    }
    log('Scanned ' + (totalScanned / (1024 * 1024)).toFixed(1) + ' MB across ' + ranges.length +
        ' private rw- ranges in ' + ((Date.now() - t0) / 1000).toFixed(1) + 's. Found ' +
        allMatches.length + ' raw DisplaySize-shaped match(es).');

    const ctxPtrs = allMatches.map(displaySizeAddr =>
        ({ displaySizeAddr, ctxPtr: displaySizeAddr.sub(DisplaySize_within_IO).sub(IO_within_Context) }));

    let candidates = [];
    for (const c of ctxPtrs) {
        for (const fc of FRAME_COUNT_CANDIDATES) {
            let frameCount1;
            try { frameCount1 = c.ctxPtr.add(fc.offset).readS64().toNumber(); } catch (e) { continue; }
            if (frameCount1 > 0 && frameCount1 < 100000000) {
                candidates.push({ ...c, branch: fc.name, offset: fc.offset, frameCount1 });
            }
        }
    }
    log(candidates.length + ' candidate(s) had a plausible FrameCount under at least one branch offset.');

    if (candidates.length === 0) {
        log('No candidates matched either offset set. Raw DisplaySize match addresses for manual inspection:');
        for (const a of allMatches) log('  DisplaySize-shaped match @ ' + a);
        return;
    }

    log('Waiting 300ms then re-checking FrameCount advances...');
    Thread.sleep(0.3);

    let confirmed = [];
    for (const c of candidates) {
        let frameCount2;
        try { frameCount2 = c.ctxPtr.add(c.offset).readS64().toNumber(); } catch (e) { continue; }
        const delta = frameCount2 - c.frameCount1;
        if (delta >= 2 && delta <= 60) {
            confirmed.push({ ...c, frameCount2, delta });
        }
    }

    log('CONFIRMED ' + confirmed.length + ' candidate(s):');
    for (const c of confirmed) {
        log('  [' + c.branch + '] ImGuiIO.DisplaySize @ ' + c.displaySizeAddr + '  ->  ImGuiContext* = ' + c.ctxPtr +
            '  FrameCount ' + c.frameCount1 + ' -> ' + c.frameCount2 + ' (delta ' + c.delta + ')');
    }
}

// Deferred: keeps script.load() fast (it just registers this timer), so the
// heavy scan below doesn't block the Frida load handshake and time out.
setTimeout(main, 0);
