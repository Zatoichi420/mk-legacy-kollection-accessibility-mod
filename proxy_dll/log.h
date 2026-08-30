#pragma once

// Appends one timestamped line to mk_accessibility.log, next to this DLL.
// Safe to call from any thread.
void LogLine(const char* message);
