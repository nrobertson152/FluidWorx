; Inno Setup 6 script for FluidWorx (Windows x64). Compile with /DMyAppVersion=<version> after building dist\FluidWorx.
#define MyAppName "FluidWorx"
#ifndef MyAppVersion
  #error "Provide version using /DMyAppVersion=<application version>"
#endif
#define MyAppExeName "FluidWorx.exe"

[Setup]
AppId={{B7A4D1E6-2C0F-4E8B-A5D3-91F6C2E07A34}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Nate Robertson
AppSupportURL=https://ko-fi.com/nr270343
AppCopyright=Copyright (C) 2026 Nate Robertson
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=FluidWorx-{#MyAppVersion}-Setup-x64
SetupIconFile=..\fluidworx\resources\fluidworx.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "assoc"; Description: "Open .fluidworx studies with FluidWorx"; GroupDescription: "File types:"

[Files]
Source: "..\dist\FluidWorx\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.fluidworx"; ValueType: string; ValueData: "FluidWorx.Study"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\FluidWorx.Study"; ValueType: string; ValueData: "FluidWorx study"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\FluidWorx.Study\DefaultIcon"; ValueType: string; ValueData: "{app}\{#MyAppExeName},0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\FluidWorx.Study\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
