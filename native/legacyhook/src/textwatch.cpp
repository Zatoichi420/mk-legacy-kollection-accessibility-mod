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
#include <algorithm>
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

bool g_saidThisFrame;  // the first thing said in a frame interrupts, the rest queue

// "{menu_accept}" -> "accept": the game draws these placeholders as button
// pictures for whichever controller is in use.
std::string SpeakablePlaceholders(const std::string& in) {
    if (in.compare(0, 19, "PRESS {menu_accept}") == 0) return "Press Enter, or A on a controller, to start";
    std::string out;
    for (size_t i = 0; i < in.size(); i++) {
        size_t end = in[i] == '{' ? in.find('}', i) : std::string::npos;
        if (end == std::string::npos) {
            out += in[i];
            continue;
        }
        std::string name = in.substr(i + 1, end - i - 1);
        if (name.compare(0, 5, "menu_") == 0) name.erase(0, 5);
        for (auto& c : name)
            if (c == '_') c = ' ';
        if (!out.empty() && out.back() != ' ') out += ' ';
        out += name + " button";
        i = end;
    }
    return out;
}

DWORD g_lastSayTick;
DWORD g_screenTextTick;       // when a new screen's heading/question was last said
int g_frameNumber;            // frame being finished
int g_lastItemFrame = -100;   // when the last selected item was announced
std::string g_lastItemText;

// queue: speak after whatever is being said instead of cutting it off.
void Say(const std::string& raw, bool queue = false) {
    std::string text = SpeakablePlaceholders(raw);
    if (text == g_lastSaid) return;
    g_lastSaid = text;
    bool interrupt = !g_saidThisFrame && !queue;
    g_saidThisFrame = true;
    g_lastSayTick = GetTickCount();
    LogLine("SAY%s %s", interrupt ? "!" : " ", text.c_str());
    if (!g_muted) speech::Say(text, interrupt);
}

// Single texts worth reading: not button-glyph placeholders like
// "{menu_cancel}", not bare numbers (timers, counters).
// Valid UTF-8 with no control characters (some call sites pass things
// that aren't text at all).
bool LooksLikeText(const std::string& t) {
    bool alnum = false;
    for (size_t i = 0; i < t.size();) {
        unsigned char c = (unsigned char)t[i];
        int extra = c < 0x80 ? 0 : (c >> 5) == 6 ? 1 : (c >> 4) == 14 ? 2 : (c >> 3) == 30 ? 3 : -1;
        if (extra < 0 || i + extra >= t.size() + (extra ? 0 : 1)) return false;
        if (extra == 0 && c < 0x20) return false;
        for (int k = 1; k <= extra; k++)
            if (((unsigned char)t[i + k] >> 6) != 2) return false;
        if (extra == 0 && isalnum(c)) alnum = true;
        if (extra) alnum = true;
        i += extra + 1;
    }
    return alnum;
}

bool Readable(const std::string& t) {
    if (t.empty() || t[0] == '{' || !LooksLikeText(t)) return false;
    if (t.size() == 4 && (t[0] == '1' || t[0] == '2') && isdigit((unsigned char)t[1]) && isdigit((unsigned char)t[2]) &&
        isdigit((unsigned char)t[3]))
        return true;  // a year: the Game Library tells versions apart by it
    for (char c : t)
        if (!isdigit((unsigned char)c) && c != ':' && c != '.' && c != ' ' && c != '%') return true;
    return false;
}

std::map<uintptr_t, int> g_siteMaxCount;          // call site -> most texts it has drawn in a frame
std::map<uintptr_t, int> g_siteAge;               // call site -> frames running it has drawn text
std::map<uintptr_t, std::string> g_prevSingles;  // single-text call sites last frame -> text
std::map<uintptr_t, std::string> g_singleSaid;   // what was last spoken for each
const uint32_t kHeadingStyle = 8;                // "GAME OPTIONS", "PLAY", "GAME LIBRARY"
const uint32_t kValueStyle = 11;                 // a setting's value: "ON", "ENGLISH"

