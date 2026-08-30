#include "log.h"

#include <windows.h>
#include <cstdio>
#include <ctime>
#include <string>
#include <mutex>

static std::wstring GetLogPath()
{
    HMODULE hSelf = nullptr;
    // UNCHANGED_REFCOUNT: without it, FROM_ADDRESS increments the module's
    // reference count on every call - and this runs on every LogLine() call,
    // i.e. every frame-1 and every-600th-frame log for the life of the
    // process, leaking one reference each time. Code executing from within
    // this module already guarantees it can't unload out from under us, so
    // there's nothing to pin.
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(&GetLogPath),
        &hSelf);

    wchar_t modulePath[MAX_PATH] = {};
    GetModuleFileNameW(hSelf, modulePath, MAX_PATH);
    std::wstring path(modulePath);
    size_t slash = path.find_last_of(L"\\/");
    std::wstring dir = (slash == std::wstring::npos) ? L"" : path.substr(0, slash + 1);
    return dir + L"mk_accessibility.log";
}

void LogLine(const char* message)
{
    static std::mutex logMutex;
    std::lock_guard<std::mutex> lock(logMutex);

    FILE* f = nullptr;
    if (_wfopen_s(&f, GetLogPath().c_str(), L"a") == 0 && f)
    {
        time_t now = time(nullptr);
        char timeBuf[32] = {};
        ctime_s(timeBuf, sizeof(timeBuf), &now);
        for (char* p = timeBuf; *p; ++p) { if (*p == '\n') *p = '\0'; }
        fprintf(f, "[%s] %s\n", timeBuf, message);
        fclose(f);
    }
}
