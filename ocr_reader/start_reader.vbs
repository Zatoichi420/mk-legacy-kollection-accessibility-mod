' Launched from Steam's launch options (see PROGRESS.md) so the
' accessibility reader starts automatically whenever the game is launched.
'
' Duplicate-instance protection now lives in main.py itself (a PID lock
' file, see acquire_single_instance_lock/release_single_instance_lock)
' rather than here. This script used to query WMI in advance for a
' matching python.exe command line and skip launching if one was found -
' but that meant any WMI failure (not just a transient hiccup; a
' persistently unavailable WMI service) fell back to "assume nothing's
' running," which could launch a second reader on top of an existing one,
' with both talking over each other on NVDA. The PID lock file has no such
' dependency and correctly detects a stale lock (process no longer alive)
' left behind even by a hard kill - so this script no longer needs to
' guess in advance. If another reader already holds the lock, the new
' one just exits immediately, before ever touching NVDA.
Option Explicit
Dim shell, fso, scriptDir, batPath

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\run_reader.bat"

If fso.FileExists(batPath) Then
    shell.Run """" & batPath & """", 0, False
End If
