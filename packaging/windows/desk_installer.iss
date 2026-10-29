; Inno Setup script for YTKTV Desk. Build with:
;   iscc /DAppVersion=1.0.0 packaging\windows\desk_installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{C2E7A1D4-3F6B-4E58-9A21-7D0B5E4C8F13}
AppName=YTKTV Desk
AppVersion={#AppVersion}
AppPublisher=TonyD365
AppPublisherURL=https://github.com/TonyD365/YTKTV
DefaultDirName={autopf}\YTKTV Desk
DefaultGroupName=YTKTV Desk
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=YTKTV-Desk-{#AppVersion}-windows-x64-setup
SetupIconFile=..\..\build\desk-icon\icon.ico
UninstallDisplayIcon={app}\YTKTV Desk.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\..\dist\YTKTV Desk\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\YTKTV Desk"; Filename: "{app}\YTKTV Desk.exe"
Name: "{autodesktop}\YTKTV Desk"; Filename: "{app}\YTKTV Desk.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\YTKTV Desk.exe"; Description: "Launch YTKTV Desk"; Flags: nowait postinstall
