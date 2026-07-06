#include "present_hook.h"
#include "log.h"

#include <windows.h>
#include <d3d11.h>
#include <dxgi.h>
#include <MinHook.h>
#include <atomic>
#include <cstdint>
#include <cstdio>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")

typedef HRESULT(STDMETHODCALLTYPE* Present_t)(IDXGISwapChain*, UINT, UINT);
static Present_t oPresent = nullptr;
static std::atomic<uint64_t> g_frameCount{ 0 };
static std::atomic<bool> g_hookInstalled{ false };

static HRESULT STDMETHODCALLTYPE HookedPresent(IDXGISwapChain* swapChain, UINT syncInterval, UINT flags)
{
    uint64_t n = ++g_frameCount;
    if (n == 1)
    {
        LogLine("Present hook: first frame observed - render loop callback is alive.");
        DXGI_SWAP_CHAIN_DESC desc = {};
        if (SUCCEEDED(swapChain->GetDesc(&desc)))
        {
            char buf[128];
            sprintf_s(buf, "Present hook: real swapchain buffer size = %u x %u (format=%d, windowed=%d)",
                desc.BufferDesc.Width, desc.BufferDesc.Height, (int)desc.BufferDesc.Format, desc.Windowed);
            LogLine(buf);
        }
    }
    else if (n % 600 == 0)
    {
        char buf[128];
        sprintf_s(buf, "Present hook: %llu frames observed.", static_cast<unsigned long long>(n));
        LogLine(buf);
    }
    return oPresent(swapChain, syncInterval, flags);
}

// Creates a throwaway D3D11 device + swapchain purely to read the real
// IDXGISwapChain::Present function pointer out of its vtable, then tears
// the dummy objects down. The vtable is shared process-wide by the DXGI
// runtime, so hooking this one address affects the game's real swapchain
// too, whether the game itself renders via D3D11 or D3D12.
static bool GetRealPresentAddress(void** outAddress)
{
    WNDCLASSEXW wc = { sizeof(WNDCLASSEXW) };
    wc.lpfnWndProc = DefWindowProcW;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.lpszClassName = L"mk_access_dummy_wnd";
    RegisterClassExW(&wc);

    HWND hwnd = CreateWindowExW(0, wc.lpszClassName, L"", WS_OVERLAPPEDWINDOW,
        0, 0, 64, 64, nullptr, nullptr, wc.hInstance, nullptr);
    if (!hwnd)
    {
        LogLine("Present hook: failed to create dummy window.");
        return false;
    }

    DXGI_SWAP_CHAIN_DESC scd = {};
    scd.BufferCount = 1;
    scd.BufferDesc.Width = 2;
    scd.BufferDesc.Height = 2;
    scd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    scd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    scd.OutputWindow = hwnd;
    scd.SampleDesc.Count = 1;
    scd.Windowed = TRUE;
    scd.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;

    IDXGISwapChain* swapChain = nullptr;
    ID3D11Device* device = nullptr;
    ID3D11DeviceContext* context = nullptr;
    D3D_FEATURE_LEVEL level;

    HRESULT hr = D3D11CreateDeviceAndSwapChain(
        nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0,
        nullptr, 0, D3D11_SDK_VERSION, &scd,
        &swapChain, &device, &level, &context);

    bool ok = false;
    if (SUCCEEDED(hr) && swapChain)
    {
        void** vtable = *reinterpret_cast<void***>(swapChain);
        *outAddress = vtable[8]; // IDXGISwapChain::Present
        ok = true;
    }
    else
    {
        char buf[64];
        sprintf_s(buf, "Present hook: dummy device creation failed, hr=0x%08X", static_cast<unsigned int>(hr));
        LogLine(buf);
    }

    if (context) context->Release();
    if (swapChain) swapChain->Release();
    if (device) device->Release();
    DestroyWindow(hwnd);
    UnregisterClassW(wc.lpszClassName, wc.hInstance);

    return ok;
}

void InstallPresentHook()
{
    if (g_hookInstalled.exchange(true))
        return;

    void* presentAddr = nullptr;
    if (!GetRealPresentAddress(&presentAddr))
        return;

    if (MH_Initialize() != MH_OK)
    {
        LogLine("Present hook: MH_Initialize failed.");
        return;
    }

    if (MH_CreateHook(presentAddr, &HookedPresent, reinterpret_cast<void**>(&oPresent)) != MH_OK)
    {
        LogLine("Present hook: MH_CreateHook failed.");
        return;
    }

    if (MH_EnableHook(presentAddr) != MH_OK)
    {
        LogLine("Present hook: MH_EnableHook failed.");
        return;
    }

    LogLine("Present hook: installed successfully.");
}
