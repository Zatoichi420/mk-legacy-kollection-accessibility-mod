// Frida script: attach to the running mk_legacy_kollection.exe and locate
// Dear ImGui's global context pointer (GImGui) without any debug symbols.
//
// Technique: ImGui::GetCurrentContext() compiles down to a tiny, distinctive
// function body: `mov rax, [rip+disp32] ; ret` (bytes: 48 8B 05 ?? ?? ?? ?? C3).
// That disp32 resolves to the address of the GImGui global variable itself.
// We scan the main module's executable section for this byte pattern, then
// validate each candidate by dereferencing it as an ImGuiContext (using the
// exact offsets computed from the real ImGui 1.89.8 headers) and checking
// that ImGuiIO::DisplaySize matches the game window's actual client size.

'use strict';

const OFFSETS = {
    IO: 8,
    NavId: 18632,
    NavWindow: 18624,
    FrameCount: 15920,
    IO_DisplaySize: 8, // within IO, so absolute = IO + 8 = 16
};

function log(msg) {
    console.log('[find_gimgui] ' + msg);
}

function getClientSize() {
    const user32 = Process.getModuleByName('user32.dll');
    const GetForegroundWindow = new NativeFunction(user32.getExportByName('GetForegroundWindow'), 'pointer', []);
    const GetClientRect = new NativeFunction(user32.getExportByName('GetClientRect'), 'int', ['pointer', 'pointer']);
    // Find our own process's top-level window instead of relying on foreground
    // focus (game might not be focused when this script runs).
    const kernel32 = Process.getModuleByName('kernel32.dll');
    const GetCurrentProcessId = new NativeFunction(kernel32.getExportByName('GetCurrentProcessId'), 'uint32', []);
    const myPid = GetCurrentProcessId();

    const EnumWindows = new NativeFunction(user32.getExportByName('EnumWindows'), 'int', ['pointer', 'pointer']);
    const GetWindowThreadProcessId = new NativeFunction(user32.getExportByName('GetWindowThreadProcessId'), 'uint32', ['pointer', 'pointer']);
    const IsWindowVisible = new NativeFunction(user32.getExportByName('IsWindowVisible'), 'int', ['pointer']);

    let found = null;
    const cb = new NativeCallback((hwnd) => {
        const pidBuf = Memory.alloc(4);
        GetWindowThreadProcessId(hwnd, pidBuf);
        const pid = pidBuf.readU32();
        if (pid === myPid && IsWindowVisible(hwnd)) {
            found = hwnd;
            return 0; // stop enumeration
        }
        return 1; // continue
    }, 'int', ['pointer', 'pointer']);

    EnumWindows(cb, ptr(0));

    if (!found) {
        log('WARNING: could not find a visible top-level window for this process.');
        return null;
    }

    const rect = Memory.alloc(16); // RECT { LONG left, top, right, bottom }
    GetClientRect(found, rect);
    const left = rect.readS32();
    const top = rect.add(4).readS32();
    const right = rect.add(8).readS32();
    const bottom = rect.add(12).readS32();
    return { width: right - left, height: bottom - top };
}

function scanForCandidates(mainModule) {
    const pattern = '48 8B 05 ?? ?? ?? ?? C3';
    const ranges = Process.enumerateRanges('r-x').filter(r =>
        r.base.compare(mainModule.base) >= 0 &&
        r.base.compare(mainModule.base.add(mainModule.size)) < 0
    );

    let candidates = [];
    for (const range of ranges) {
        try {
            const matches = Memory.scanSync(range.base, range.size, pattern);
            for (const m of matches) {
                candidates.push(m.address);
            }
        } catch (e) {
            // unreadable range, skip
        }
    }
    return candidates;
}

function tryValidate(insnAddr, clientSize) {
    // decode disp32 from bytes at insnAddr+3..+6
    const disp32 = insnAddr.add(3).readS32();
    const globalVarAddr = insnAddr.add(7).add(disp32);

    let ctxPtr;
    try {
        ctxPtr = globalVarAddr.readPointer();
    } catch (e) {
        return null;
    }
    if (ctxPtr.isNull()) return null;

    let displayW, displayH, frameCount;
    try {
        displayW = ctxPtr.add(OFFSETS.IO + OFFSETS.IO_DisplaySize).readFloat();
        displayH = ctxPtr.add(OFFSETS.IO + OFFSETS.IO_DisplaySize + 4).readFloat();
        frameCount = ctxPtr.add(OFFSETS.FrameCount).readS64();
    } catch (e) {
        return null;
    }

    const sizeMatches = clientSize &&
        Math.abs(displayW - clientSize.width) < 2 &&
        Math.abs(displayH - clientSize.height) < 2;

    const frameCountPlausible = frameCount > 0 && frameCount < 100000000;

    if (sizeMatches && frameCountPlausible) {
        return { globalVarAddr, ctxPtr, displayW, displayH, frameCount };
    }
    return null;
}

function main() {
    const mainModule = Process.enumerateModules()[0];
    log('Main module: ' + mainModule.name + ' base=' + mainModule.base + ' size=' + mainModule.size);

    const clientSize = getClientSize();
    if (clientSize) {
        log('Detected game window client size: ' + clientSize.width + 'x' + clientSize.height);
    }

    const candidates = scanForCandidates(mainModule);
    log('Found ' + candidates.length + ' byte-pattern candidates for GetCurrentContext-style accessor.');

    let confirmed = [];
    for (const addr of candidates) {
        const result = tryValidate(addr, clientSize);
        if (result) {
            confirmed.push({ insnAddr: addr, ...result });
        }
    }

    log('Confirmed ' + confirmed.length + ' candidate(s) matching DisplaySize + plausible FrameCount:');
    for (const c of confirmed) {
        log('  instruction @ ' + c.insnAddr + '  ->  global var @ ' + c.globalVarAddr +
            '  ->  ctx @ ' + c.ctxPtr + '  DisplaySize=(' + c.displayW + ',' + c.displayH + ')' +
            '  FrameCount=' + c.frameCount);
    }

    if (confirmed.length === 1) {
        log('SUCCESS: unique match found. globalVarAddr (relative to module base) = 0x' +
            confirmed[0].globalVarAddr.sub(mainModule.base).toString(16));
    } else if (confirmed.length === 0) {
        log('No candidates confirmed - client size check may have failed, or pattern/offsets need adjustment.');
    } else {
        log('Multiple candidates matched - re-run with a second validation pass (e.g. re-check FrameCount increases over time) to disambiguate.');
    }
}

main();
