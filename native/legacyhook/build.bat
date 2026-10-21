@echo off
rem Builds the 64-bit dinput8.dll proxy into native\legacyhook\out.
setlocal
set VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat
if not exist "%VCVARS%" set VCVARS=C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvarsall.bat
call "%VCVARS%" amd64 >nul || exit /b 1
cd /d "%~dp0"
if not exist out mkdir out
set MH=third_party\minhook
set LIBS=user32.lib kernel32.lib ole32.lib oleaut32.lib
cl /nologo /O2 /MT /EHsc /std:c++17 /W3 /DWIN32_LEAN_AND_MEAN /I %MH%\include ^
  src\dllmain.cpp src\probe.cpp src\textwatch.cpp src\speech.cpp %MH%\src\hook.c %MH%\src\buffer.c %MH%\src\trampoline.c %MH%\src\hde\hde64.c ^
  /LD /Fo"out\\" /Fe"out\dinput8.dll" /link /DEF:src\exports.def %LIBS% || exit /b 1
copy /y third_party\nvda\nvdaControllerClient.dll out\ >nul
echo Built out\dinput8.dll
