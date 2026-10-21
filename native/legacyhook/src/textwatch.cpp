// Stage 2: speak the selected menu item.
//
// The launcher's menus are rebuilt every frame through the UI engine's C++
// functions (the ones its Lua bindings wrap):
//   text create  RVA 0x145BC0  rcx = UI, edx = style number, r9 = UTF-8 text, xmm1 = y
//   set color    RVA 0x139720  rcx = UI, edx = ARGB; applies to the element just made
// Each frame's text and colour calls are recorded in order, keyed by call
// site (the return address), and the selected item is found two ways:
//   1. Style: a menu's items come from one call site and the selected one
//      has its own style number (main menu: 7 vs 6).
//   2. Highlight colour: in menus whose items share a style (Options), the
//      selected item is the only one followed by a colour call from a call
//      site used once per frame. The next text after it from another call
//      site, before the next item, is its value ("MENU MUSIC, ON").
// Frames are told apart with Dear ImGui's frame counter, which the game
// still advances every frame.

#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <map>
#include <string>
#include <vector>
#include "MinHook.h"
#include "speech.h"

void LogLine(const char* fmt, ...);
namespace probe {
bool TraceOn();
}

namespace textwatch {
namespace {

const uintptr_t kTextCreateRva = 0x145BC0;
const uint8_t kTextCreateSig[] = {0x4C, 0x89, 0x44, 0x24, 0x18, 0x4C, 0x89, 0x4C, 0x24, 0x20, 0x48, 0x83, 0xEC, 0x38};
const uintptr_t kSetColorRva = 0x139720;
const uint8_t kSetColorSig[] = {0x48, 0x63, 0x41, 0x4C, 0x4C, 0x69, 0xC0, 0x98, 0x00, 0x00, 0x00};
const uintptr_t kImGuiContextRva = 0xDC8D80;  // GImGui
const size_t kFrameCountOffset = 4400;         // ImGuiContext::FrameCount in this build

uint8_t* g_base;
bool g_muted;
bool g_logFrames;  // legacyhook_frames.txt present: log each new screen's texts

struct Event {
    bool isText;
    uintptr_t site;  // call site, as an RVA
    uint32_t style;  // text: style number; colour: ARGB
    std::string text;
};
struct Frame {
    int number = -1;
    std::vector<Event> events;
};
Frame g_cur;
CRITICAL_SECTION g_lock;  // the game could create UI text from more than one thread
std::map<uintptr_t, std::string> g_lastSelected;  // item call site -> last selected text
std::string g_lastShape;
std::string g_lastSaid;

int ReadFrameCount() {
    __try {
        uint8_t* ctx = *(uint8_t**)(g_base + kImGuiContextRva);
        return ctx ? *(int*)(ctx + kFrameCountOffset) : -1;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return -1;
    }
}

bool CopyText(const char* p, char* out, size_t cap) {
    size_t n = 0;
    __try {
        for (; n + 1 < cap && p[n]; n++) out[n] = p[n];
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
    out[n] = 0;
    return n > 0;
}

void Say(const std::string& text) {
    if (text == g_lastSaid) return;
    g_lastSaid = text;
    LogLine("SAY! %s", text.c_str());
    if (!g_muted) speech::Say(text, true);
}

void Announce(uintptr_t site, const std::string& text) {
    std::string& last = g_lastSelected[site];
    if (text == last) return;
    last = text;
    Say(text);
}

// Called when a new frame starts, with everything the last one drew.
void FinishFrame(const Frame& f) {
    const auto& ev = f.events;
    std::map<uintptr_t, int> textCount, colorCount;
    std::map<uintptr_t, std::map<uint32_t, int>> styles;
    for (auto& e : ev) {
        if (e.isText) {
            textCount[e.site]++;
            styles[e.site][e.style]++;
        } else {
            colorCount[e.site]++;
        }
    }
    std::map<uintptr_t, bool> handled;

    // 1. A list whose selected item has its own style.
    for (auto& [site, counts] : styles) {
        if (textCount[site] < 3 || counts.size() != 2) continue;
        for (auto& e : ev)
            if (e.isText && e.site == site && counts[e.style] == 1) {
                Announce(site, e.text);
                handled[site] = true;
            }
    }

    // 2. A list whose selected item is followed by a one-off highlight colour.
    for (size_t i = 1; i < ev.size(); i++) {
        const Event& c = ev[i];
        if (c.isText || colorCount[c.site] != 1) continue;
        const Event& item = ev[i - 1];
        if (!item.isText || textCount[item.site] < 3 || handled[item.site] || styles[item.site].size() != 1) continue;
        std::string spoken = item.text;
        for (size_t j = i + 1; j < ev.size(); j++) {
            if (!ev[j].isText) continue;
            if (ev[j].site != item.site) {
                spoken += ", " + ev[j].text;  // its value
                handled[ev[j].site] = true;   // the value's own highlight isn't another list
            }
            break;
        }
        Announce(item.site, spoken);
        handled[item.site] = true;
    }

    if (g_logFrames) {
        std::string shape;
        for (auto& [site, n] : textCount) shape += std::to_string(site) + ":" + std::to_string(n) + ";";
        if (shape != g_lastShape) {
            // A new screen (different call sites or item counts): log its texts.
            LogLine("SCREEN frame %d", f.number);
            std::map<uintptr_t, std::string> lines;
            for (auto& e : ev)
                if (e.isText) lines[e.site] += " [" + std::to_string(e.style) + "] " + e.text + " |";
            for (auto& [site, line] : lines) LogLine("  site %llx:%s", (unsigned long long)site, line.c_str());
        }
        g_lastShape = shape;
    }
}

void NextFrameIfNeeded() {
    int fc = ReadFrameCount();
    if (fc == g_cur.number) return;
    if (g_cur.number >= 0) FinishFrame(g_cur);
    g_cur.events.clear();
    g_cur.number = fc;
}

uintptr_t CallSite(const uint8_t* frame) { return *(const uintptr_t*)(frame + 0xA8) - (uintptr_t)g_base; }

}  // namespace

// From the stubs, on the game's UI thread.
extern "C" void TextCreateHit(uintptr_t ui, uintptr_t style, uintptr_t r8, uintptr_t text, const uint8_t* frame) {
    char buf[256];
    if (!CopyText((const char*)text, buf, sizeof(buf))) return;
    uintptr_t site = CallSite(frame);
    EnterCriticalSection(&g_lock);
    NextFrameIfNeeded();
    g_cur.events.push_back({true, site, (uint32_t)style, buf});
    LeaveCriticalSection(&g_lock);
    if (probe::TraceOn())
        LogLine("TXT  site %llx style %llu \"%s\"", (unsigned long long)site, (unsigned long long)style, buf);
}

extern "C" void SetColorHit(uintptr_t ui, uintptr_t argb, uintptr_t r8, uintptr_t r9, const uint8_t* frame) {
    EnterCriticalSection(&g_lock);
    NextFrameIfNeeded();
    g_cur.events.push_back({false, CallSite(frame), (uint32_t)argb, {}});
    LeaveCriticalSection(&g_lock);
}

namespace {

// Stub: save argument registers, call hit(rcx, rdx, r8, r9, frame), restore,
// jump to the original. frame + 0xA8 holds the caller's return address.
uint8_t* MakeStub(void* hit) {
    uint8_t* s = (uint8_t*)VirtualAlloc(nullptr, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    const uint8_t code[] = {
        0x51, 0x52, 0x41, 0x50, 0x41, 0x51,                    // push rcx, rdx, r8, r9
        0x48, 0x81, 0xEC, 0x88, 0x00, 0x00, 0x00,              // sub rsp, 0x88
        0xF3, 0x0F, 0x7F, 0x44, 0x24, 0x30,                    // movdqu [rsp+30h], xmm0
        0xF3, 0x0F, 0x7F, 0x4C, 0x24, 0x40,                    //        [rsp+40h], xmm1
        0xF3, 0x0F, 0x7F, 0x54, 0x24, 0x50,                    //        [rsp+50h], xmm2
        0xF3, 0x0F, 0x7F, 0x5C, 0x24, 0x60,                    //        [rsp+60h], xmm3
        0x48, 0x89, 0x64, 0x24, 0x20,                          // mov [rsp+20h], rsp (5th arg: frame)
        0x48, 0xB8, 0, 0, 0, 0, 0, 0, 0, 0,                    // mov rax, hit
        0xFF, 0xD0,                                            // call rax (rcx..r9 untouched)
        0xF3, 0x0F, 0x6F, 0x44, 0x24, 0x30,
        0xF3, 0x0F, 0x6F, 0x4C, 0x24, 0x40,
        0xF3, 0x0F, 0x6F, 0x54, 0x24, 0x50,
        0xF3, 0x0F, 0x6F, 0x5C, 0x24, 0x60,
        0x48, 0x81, 0xC4, 0x88, 0x00, 0x00, 0x00,              // add rsp, 0x88
        0x41, 0x59, 0x41, 0x58, 0x5A, 0x59,                    // pop r9, r8, rdx, rcx
        0xFF, 0x25, 0, 0, 0, 0,                                // jmp [rip+0]
        0, 0, 0, 0, 0, 0, 0, 0,                                // -> original (offset 97)
    };
    static_assert(sizeof(code) == 105, "stub layout");
    memcpy(s, code, sizeof(code));
    uint64_t fn = (uint64_t)hit;
    memcpy(s + 44, &fn, 8);
    return s;
}

bool HookWithStub(const char* name, uintptr_t rva, const uint8_t* sig, size_t sigLen, void* hit) {
    void* target = g_base + rva;
    if (memcmp(target, sig, sigLen) != 0) {
        LogLine("SKIP %s: bytes don't match", name);
        return false;
    }
    uint8_t* stub = MakeStub(hit);
    void* original = nullptr;
    MH_STATUS st = MH_CreateHook(target, stub, &original);
    if (st == MH_OK) {
        memcpy(stub + 97, &original, 8);
        st = MH_QueueEnableHook(target);
    }
    LogLine("HOOK %s at %p: %s", name, target, MH_StatusToString(st));
    return st == MH_OK;
}

}  // namespace

void Install(const std::wstring& gameDir, uint8_t* base) {
    g_base = base;
    InitializeCriticalSection(&g_lock);
    std::wstring ini = gameDir + L"\\legacyhook.ini";
    g_muted = GetPrivateProfileIntW(L"speech", L"mute", 0, ini.c_str()) != 0;
    g_logFrames = GetFileAttributesW((gameDir + L"\\legacyhook_frames.txt").c_str()) != INVALID_FILE_ATTRIBUTES;
    if (!HookWithStub("text create", kTextCreateRva, kTextCreateSig, sizeof(kTextCreateSig), (void*)&TextCreateHit))
        return;
    HookWithStub("set color", kSetColorRva, kSetColorSig, sizeof(kSetColorSig), (void*)&SetColorHit);
    speech::Start(gameDir);
    LogLine("Speech %s", g_muted ? "muted (legacyhook.ini)" : "on");
}

}  // namespace textwatch
