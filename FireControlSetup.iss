#define MyAppName "Fire Control"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "WildCode Studios"
#define MyAppExeName "Fire Control.exe"

[Setup]
AppId={{A8B3B4D1-7D2C-4E89-9E9D-4A4F9E8C1000}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=
AppSupportURL=
AppUpdatesURL=
DefaultDirName={autopf}\Fire Control
DefaultGroupName=Fire Control
DisableProgramGroupPage=yes
OutputDir=C:\Users\sindh\Documents\codes\pcapp\output
OutputBaseFilename=FireControlSetup_x64
SetupIconFile=C:\Users\sindh\Documents\codes\pcapp\fire_control.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
VersionInfoCompany=WildCode Studios
VersionInfoDescription=Fire Control Installer
VersionInfoProductName=Fire Control
VersionInfoProductVersion=1.0.0
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "startup"; Description: "Start Fire Control with Windows"; GroupDescription: "Startup options:"; Flags: checkedonce

[Files]
Source: "C:\Users\sindh\Documents\codes\pcapp\dist\Fire Control\Fire Control.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\Users\sindh\Documents\codes\pcapp\dist\Fire Control\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Fire Control"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Fire Control"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Fire Control"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Fire Control"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/F /IM ""{#MyAppExeName}"""; Flags: runhidden

[InstallDelete]
Type: filesandordirs; Name: "{app}"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"