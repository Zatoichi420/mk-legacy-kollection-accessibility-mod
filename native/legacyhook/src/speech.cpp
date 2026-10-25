#include "speech.h"

#include <windows.h>
#include <sapi.h>
#include <deque>
#include <mutex>
#include <condition_variable>

namespace speech {
namespace {

typedef unsigned long(__stdcall* NvdaTest_t)();
typedef unsigned long(__stdcall* NvdaSpeak_t)(const wchar_t*);
typedef unsigned long(__stdcall* NvdaCancel_t)();

NvdaTest_t nvdaTest;
NvdaSpeak_t nvdaSpeak;
NvdaCancel_t nvdaCancel;

IDispatch* jaws;
DISPID jawsSayString = DISPID_UNKNOWN;
DISPID jawsStop = DISPID_UNKNOWN;
ISpVoice* sapi;

struct Item {
    std::wstring text;
    bool interrupt;
};
std::deque<Item> queue;
std::mutex lock;
std::condition_variable wake;
std::wstring nvdaPath;
volatile const char* backend = "none";

std::wstring Widen(const std::string& s) {
    if (s.empty()) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0);
    std::wstring w(n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), &w[0], n);
    return w;
}

void LoadNvda() {
    HMODULE m = LoadLibraryW(nvdaPath.c_str());
    if (!m) return;
    nvdaTest = (NvdaTest_t)GetProcAddress(m, "nvdaController_testIfRunning");
    nvdaSpeak = (NvdaSpeak_t)GetProcAddress(m, "nvdaController_speakText");
    nvdaCancel = (NvdaCancel_t)GetProcAddress(m, "nvdaController_cancelSpeech");
}

bool JawsRunning() { return FindWindowW(L"JFWUI2", nullptr) != nullptr; }

void ConnectJaws() {
    if (jaws) return;
    CLSID clsid;
    if (FAILED(CLSIDFromProgID(L"FreedomSci.JawsApi", &clsid))) return;
    if (FAILED(CoCreateInstance(clsid, nullptr, CLSCTX_ALL, IID_IDispatch, (void**)&jaws))) { jaws = nullptr; return; }
    LPOLESTR say = (LPOLESTR)L"SayString", stop = (LPOLESTR)L"StopString";
    jaws->GetIDsOfNames(IID_NULL, &say, 1, LOCALE_USER_DEFAULT, &jawsSayString);
    jaws->GetIDsOfNames(IID_NULL, &stop, 1, LOCALE_USER_DEFAULT, &jawsStop);
}

void JawsSay(const std::wstring& text, bool interrupt) {
    if (jawsSayString == DISPID_UNKNOWN) return;
    // Arguments go in reverse order: SayString(text, flush).
    VARIANT args[2];
    VariantInit(&args[0]);
    args[0].vt = VT_BOOL;
    args[0].boolVal = interrupt ? VARIANT_TRUE : VARIANT_FALSE;
    VariantInit(&args[1]);
    args[1].vt = VT_BSTR;
    args[1].bstrVal = SysAllocString(text.c_str());
    DISPPARAMS p = {args, nullptr, 2, 0};
    jaws->Invoke(jawsSayString, IID_NULL, LOCALE_USER_DEFAULT, DISPATCH_METHOD, &p, nullptr, nullptr, nullptr);
    SysFreeString(args[1].bstrVal);
}

void Speak(const Item& item) {
    // Pick the backend per utterance, so starting or quitting a screen
    // reader mid-game switches voice without a restart.
    if (nvdaTest && nvdaTest() == 0) {
        backend = "NVDA";
        if (item.interrupt) nvdaCancel();
        nvdaSpeak(item.text.c_str());
        return;
    }
    if (JawsRunning()) {
        ConnectJaws();
        if (jaws) {
            backend = "JAWS";
            JawsSay(item.text, item.interrupt);
            return;
        }
    }
    if (!sapi) CoCreateInstance(CLSID_SpVoice, nullptr, CLSCTX_ALL, IID_ISpVoice, (void**)&sapi);
    if (sapi) {
        backend = "SAPI";
        DWORD flags = SPF_ASYNC | (item.interrupt ? SPF_PURGEBEFORESPEAK : 0);
        sapi->Speak(item.text.c_str(), flags, nullptr);
        return;
    }
    backend = "none";
}

DWORD WINAPI Worker(LPVOID) {
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    LoadNvda();
    for (;;) {
        Item item;
        {
            std::unique_lock<std::mutex> g(lock);
            wake.wait(g, [] { return !queue.empty(); });
            item = std::move(queue.front());
            queue.pop_front();
        }
        Speak(item);
    }
}

}  // namespace

void Start(const std::wstring& dllDir) {
    nvdaPath = dllDir + L"\\nvdaControllerClient.dll";
    CreateThread(nullptr, 0, Worker, nullptr, 0, nullptr);
}

void Say(const std::string& utf8, bool interrupt) {
    if (utf8.empty()) return;
    std::lock_guard<std::mutex> g(lock);
    if (interrupt) queue.clear();
    queue.push_back({Widen(utf8), interrupt});
    wake.notify_one();
}

const char* Backend() { return (const char*)backend; }

}  // namespace speech
