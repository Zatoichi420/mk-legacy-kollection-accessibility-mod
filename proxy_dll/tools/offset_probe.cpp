// Standalone host-side tool (not part of the injected proxy DLL). Compiles
// against the real Dear ImGui 1.89.8 headers purely to compute struct
// offsets/sizes via the type definitions -- no ImGui .cpp is linked, and no
// ImGui function is ever called, so this is safe to build and run outside
// any game process.
#include <cstdio>
#include "imgui.h"
#include "imgui_internal.h"

int main()
{
    printf("sizeof(ImGuiContext)      = %zu\n", sizeof(ImGuiContext));
    printf("offsetof(Context, IO)     = %zu\n", offsetof(ImGuiContext, IO));
    printf("offsetof(Context, NavId)  = %zu\n", offsetof(ImGuiContext, NavId));
    printf("offsetof(Context, NavWindow)      = %zu\n", offsetof(ImGuiContext, NavWindow));
    printf("offsetof(Context, NavFocusScopeId)= %zu\n", offsetof(ImGuiContext, NavFocusScopeId));
    printf("offsetof(Context, Windows)        = %zu\n", offsetof(ImGuiContext, Windows));
    printf("offsetof(Context, HoveredId)      = %zu\n", offsetof(ImGuiContext, HoveredId));
    printf("offsetof(Context, ActiveId)       = %zu\n", offsetof(ImGuiContext, ActiveId));
    printf("offsetof(Context, FrameCount)     = %zu\n", offsetof(ImGuiContext, FrameCount));
    printf("offsetof(IO, DisplaySize) (within IO) = %zu\n", offsetof(ImGuiIO, DisplaySize));
    printf("offsetof(IO, Framerate)   (within IO) = %zu\n", offsetof(ImGuiIO, Framerate));
    printf("sizeof(ImGuiIO)           = %zu\n", sizeof(ImGuiIO));
    printf("--- ImGuiWindow ---\n");
    printf("sizeof(ImGuiWindow)       = %zu\n", sizeof(ImGuiWindow));
    printf("offsetof(Window, Name)    = %zu\n", offsetof(ImGuiWindow, Name));
    printf("offsetof(Window, ID)      = %zu\n", offsetof(ImGuiWindow, ID));
    printf("offsetof(Window, Active)  = %zu\n", offsetof(ImGuiWindow, Active));
    printf("--- ImVector<ImGuiWindow*> (Windows) ---\n");
    printf("sizeof(ImVector<ImGuiWindow*>) = %zu\n", sizeof(ImVector<ImGuiWindow*>));
    return 0;
}
