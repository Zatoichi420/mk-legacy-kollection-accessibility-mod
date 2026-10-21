// MK Legacy Kollection accessibility hook.
//
// Loaded by the game as dinput8.dll (a proxy that forwards to the real one).
// The launcher's menus are Lua scripts run by Digital Eclipse's UI engine
// (docs/NATIVE-UI-ANALYSIS.md). Stage 1, this file: hook lua_load and save a
// copy of every script the game loads, so the menus can be studied. It is
// read-only and silent.
//
// Output, next to mk_legacy_kollection.exe:
//   legacyhook_log.txt       what was hooked and loaded
//   legacyhook_scripts\      one file per loaded chunk

#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include "MinHook.h"

// ---------------------------------------------------------------- dinput8 proxy

typedef HRESULT(WINAPI* DirectInput8Create_t)(HINSTANCE, DWORD, REFIID, LPVOID*, void*);
static DirectInput8Create_t g_realDirectInput8Create;

extern "C" HRESULT WINAPI Proxy_DirectInput8Create(HINSTANCE inst, DWORD ver, REFIID riid, LPVOID* out, void* outer) {
    if (!g_realDirectInput8Create) {
        wchar_t path[MAX_PATH];
        GetSystemDirectoryW(path, MAX_PATH);
        wcscat_s(path, L"\\dinput8.dll");
        if (HMODULE real = LoadLibraryW(path))
            g_realDirectInput8Create = (DirectInput8Create_t)GetProcAddress(real, "DirectInput8Create");
    }
    return g_realDirectInput8Create ? g_realDirectInput8Create(inst, ver, riid, out, outer) : E_FAIL;
}

// ---------------------------------------------------------------- log

static CRITICAL_SECTION g_logLock;
static FILE* g_log;
static DWORD g_startTick;
static std::wstring g_gameDir;

void LogLine(const char* fmt, ...) {
    if (!g_log) return;
    EnterCriticalSection(&g_logLock);
    DWORD t = GetTickCount() - g_startTick;
    fprintf(g_log, "%6lu.%03lu ", t / 1000, t % 1000);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);
    LeaveCriticalSection(&g_logLock);
}

// ---------------------------------------------------------------- lua_load

// int lua_load(lua_State* L, lua_Reader reader, void* data, const char* chunkname, const char* mode)
typedef const char* (*lua_Reader)(void* L, void* ud, size_t* size);
typedef int (*lua_load_t)(void* L, lua_Reader reader, void* data, const char* chunkname, const char* mode);
static lua_load_t o_lua_load;
static void* g_mainState;  // first lua_State seen; stage 2 runs code in it

struct Capture {
    lua_Reader reader;
    void* data;
    std::string bytes;
};

// Passes the game's chunk through unchanged, keeping a copy.
static const char* CaptureReader(void* L, void* ud, size_t* size) {
    Capture* c = (Capture*)ud;
    const char* p = c->reader(L, c->data, size);
    if (p && *size) c->bytes.append(p, *size);
    return p;
}

static void SaveChunk(const char* chunkname, const std::string& bytes) {
    // "@ui/functions.lua" -> legacyhook_scripts\ui_functions.lua
    std::string name = chunkname ? chunkname : "unnamed";
    if (!name.empty() && (name[0] == '@' || name[0] == '=')) name.erase(0, 1);
    for (auto& ch : name)
        if (ch == '/' || ch == '\\' || ch == ':' || ch == '*' || ch == '?' || ch == '"' || ch == '<' || ch == '>' ||
            ch == '|' || (unsigned char)ch < 32)
            ch = '_';
    if (name.size() > 120) name.resize(120);
    bool binary = !bytes.empty() && bytes[0] == 0x1B;  // precompiled ("\x1bLua")
    if (binary && name.size() > 4 && name.compare(name.size() - 4, 4, ".lua") == 0) name += "c";
    std::wstring dir = g_gameDir + L"\\legacyhook_scripts";
    CreateDirectoryW(dir.c_str(), nullptr);
    std::wstring path = dir + L"\\" + std::wstring(name.begin(), name.end());
    if (GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES) return;  // first copy wins
    FILE* f = _wfsopen(path.c_str(), L"wb", _SH_DENYWR);
    if (!f) return;
    fwrite(bytes.data(), 1, bytes.size(), f);
    fclose(f);
}

