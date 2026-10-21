// Developer probe: find which game function draws a given piece of text.
//
// If legacyhook_probe.txt exists next to the game, each line is a function
// RVA (hex). Every listed function gets a tiny assembly stub that saves the
// argument registers (rcx, rdx, r8, r9 and xmm0-3), reports the four
// integer arguments to ProbeHit, restores everything and jumps on to the
// original code, so the game sees no difference. ProbeHit logs each new
// piece of text found through an argument: a char*, a pointer to a char*
// (string_view / heap std::string) or text stored inline (short std::string).

#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <set>
#include <string>
#include <vector>
#include "MinHook.h"

void LogLine(const char* fmt, ...);

namespace probe {
namespace {

struct Probe {
    uintptr_t rva;
    void* original;
    unsigned hits;
    bool trace;  // "t" after the RVA in legacyhook_probe.txt: log every call's raw arguments
};
std::vector<Probe> g_probes;
CRITICAL_SECTION g_lock;
std::set<std::pair<size_t, std::string>> g_seen;

// Copies printable text at p (at least 2 chars) into out; false otherwise.
bool TryText(const char* p, char* out, size_t cap) {
    if ((uintptr_t)p < 0x10000 || (uintptr_t)p > 0x7FFFFFFFFFFF) return false;
    size_t n = 0;
    __try {
        for (; n + 1 < cap && p[n]; n++) {
            unsigned char c = (unsigned char)p[n];
            if (c < 0x20 || c > 0x7E) return false;
            out[n] = (char)c;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
    out[n] = 0;
    return n >= 2 && n + 1 < cap;
}

bool TryDeref(uintptr_t a, uintptr_t* out) {
    if (a < 0x10000 || a > 0x7FFFFFFFFFFF) return false;
    __try {
        *out = *(uintptr_t*)a;
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

void Note(size_t id, int arg, const char* how, const char* text) {
    EnterCriticalSection(&g_lock);
    Probe& p = g_probes[id];
    bool fresh = g_seen.size() < 20000 && g_seen.insert({id, text}).second;
    if (fresh) p.hits++;
    LeaveCriticalSection(&g_lock);
    if (fresh && p.hits <= 500) LogLine("PROBE %06zx arg%d %s \"%s\"", p.rva, arg, how, text);
}

}  // namespace

// frame: the stub's stack. xmm0-3 saved at +30h..+6Fh; the caller's stack
// arguments (5th onward) start at +D0h.
static volatile LONG g_traceLines;
static volatile bool g_traceOn;  // while legacyhook_trace_on exists (see WatchThread)

static void Trace(size_t id, const uintptr_t* args, const uint8_t* frame) {
    if (!g_traceOn || InterlockedIncrement(&g_traceLines) > 3000) return;
    char text[160] = "";
    if (!TryText((const char*)args[1], text, sizeof(text)) && !TryText((const char*)args[3], text, sizeof(text)))
        TryText((const char*)args[2], text, sizeof(text));
    float x[4];
    uintptr_t stackArgs[4] = {}, ret = 0;
    __try {
        for (int i = 0; i < 4; i++) x[i] = *(const float*)(frame + 0x30 + 16 * i);
        for (int i = 0; i < 4; i++) stackArgs[i] = *(const uintptr_t*)(frame + 0xD0 + 8 * i);
        ret = *(const uintptr_t*)(frame + 0xA8);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return;
    }
    uintptr_t base = (uintptr_t)GetModuleHandleW(nullptr);
    LogLine("TRACE %06zx from %llx \"%s\" rcx=%llx rdx=%llx r8=%llx r9=%llx xmm=%g,%g,%g,%g stk=%llx,%llx,%llx,%llx",
            g_probes[id].rva, (unsigned long long)(ret - base), text, (unsigned long long)args[0],
            (unsigned long long)args[1], (unsigned long long)args[2],
            (unsigned long long)args[3], x[0], x[1], x[2], x[3], (unsigned long long)stackArgs[0],
            (unsigned long long)stackArgs[1], (unsigned long long)stackArgs[2], (unsigned long long)stackArgs[3]);
}

extern "C" void ProbeHit(size_t id, uintptr_t a1, uintptr_t a2, uintptr_t a3, uintptr_t a4, const uint8_t* frame) {
    uintptr_t args[4] = {a1, a2, a3, a4};
    if (g_probes[id].trace) {
        Trace(id, args, frame);
        return;
    }
    char text[160];
    for (int i = 0; i < 4; i++) {
        uintptr_t inner;
        if (TryText((const char*)args[i], text, sizeof(text))) Note(id, i + 1, "str", text);
        else if (TryDeref(args[i], &inner) && TryText((const char*)inner, text, sizeof(text))) Note(id, i + 1, "*str", text);
    }
}

namespace {

const size_t kJumpSlot = 121;  // offset of the jmp's 8-byte target in the stub

// Builds the save/report/restore/jump stub for probe id.
void* MakeStub(size_t id) {
    static uint8_t* pool;
    static size_t used = 4096;
    if (used + 160 > 4096) {
        pool = (uint8_t*)VirtualAlloc(nullptr, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
        used = 0;
    }
    uint8_t* s = pool + used;
    std::vector<uint8_t> b = {
        0x51, 0x52, 0x41, 0x50, 0x41, 0x51,                    // push rcx, rdx, r8, r9
        0x48, 0x81, 0xEC, 0x88, 0x00, 0x00, 0x00,              // sub rsp, 0x88 (keeps 16-byte alignment)
        0xF3, 0x0F, 0x7F, 0x44, 0x24, 0x30,                    // movdqu [rsp+30h], xmm0
        0xF3, 0x0F, 0x7F, 0x4C, 0x24, 0x40,                    // movdqu [rsp+40h], xmm1
        0xF3, 0x0F, 0x7F, 0x54, 0x24, 0x50,                    // movdqu [rsp+50h], xmm2
        0xF3, 0x0F, 0x7F, 0x5C, 0x24, 0x60,                    // movdqu [rsp+60h], xmm3
        0x4C, 0x89, 0x4C, 0x24, 0x20,                          // mov [rsp+20h], r9   (5th arg)
        0x48, 0x89, 0x64, 0x24, 0x28,                          // mov [rsp+28h], rsp  (6th arg: frame)
        0x4D, 0x89, 0xC1,                                      // mov r9, r8
        0x49, 0x89, 0xD0,                                      // mov r8, rdx
        0x48, 0x89, 0xCA,                                      // mov rdx, rcx
        0x48, 0xB9, 0, 0, 0, 0, 0, 0, 0, 0,                    // mov rcx, id
        0x48, 0xB8, 0, 0, 0, 0, 0, 0, 0, 0,                    // mov rax, ProbeHit
        0xFF, 0xD0,                                            // call rax
        0xF3, 0x0F, 0x6F, 0x44, 0x24, 0x30,                    // movdqu xmm0, [rsp+30h]
        0xF3, 0x0F, 0x6F, 0x4C, 0x24, 0x40,
        0xF3, 0x0F, 0x6F, 0x54, 0x24, 0x50,
        0xF3, 0x0F, 0x6F, 0x5C, 0x24, 0x60,
        0x48, 0x81, 0xC4, 0x88, 0x00, 0x00, 0x00,              // add rsp, 0x88
        0x41, 0x59, 0x41, 0x58, 0x5A, 0x59,                    // pop r9, r8, rdx, rcx
        0xFF, 0x25, 0, 0, 0, 0,                                // jmp [rip+0]
        0, 0, 0, 0, 0, 0, 0, 0,                                // -> original (filled in later)
    };
    const size_t idAt = 58, fnAt = 68;  // the imm64 fields of the two movs
    static_assert(kJumpSlot == 121, "stub layout");
    uint64_t fn = (uint64_t)&ProbeHit;
    memcpy(&b[idAt], &id, 8);
    memcpy(&b[fnAt], &fn, 8);
    if (b.size() != kJumpSlot + 8) return nullptr;
    memcpy(s, b.data(), b.size());
    used += (b.size() + 15) & ~15;
    return s;
}

}  // namespace

static std::wstring g_traceFlag;

bool TraceOn() { return g_traceOn && g_traceLines < 3000; }

static DWORD WINAPI WatchThread(LPVOID) {
    for (;;) {
        bool on = GetFileAttributesW(g_traceFlag.c_str()) != INVALID_FILE_ATTRIBUTES;
        if (on && !g_traceOn) {
            g_traceLines = 0;
            LogLine("TRACE on");
        }
        if (!on && g_traceOn) LogLine("TRACE off");
        g_traceOn = on;
        Sleep(200);
    }
}

void Install(const std::wstring& gameDir, uint8_t* base) {
    FILE* f = _wfsopen((gameDir + L"\\legacyhook_probe.txt").c_str(), L"r", _SH_DENYNO);
    if (!f) return;
    g_traceFlag = gameDir + L"\\legacyhook_trace_on";
    CreateThread(nullptr, 0, WatchThread, nullptr, 0, nullptr);
    InitializeCriticalSection(&g_lock);
    char line[64];
    while (fgets(line, sizeof(line), f)) {
        char* rest;
        uintptr_t rva = strtoull(line, &rest, 16);
        if (rva) g_probes.push_back({rva, nullptr, 0, strchr(rest, 't') != nullptr});
    }
    fclose(f);
    size_t ok = 0;
    for (size_t i = 0; i < g_probes.size(); i++) {
        uint8_t* stub = (uint8_t*)MakeStub(i);
        if (!stub) break;
        void* target = base + g_probes[i].rva;
        if (MH_CreateHook(target, stub, &g_probes[i].original) != MH_OK) continue;
        memcpy(stub + kJumpSlot, &g_probes[i].original, 8);
        if (MH_QueueEnableHook(target) == MH_OK) ok++;
    }
    MH_ApplyQueued();
    LogLine("PROBE installed %zu of %zu", ok, g_probes.size());
}

}  // namespace probe