void Announce(uintptr_t site, const std::string& text) {
    std::string& last = g_lastSelected[site];
    if (text == last) return;
    last = text;
    // Right after a new screen's heading or question, queue behind it.
    Say(text, g_screenTextTick && GetTickCount() - g_screenTextTick < 1500);
    g_screenTextTick = 0;
    g_lastItemFrame = g_frameNumber;
    g_lastItemText = text;
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
    g_saidThisFrame = false;
    // How many frames running each call site has drawn text. A list that
    // only just appeared waits a frame, so the new screen's heading and
    // texts (a pop-up's question) are said before its selected item.
    std::map<uintptr_t, int> age;
    for (auto& [site, n] : textCount) {
        auto it = g_siteAge.find(site);
        age[site] = it == g_siteAge.end() ? 0 : it->second + 1;
    }

    // 3a. Single texts (a call site that made exactly one text this frame):
    // headings of a screen that just appeared go first, other texts (the
    // selected game's name, descriptions) after the selected item.
    std::map<uintptr_t, std::string> singles;
    std::vector<const Event*> headings, newInfos, infos;
    for (auto& [site, n] : textCount) g_siteMaxCount[site] = (std::max)(g_siteMaxCount[site], n);  // parenthesised: windows.h defines max
    for (size_t k = 0; k < ev.size(); k++) {
        const Event& e = ev[k];
        if (!e.isText || textCount[e.site] != 1) continue;
        // A list that shrank to one item isn't a heading or a description:
        // the button-hint bar ("BACK") does this when options disappear.
        if (g_siteMaxCount[e.site] > 1) continue;
        singles[e.site] = e.text;
        // A text between two items of one list is an item's value ("OFF");
        // it's read with its item.
        const Event *before = nullptr, *after = nullptr;
        for (size_t j = k; j-- > 0;)
            if (ev[j].isText) { before = &ev[j]; break; }
        for (size_t j = k + 1; j < ev.size(); j++)
            if (ev[j].isText) { after = &ev[j]; break; }
        if (e.style == kValueStyle && before && after && before->site == after->site && textCount[before->site] >= 3)
            continue;
        auto prev = g_prevSingles.find(e.site);
        bool appeared = prev == g_prevSingles.end();
        bool settled = !appeared && prev->second == e.text;  // same two frames running
        if (!Readable(e.text) || e.text == g_singleSaid[e.site]) continue;
        // Value-style text alone is a value seen mid-build ("ENGLISH"), unless
        // it's long enough to be a description.
        if (e.style == kValueStyle && e.text.size() < 20) continue;
        if ((appeared || settled) && e.style == kHeadingStyle) headings.push_back(&e);  // includes a title replaced in place
        else if (settled) (age[e.site] <= 2 ? newInfos : infos).push_back(&e);
    }
    g_frameNumber = f.number;
    bool itemJustSaid = f.number - g_lastItemFrame <= 5;
    for (auto* e : headings) {
        g_singleSaid[e->site] = e->text;
        Say(e->text);
        g_screenTextTick = GetTickCount();
    }
    if (!headings.empty() && itemJustSaid) {
        // The screen's heading arrived a frame or two after its first
        // item: say the item again after the heading.
        g_lastSaid.clear();
        Say(g_lastItemText, true);
    }
    for (auto* e : newInfos) {  // a new screen's other texts: a pop-up's question
        g_singleSaid[e->site] = e->text;
        Say(e->text, g_screenTextTick && GetTickCount() - g_screenTextTick < 1500);
        g_screenTextTick = GetTickCount();
    }

    // 1. A list whose selected item has its own style.
    for (auto& [site, counts] : styles) {
        if (age[site] == 0 || counts.size() != 2) continue;
        // Two-item lists (a pop-up's NO / YES) use the main menu's pair:
        // 7 selected, 6 not.
        bool pair = textCount[site] == 2 && counts.count(7) && counts.count(6);
        if (textCount[site] < 3 && !pair) continue;
        for (auto& e : ev)
            if (e.isText && e.site == site && (pair ? e.style == 7 : counts[e.style] == 1)) {
                Announce(site, e.text);
                handled[site] = true;
            }
    }

    // 4. A list whose items are each followed by a colour, the selected one
    // in its own colour (game menu: gold FFF1AD2B among translucent blue).
    for (auto& [site, n] : textCount) {
        if (n < 3 || age[site] == 0 || handled[site] || styles[site].size() != 1 || styles[site].count(kValueStyle))
            continue;  // a column of values is never the menu
        std::vector<std::pair<size_t, uint32_t>> itemColor;  // item event index, colour after it
        std::map<uint32_t, int> colorUse;
        for (size_t i = 0; i < ev.size(); i++) {
            if (!ev[i].isText || ev[i].site != site) continue;
            for (size_t j = i + 1; j < ev.size() && !(ev[j].isText && ev[j].site == site); j++)
                if (!ev[j].isText) {
                    itemColor.push_back({i, ev[j].style});
                    colorUse[ev[j].style]++;
                    break;
                }
        }
        if ((int)itemColor.size() != n || colorUse.size() != 2) continue;
        for (auto& [idx, color] : itemColor)
            if (colorUse[color] == 1) {
                std::string spoken = ev[idx].text;
                for (size_t j = idx + 1; j < ev.size(); j++) {
                    if (!ev[j].isText) continue;
                    if (ev[j].site != site && ev[j].style == kValueStyle) {
                        spoken += ", " + ev[j].text;
                        handled[ev[j].site] = true;
                    }
                    break;
                }
                Announce(site, spoken);
                handled[site] = true;
            }
    }

    // 2. A list whose selected item is followed by a one-off highlight colour.
    for (size_t i = 1; i < ev.size(); i++) {
        const Event& c = ev[i];
        if (c.isText || colorCount[c.site] != 1) continue;
        const Event& item = ev[i - 1];
        if (!item.isText || textCount[item.site] < 3 || age[item.site] == 0 || handled[item.site] ||
            styles[item.site].size() != 1 || item.style == kValueStyle)
            continue;
        std::string spoken = item.text;
        for (size_t j = i + 1; j < ev.size(); j++) {
            if (!ev[j].isText) continue;
            if (ev[j].site != item.site && ev[j].style == kValueStyle) {
                spoken += ", " + ev[j].text;  // its value
                handled[ev[j].site] = true;   // the value's own highlight isn't another list
            }
            break;
        }
        Announce(item.site, spoken);
        handled[item.site] = true;
    }

    // 3b. Other single texts that changed.
    for (auto* e : infos) {
        if (handled[e->site]) continue;
        g_singleSaid[e->site] = e->text;
        Say(e->text, GetTickCount() - g_lastSayTick < 1000);  // don't cut off the item it describes
    }
    g_prevSingles = singles;
    g_siteAge = age;

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
    if (!CopyText((const char*)text, buf, sizeof(buf)) || !LooksLikeText(buf)) return;
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
    if (probe::TraceOn()) LogLine("COL  site %llx argb %08llx", (unsigned long long)CallSite(frame), (unsigned long long)argb);
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
