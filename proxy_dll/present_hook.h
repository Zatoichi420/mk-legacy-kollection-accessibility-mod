#pragma once

// Installs a MinHook detour on IDXGISwapChain::Present so we get a callback
// synced to every rendered frame, regardless of whether the game is using
// its D3D11 or D3D12 backend (both go through the same DXGI swapchain
// Present entry point). Call once, from a thread (not DllMain).
void InstallPresentHook();
