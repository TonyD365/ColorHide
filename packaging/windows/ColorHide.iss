; Inno Setup script: ColorHide-<tag>-windows-x64-setup.exe from dist\ColorHide
;   iscc /DAppVersion=1.2.3 /DTag=v1.2.3 packaging\windows\ColorHide.iss
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
AppName=ColorHide
AppVersion={#AppVersion}
AppVerName=ColorHide {#AppVersion}
AppPublisher=ColorHide contributors
AppPublisherURL=https://github.com/TonyD365/ColorHide
AppSupportURL=https://github.com/TonyD365/ColorHide/issues
AppUpdatesURL=https://github.com/TonyD365/ColorHide/releases
DefaultDirName={autopf}\ColorHide
DefaultGroupName=ColorHide
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
LicenseFile=..\..\LICENSE
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\ColorHide.exe
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
OutputDir=..\..
OutputBaseFilename=ColorHide-{#Tag}-windows-x64-setup

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\ColorHide\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; a clean program folder on upgrade, so files removed in a new version don't linger
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\ColorHide"; Filename: "{app}\ColorHide.exe"
Name: "{autodesktop}\ColorHide"; Filename: "{app}\ColorHide.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ColorHide.exe"; Description: "{cm:LaunchProgram,ColorHide}"; Flags: nowait postinstall skipifsilent
; in-app updates run the installer silently with /UPDATE: start the new version afterwards
Filename: "{app}\ColorHide.exe"; Flags: nowait; Check: IsUpdate

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