static int h_lua_load(void* L, lua_Reader reader, void* data, const char* chunkname, const char* mode) {
    if (!g_mainState) g_mainState = L;
    Capture c{reader, data, {}};
    int status = o_lua_load(L, CaptureReader, &c, chunkname, mode);
    LogLine("LOAD %s (%zu bytes, status %d, state %p)", chunkname ? chunkname : "(null)", c.bytes.size(), status, L);
    SaveChunk(chunkname, c.bytes);
    return status;
}

namespace probe {
void Install(const std::wstring& gameDir, uint8_t* base);
}
namespace textwatch {
void Install(const std::wstring& gameDir, uint8_t* base);
}

// ---------------------------------------------------------------- install

struct Target {
    const char* name;
    uintptr_t rva;
    uint8_t sig[16];
    void* detour;
    void** original;
};

// mk_legacy_kollection.exe, PE timestamp 1775170048 (2026-04 Steam build).
static Target g_targets[] = {
    {"lua_load", 0x2171F0,
     {0x48, 0x89, 0x5C, 0x24, 0x10, 0x57, 0x48, 0x83, 0xEC, 0x50, 0x49, 0x8B, 0xD9, 0x48, 0x8B, 0xF9},
     (void*)h_lua_load, (void**)&o_lua_load},
};
static const DWORD kExpectedTimestamp = 1775170048;

static DWORD WINAPI InstallThread(LPVOID) {
    uint8_t* base = (uint8_t*)GetModuleHandleW(nullptr);
    auto nt = (IMAGE_NT_HEADERS64*)(base + ((IMAGE_DOS_HEADER*)base)->e_lfanew);
    if (nt->FileHeader.TimeDateStamp != kExpectedTimestamp) {
        LogLine("Unexpected game build (timestamp %lu); no hooks installed.", nt->FileHeader.TimeDateStamp);
        return 0;
    }
    for (auto& t : g_targets) {
        uint8_t* addr = base + t.rva;
        bool hasSig = false;
        for (uint8_t b : t.sig) hasSig |= b != 0;
        if (hasSig && memcmp(addr, t.sig, sizeof(t.sig)) != 0) {
            LogLine("SKIP %s: bytes don't match", t.name);
            continue;
        }
        MH_STATUS s = MH_CreateHook(addr, t.detour, t.original);
        if (s == MH_OK) s = MH_QueueEnableHook(addr);
        LogLine("HOOK %s at %p: %s", t.name, addr, MH_StatusToString(s));
    }
    textwatch::Install(g_gameDir, base);  // speaks the selected menu item
    probe::Install(g_gameDir, base);      // developer probes, only with legacyhook_probe.txt
    LogLine("Enabling hooks: %s", MH_StatusToString(MH_ApplyQueued()));
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID) {
    if (reason != DLL_PROCESS_ATTACH) return TRUE;
    DisableThreadLibraryCalls(inst);
    wchar_t exePath[MAX_PATH];
    GetModuleFileNameW(nullptr, exePath, MAX_PATH);
    const wchar_t* exeName = wcsrchr(exePath, L'\\');
    if (!exeName || _wcsicmp(exeName + 1, L"mk_legacy_kollection.exe") != 0) return TRUE;
    InitializeCriticalSection(&g_logLock);
    g_startTick = GetTickCount();
    g_gameDir.assign(exePath, exeName - exePath);
    g_log = _wfsopen((g_gameDir + L"\\legacyhook_log.txt").c_str(), L"a", _SH_DENYWR);
    LogLine("---- legacyhook stage 1 (script capture) started ----");
    // The game loads its first scripts early, so hook from DllMain's thread
    // as soon as possible; MinHook's setup is safe under the loader lock.
    if (MH_Initialize() != MH_OK) {
        LogLine("MinHook failed to start.");
        return TRUE;
    }
    InstallThread(nullptr);
    return TRUE;
}
