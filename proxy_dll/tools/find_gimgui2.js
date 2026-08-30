// v2: brute-force pointer scan instead of instruction-pattern scan.
// Rationale: ImGui::GetCurrentContext() is a 1-line function and very
// likely got inlined everywhere under /O2, so there may be no standalone
// "mov rax,[rip+X]; ret" accessor to find in .text at all. Instead, scan
// the main module's writable (.data/.bss) memory directly for any
// 8-byte-aligned QWORD that looks like a valid heap pointer, and validate
// each candidate by dereferencing it as an ImGuiContext using the offsets
// computed from the real ImGui 1.89.8 headers.

'use strict';

const OFFSETS = {
    IO: 8,
    IO_DisplaySize: 8, // absolute = IO + 8 = 16
    NavId: 18632,
    NavWindow: 18624,
    FrameCount: 15920,
};
const CTX_SIZE = 24168;

function log(msg) { console.log('[find_gimgui2] ' + msg); }

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

function readCandidate(ctxPtr) {
    try {
        const displayW = ctxPtr.add(OFFSETS.IO + OFFSETS.IO_DisplaySize).readFloat();
        const displayH = ctxPtr.add(OFFSETS.IO + OFFSETS.IO_DisplaySize + 4).readFloat();
        const frameCount = ctxPtr.add(OFFSETS.FrameCount).readS64().toNumber();
        return { displayW, displayH, frameCount };
    } catch (e) { return null; }
}

// Loose first-pass filter: values merely in a sane numeric range. The real
// discriminator is the second pass (frame count must advance in step with
// real elapsed time), which is what actually rules out coincidental
// heap garbage.
function passesLooseFilter(v) {
    if (!v) return false;
    if (!(v.displayW >= 200 && v.displayW <= 7680)) return false;
    if (!(v.displayH >= 200 && v.displayH <= 4320)) return false;
    if (!(v.frameCount > 0 && v.frameCount < 100000000)) return false;
    return true;
}

function main() {
    const mainModule = Process.enumerateModules()[0];
    log('Main module: ' + mainModule.name + ' base=' + mainModule.base + ' size=' + mainModule.size);

    const clientSize = getClientSize();
    if (clientSize) log('Detected game window client size: ' + clientSize.width + 'x' + clientSize.height);

    // Writable ranges belonging to the main module (.data/.bss).
    const writableRanges = Process.enumerateRanges('rw-').filter(r =>
        r.base.compare(mainModule.base) >= 0 &&
        r.base.compare(mainModule.base.add(mainModule.size)) < 0
    );
    log('Scanning ' + writableRanges.length + ' writable range(s) within main module for candidate pointers...');

    // All currently mapped memory, used to sanity-check that a candidate
    // QWORD actually points somewhere valid before we dereference it.
    // Sorted + binary-searched since this gets checked many thousands of times.
    // (Frida's enumerateRanges doesn't accept a full "any protection"
    // wildcard string on this version, so union the common specs instead.)
    const specs = ['r--', 'rw-', 'rwx', 'r-x', '-w-', '--x'];
    let rawRanges = [];
    for (const spec of specs) {
        try { rawRanges = rawRanges.concat(Process.enumerateRanges(spec)); } catch (e) { /* ignore */ }
    }
    const allRanges = rawRanges
        .map(r => ({ start: r.base, end: r.base.add(r.size) }))
        .sort((a, b) => a.start.compare(b.start));

    function isMapped(addr) {
        let lo = 0, hi = allRanges.length - 1;
        while (lo <= hi) {
            const mid = (lo + hi) >> 1;
            const r = allRanges[mid];
            if (addr.compare(r.start) < 0) hi = mid - 1;
            else if (addr.compare(r.end) >= 0) lo = mid + 1;
            else return true;
        }
        return false;
    }

    let passLoose = [];
    let scanned = 0;
    for (const range of writableRanges) {
        let offset = 0;
        while (offset + 8 <= range.size) {
            const addr = range.base.add(offset);
            let val;
            try { val = addr.readPointer(); } catch (e) { offset += 8; continue; }
            scanned++;
            if (!val.isNull() && isMapped(val)) {
                const v1 = readCandidate(val);
                if (passesLooseFilter(v1)) {
                    passLoose.push({ globalVarAddr: addr, ctxPtr: val, v1 });
                }
            }
            offset += 8;
        }
    }
    log('Scanned ' + scanned + ' candidate QWORDs. ' + passLoose.length + ' passed the loose numeric filter.');

    if (passLoose.length === 0) {
        log('No candidates even passed the loose filter - offsets likely do not match this build.');
        return;
    }

    log('Waiting 300ms, then re-reading FrameCount on each candidate to check it advances in step with real time...');
    Thread.sleep(0.3);

    let confirmed = [];
    for (const c of passLoose) {
        const v2 = readCandidate(c.ctxPtr);
        if (!v2) continue;
        const delta = v2.frameCount - c.v1.frameCount;
        // At 300ms, expect somewhere around 5-30 frames depending on frame
        // rate (30-100fps range) - generous bounds to tolerate hitches.
        if (delta >= 2 && delta <= 60) {
            confirmed.push({ ...c, v2, delta });
        }
    }

    log('Confirmed ' + confirmed.length + ' candidate(s) with plausible advancing FrameCount:');
    for (const c of confirmed) {
        log('  global var @ ' + c.globalVarAddr + ' (module+0x' + c.globalVarAddr.sub(mainModule.base).toString(16) + ')' +
            '  ->  ctx @ ' + c.ctxPtr +
            '  DisplaySize=(' + c.v1.displayW + ',' + c.v1.displayH + ')' +
            '  FrameCount ' + c.v1.frameCount + ' -> ' + c.v2.frameCount + ' (delta ' + c.delta + ')');
    }
    if (confirmed.length === 0) {
        log('No candidates confirmed by the frame-advance check.');
    }
}

main();
