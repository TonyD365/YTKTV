; Inno Setup script for YTKTV. Build with:
;   iscc /DAppVersion=1.0.0 packaging\windows\installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; /DArch=arm64 for Windows on ARM; x64 otherwise.
#ifndef Arch
  #define Arch "x64"
#endif

[Setup]
AppId={{6B0C5B0E-6C1B-4D0B-9E0F-59A7C0E6B2A1}
AppName=YTKTV
AppVersion={#AppVersion}
AppPublisher=TonyD365
AppPublisherURL=https://github.com/TonyD365/YTKTV
DefaultDirName={autopf}\YTKTV
DefaultGroupName=YTKTV
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
#if Arch == "arm64"
ArchitecturesAllowed=arm64
ArchitecturesInstallIn64BitMode=arm64
#else
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif
OutputDir=..\..\dist
OutputBaseFilename=YTKTV-{#AppVersion}-windows-{#Arch}-setup
SetupIconFile=..\..\build\icon\icon.ico
UninstallDisplayIcon={app}\YTKTV.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Lets the auto-updater replace a running copy and start it again.
CloseApplications=yes
RestartApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\..\dist\YTKTV\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\YTKTV"; Filename: "{app}\YTKTV.exe"
Name: "{autodesktop}\YTKTV"; Filename: "{app}\YTKTV.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\YTKTV.exe"; Description: "Launch YTKTV"; Flags: nowait postinstall
