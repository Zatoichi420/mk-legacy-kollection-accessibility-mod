; Inno Setup 6 script for the MK Legacy Kollection accessibility reader.
; Built by packaging/build.py (which passes /DAppVersion=...) after
; PyInstaller has produced dist\mk-legacy-access\ and dist\docs\README.html.
;
; Design choices:
;  - Per-user install (PrivilegesRequired=lowest) into
;    %LOCALAPPDATA%\Programs: no administrator prompt. A UAC prompt moves to
;    the secure desktop, which is one more thing a screen reader user has
;    to get through, and nothing here needs admin rights.
;  - Inno Setup's wizard is made of ordinary Windows dialogs, which NVDA,
;    JAWS and Narrator all read.
;  - "Start at sign-in" is a per-user Run registry value, so it shows up
;    (and can be turned off) in Task Manager's Startup apps too.
;  - The reader is stopped cleanly (--stop) before an upgrade overwrites
;    it and before uninstalling, so no files are left locked.

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#define AppName "MK Legacy Kollection Accessibility Reader"
#define ExeName "mk-legacy-access.exe"
; Must match AUTOSTART_VALUE_NAME in ocr_reader/main.py.
#define RunValueName "MKLegacyKollectionAccess"
; Must match DATA_DIR_NAME in ocr_reader/app_paths.py.
#define DataDirName "MKLegacyKollectionAccess"

[Setup]
AppId={{E813BC74-D7E8-47F1-B141-5F688EDA2744}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Zatoichi420
AppPublisherURL=https://github.com/Zatoichi420/mk-legacy-kollection-accessibility-mod
AppSupportURL=https://github.com/Zatoichi420/mk-legacy-kollection-accessibility-mod/issues
DefaultDirName={autopf}\MK Legacy Kollection Accessibility
DefaultGroupName=MK Legacy Kollection Accessibility
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=MK-Legacy-Kollection-Access-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#ExeName}
CloseApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "Start the reader automatically when I sign in to Windows (recommended). It stays quiet until the game is open."

[Files]
Source: "..\dist\mk-legacy-access\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\docs\README.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\NOTICE"; DestDir: "{app}"; DestName: "NOTICE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\Start accessibility reader"; Filename: "{app}\{#ExeName}"; Comment: "Start reading the game's menus aloud"
Name: "{group}\Stop accessibility reader"; Filename: "{app}\{#ExeName}"; Parameters: "--stop"; Comment: "Stop the accessibility reader"
Name: "{group}\Check accessibility reader"; Filename: "{app}\{#ExeName}"; Parameters: "--self-test"; Comment: "Check that speech and screen recognition are working"
Name: "{group}\Read me"; Filename: "{app}\README.html"
Name: "{group}\Uninstall accessibility reader"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#RunValueName}"; ValueData: """{app}\{#ExeName}"" --background"; Flags: uninsdeletevalue; Tasks: autostart
; Re-running setup with the option unticked has to remove an earlier value.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "{#RunValueName}"; Flags: deletevalue; Tasks: not autostart

[Run]
Filename: "{app}\{#ExeName}"; Description: "Start the accessibility reader now"; Flags: postinstall nowait skipifsilent
Filename: "{app}\README.html"; Description: "Open the read me"; Flags: postinstall shellexec skipifsilent unchecked

[UninstallRun]
Filename: "{app}\{#ExeName}"; Parameters: "--stop --quiet"; Flags: runhidden waituntilterminated; RunOnceId: "StopReader"

[UninstallDelete]
; The log and saved unrecognised screens. A developer's own reviewed
; known_screens\ captures in the same folder are deliberately left alone.
Type: files; Name: "{localappdata}\{#DataDirName}\reader.log"
Type: files; Name: "{localappdata}\{#DataDirName}\reader.log.old"
Type: filesandordirs; Name: "{localappdata}\{#DataDirName}\library_misses"
Type: dirifempty; Name: "{localappdata}\{#DataDirName}"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  ExistingExe: String;
begin
  { Upgrading over a running reader: ask it to stop first so its files
    aren't locked. Harmless if it isn't running. }
  ExistingExe := ExpandConstant('{app}\{#ExeName}');
  if FileExists(ExistingExe) then
    Exec(ExistingExe, '--stop --quiet', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
