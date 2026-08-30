#pragma once

// Installs a MinHook detour on IDXGISwapChain::Present so we get a callback
// synced to every rendered frame, regardless of whether the game is using
// its D3D11 or D3D12 backend (both go through the same DXGI swapchain
// Present entry point). Call once, from a thread (not DllMain).
void InstallPresentHook();

// Disables the detour and uninitializes MinHook. Call from
// DLL_PROCESS_DETACH if the hook was ever installed - without this, an
// explicit FreeLibrary of this DLL while still hooked would leave the
// MinHook trampoline pointing at code inside an unloaded module, a
// use-after-free on the next Present call. No-op if never installed.
void UninstallPresentHook();
