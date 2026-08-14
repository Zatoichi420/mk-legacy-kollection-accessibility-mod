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

' WMI can transiently fail (service hiccup, slow first query right after
' boot, permissions). Without error handling, an unhandled error here
' aborts the whole script before shell.Run below ever runs - the reader
' silently never launches, with nothing to tell the user why. Treat any
' WMI failure as "couldn't tell, assume not running" (worst case is a
' harmless duplicate reader) rather than letting it block the launch.
On Error Resume Next
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
If Err.Number = 0 Then
    Set procs = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name='python.exe'")
    If Err.Number = 0 Then
        For Each proc In procs
            If Not IsNull(proc.CommandLine) Then
                If InStr(1, proc.CommandLine, "ocr_reader", vbTextCompare) > 0 _
                    And InStr(1, proc.CommandLine, "main.py", vbTextCompare) > 0 Then
                    alreadyRunning = True
                End If
            End If
        Next
    End If
End If
Err.Clear
On Error Goto 0

If Not alreadyRunning Then
    If fso.FileExists(batPath) Then
        shell.Run """" & batPath & """", 0, False
    End If
End If
