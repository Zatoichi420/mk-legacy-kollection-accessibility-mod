// This DLL is placed alongside mk_legacy_kollection.exe as "dinput8.dll",
// so Windows' DLL search order loads it instead of the real system one.
// On load it locates the real system dinput8.dll (expected to be copied
// into the game folder as "dinput8_orig.dll"), grabs pointers to its six
// exports, and re-exports thin pass-through stubs with the same names so
// game input keeps working unmodified. A background thread then installs
// the Present hook (see present_hook.cpp) so we get a callback synced to
// the game's render loop.

#include "log.h"
#include "present_hook.h"

#include <windows.h>
#include <string>

typedef HRESULT(WINAPI* DirectInput8Create_t)(void*, unsigned long, void*, void*, void*);
typedef HRESULT(WINAPI* DllCanUnloadNow_t)(void);
typedef HRESULT(WINAPI* DllGetClassObject_t)(void*, void*, void*);
typedef HRESULT(WINAPI* DllRegisterServer_t)(void);
typedef HRESULT(WINAPI* DllUnregisterServer_t)(void);
typedef void* (WINAPI* GetdfDIJoystick_t)(void);

static DirectInput8Create_t   real_DirectInput8Create = nullptr;
static DllCanUnloadNow_t      real_DllCanUnloadNow = nullptr;
static DllGetClassObject_t    real_DllGetClassObject = nullptr;
static DllRegisterServer_t    real_DllRegisterServer = nullptr;
static DllUnregisterServer_t  real_DllUnregisterServer = nullptr;
static GetdfDIJoystick_t      real_GetdfDIJoystick = nullptr;

static std::wstring GetSelfDirectory(HMODULE hSelf)
{
    wchar_t modulePath[MAX_PATH] = {};
    GetModuleFileNameW(hSelf, modulePath, MAX_PATH);
    std::wstring path(modulePath);
    size_t slash = path.find_last_of(L"\\/");
    return (slash == std::wstring::npos) ? L"" : path.substr(0, slash + 1);
}

// WARNING for anyone re-enabling this DLL in the future (it is currently
// DISABLED - see proxy_dll/README.md): this proxy is only safe to load as
// "dinput8.dll" in the game folder if a copy of the real system DLL is
// ALSO present there as "dinput8_orig.dll". That file no longer exists
// anywhere in the game folder or this repo (removed when the proxy was
// disabled during the 2026-08-14 audit). Without it, LoadLibraryW below
// fails, every real_* pointer stays null, every exported function returns
// a failure code for the rest of the process's life, and gamepad/
// DirectInput input silently breaks - with only the one log line below as
// any indication anything went wrong. Restore dinput8_orig.dll (a plain
// copy of the real Windows dinput8.dll) before ever re-enabling this.
static void LoadRealDinput8(HMODULE hSelf)
{
    std::wstring dir = GetSelfDirectory(hSelf);
    std::wstring realPath = dir + L"dinput8_orig.dll";

    HMODULE hReal = LoadLibraryW(realPath.c_str());
    if (!hReal)
    {
        LogLine("ERROR: could not load dinput8_orig.dll - input pass-through will fail!");
        return;
    }

    real_DirectInput8Create  = reinterpret_cast<DirectInput8Create_t>(GetProcAddress(hReal, "DirectInput8Create"));
    real_DllCanUnloadNow     = reinterpret_cast<DllCanUnloadNow_t>(GetProcAddress(hReal, "DllCanUnloadNow"));
    real_DllGetClassObject   = reinterpret_cast<DllGetClassObject_t>(GetProcAddress(hReal, "DllGetClassObject"));
    real_DllRegisterServer   = reinterpret_cast<DllRegisterServer_t>(GetProcAddress(hReal, "DllRegisterServer"));
    real_DllUnregisterServer = reinterpret_cast<DllUnregisterServer_t>(GetProcAddress(hReal, "DllUnregisterServer"));
    real_GetdfDIJoystick     = reinterpret_cast<GetdfDIJoystick_t>(GetProcAddress(hReal, "GetdfDIJoystick"));

    LogLine("mk_accessibility proxy dinput8.dll loaded into host process; real dinput8_orig.dll resolved.");
}

static DWORD WINAPI InitThread(LPVOID)
{
    // Only the Present hook's D3D11 device creation needs to be off-thread
    // (see the comment in DllMain below) - InstallPresentHook itself
    // guards against being usefully callable before this runs.
    InstallPresentHook();
    return 0;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH)
    {
        DisableThreadLibraryCalls(hModule);

        // Resolve the real DirectInput8 exports synchronously, before
        // DllMain returns. This must happen before any other code in the
        // process can call our exported stubs (DirectInput8Create etc.) -
        // previously this ran on the same background thread as the Present
        // hook, which meant the exports could be called (returning E_FAIL,
        // silently breaking gamepad input for the whole session) before
        // real_DirectInput8Create was resolved, a race whose outcome
        // depended purely on thread scheduling. LoadLibrary/GetProcAddress
        // against a plain system-style DLL is the safe case the loader-lock
        // guidance is fine with; only D3D11 device creation for the Present
        // hook (below) risks deadlocking under the loader lock, so only
        // that part stays deferred to a background thread.
        LoadRealDinput8(hModule);

        HANDLE hThread = CreateThread(nullptr, 0, InitThread, nullptr, 0, nullptr);
        if (hThread) CloseHandle(hThread);
    }
    else if (reason == DLL_PROCESS_DETACH)
    {
        UninstallPresentHook();
    }
    return TRUE;
}

extern "C" __declspec(dllexport) HRESULT WINAPI DirectInput8Create(void* a1, unsigned long a2, void* a3, void* a4, void* a5)
{
    return real_DirectInput8Create ? real_DirectInput8Create(a1, a2, a3, a4, a5) : E_FAIL;
}

// DllCanUnloadNow/DllGetClassObject are pre-declared by <combaseapi.h> with
// plain (non-dllexport) linkage, so redefining them directly under
// __declspec(dllexport) conflicts. Implement under different names and
// re-export via linker pragma instead.
extern "C" HRESULT WINAPI Hook_DllCanUnloadNow(void)
{
    return real_DllCanUnloadNow ? real_DllCanUnloadNow() : E_FAIL;
}

extern "C" HRESULT WINAPI Hook_DllGetClassObject(REFCLSID rclsid, REFIID riid, LPVOID* ppv)
{
    return real_DllGetClassObject ? real_DllGetClassObject((void*)&rclsid, (void*)&riid, ppv) : E_FAIL;
}

#pragma comment(linker, "/export:DllCanUnloadNow=Hook_DllCanUnloadNow")
#pragma comment(linker, "/export:DllGetClassObject=Hook_DllGetClassObject")

extern "C" __declspec(dllexport) HRESULT WINAPI DllRegisterServer()
{
    return real_DllRegisterServer ? real_DllRegisterServer() : E_FAIL;
}

extern "C" __declspec(dllexport) HRESULT WINAPI DllUnregisterServer()
{
    return real_DllUnregisterServer ? real_DllUnregisterServer() : E_FAIL;
}

extern "C" __declspec(dllexport) void* WINAPI GetdfDIJoystick()
{
    return real_GetdfDIJoystick ? real_GetdfDIJoystick() : nullptr;
}
