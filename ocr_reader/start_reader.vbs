' Launched from Steam's launch options (see PROGRESS.md) so the
' accessibility reader starts automatically whenever the game is launched.
' Skips starting a second copy if one is already running (e.g. game was
' relaunched while the reader from a previous session is still alive).
Option Explicit

Dim shell, fso, scriptDir, batPath, wmi, procs, proc, alreadyRunning

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\run_reader.bat"

alreadyRunning = False
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name='python.exe'")
For Each proc In procs
    If Not IsNull(proc.CommandLine) Then
        If InStr(1, proc.CommandLine, "ocr_reader", vbTextCompare) > 0 _
            And InStr(1, proc.CommandLine, "main.py", vbTextCompare) > 0 Then
            alreadyRunning = True
        End If
    End If
Next

If Not alreadyRunning Then
    shell.Run """" & batPath & """", 0, False
End If
