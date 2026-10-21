// Screen-reader output for the MK9 hook: NVDA, then JAWS, then the Windows
// voice (SAPI). All speech runs on one worker thread, so callers on the
// game's threads never wait for a screen reader.
#pragma once
#include <string>

namespace speech {

// Starts the worker thread. dllDir is where nvdaControllerClient.dll lives.
void Start(const std::wstring& dllDir);

// Queues text (UTF-8). interrupt=true cancels whatever is being spoken first.
void Say(const std::string& utf8, bool interrupt);

// Which voice is in use right now: "NVDA", "JAWS", "SAPI" or "none".
const char* Backend();

}  // namespace speech
