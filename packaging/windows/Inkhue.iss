; Inno Setup script: Inkhue-<tag>-windows-x64-setup.exe from dist\Inkhue
;   iscc /DAppVersion=1.2.3 /DTag=v1.2.3 packaging\windows\Inkhue.iss
; Installs for the current user by default (no admin, so the app can update itself);
; the first page lets the user pick "all users" (Program Files) instead.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Tag
  #define Tag "v" + AppVersion
#endif

[Setup]
AppId={{6F2B8C4E-3D7A-4E1B-9A55-C0104C1D3E77}
AppName=Inkhue
AppVersion={#AppVersion}
AppVerName=Inkhue {#AppVersion}
AppPublisher=Inkhue contributors
AppPublisherURL=https://github.com/TonyD365/Inkhue
AppSupportURL=https://github.com/TonyD365/Inkhue/issues
AppUpdatesURL=https://github.com/TonyD365/Inkhue/releases
DefaultDirName={autopf}\Inkhue
DefaultGroupName=Inkhue
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
LicenseFile=..\..\LICENSE
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\Inkhue.exe
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
OutputDir=..\..
OutputBaseFilename=Inkhue-{#Tag}-windows-x64-setup

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\Inkhue\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; a clean program folder on upgrade, so files removed in a new version don't linger
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Inkhue"; Filename: "{app}\Inkhue.exe"
Name: "{autodesktop}\Inkhue"; Filename: "{app}\Inkhue.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Inkhue.exe"; Description: "{cm:LaunchProgram,Inkhue}"; Flags: nowait postinstall skipifsilent
; in-app updates run the installer silently with /UPDATE: start the new version afterwards
Filename: "{app}\Inkhue.exe"; Flags: nowait; Check: IsUpdate

[Code]
function IsUpdate: Boolean;
var
  i: Integer;
begin
  Result := False;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), '/UPDATE') = 0 then
      Result := True;
end;
