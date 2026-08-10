; Inno Setup script for RO Workbench Windows installer
; Build: iscc installer.iss

#define MyAppName "RO Workbench"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "RO Workbench"

[Setup]
AppId={{B8F4A3D2-7E6C-4A1B-9D5F-2C8E7A3B6D1F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\..\dist
OutputBaseFilename=RO-Workbench-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog

[Files]
Source: "..\..\dist\RO Workbench.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\RO Workbench"; Filename: "{app}\RO Workbench.exe"
Name: "{group}\Uninstall RO Workbench"; Filename: "{uninstallexe}"
Name: "{autodesktop}\RO Workbench"; Filename: "{app}\RO Workbench.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\RO Workbench.exe"; Description: "Launch RO Workbench"; Flags: nowait postinstall skipifsilent
