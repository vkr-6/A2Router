#ifndef AppDist
  #error AppDist is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef NoticeFile
  #error NoticeFile is required
#endif
[Setup]
AppId={{2F68E65A-6C67-43B1-B6F5-9B059F48196D}
AppName=A2Router
AppVersion=0.1.0
AppPublisher=A2Router contributors
DefaultDirName={autopf}\A2Router
DefaultGroupName=A2Router
OutputDir={#OutputDir}
OutputBaseFilename=A2Router-Setup-x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
PrivilegesRequired=admin
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
InfoBeforeFile={#NoticeFile}
LicenseFile={#AppDist}\vendor\vb-cable\readme.txt
CloseApplications=yes
UninstallDisplayIcon={app}\a2router.exe

[Tasks]
Name: "vbcable"; Description: "Install VB-CABLE by VB-Audio if absent (donationware; restart required)"; Flags: checkedonce

[Files]
Source: "{#AppDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
Type: files; Name: "{app}\vendor\vbcable-installed-by-a2router.flag"

[Icons]
Name: "{group}\A2Router"; Filename: "{app}\a2router.exe"
Name: "{group}\VB-CABLE donation and licensing"; Filename: "https://vb-audio.com/Services/licensing.htm"

[Run]
Filename: "{app}\a2router.exe"; Description: "Launch A2Router"; Flags: postinstall nowait skipifsilent runasoriginaluser; Check: CanLaunch

[Code]
var
  DriverNeedsRestart: Boolean;
  DriverFailed: Boolean;
  UninstallDriverNeedsRestart: Boolean;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
  Parameters: String;
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('vbcable') then begin
    Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{app}\vendor\install-vbcable.ps1') + '" -Directory "' +
      ExpandConstant('{app}\vendor\vb-cable') + '" -StateFile "' +
      ExpandConstant('{app}\vendor\vbcable-installed-by-a2router.flag') + '"';
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Parameters, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then begin
      DriverFailed := True;
    end else begin
      DriverNeedsRestart := ExitCode = 3010;
      DriverFailed := (ExitCode <> 0) and (ExitCode <> 3010);
    end;
    if DriverFailed then begin
      Log('VB-CABLE installation failed; application files installed, driver unavailable.');
      SuppressibleMsgBox('A2Router was installed, but VB-CABLE installation failed. ' +
        'Review %TEMP%\A2Router-VBCABLE-install.log, then use the bundled VB-CABLE vendor installer. ' +
        'No driver success is claimed.', mbError, MB_OK, IDOK);
    end;
  end;
end;

function NeedRestart(): Boolean;
begin
  Result := DriverNeedsRestart;
end;

function CanLaunch(): Boolean;
begin
  Result := not DriverNeedsRestart and not DriverFailed;
end;

function GetCustomSetupExitCode(): Integer;
begin
  if DriverFailed then Result := 1 else Result := 0;
end;

function InitializeUninstall(): Boolean;
var
  RemoveDriver, Owned: Boolean;
  Answer, ExitCode: Integer;
  Parameters, Explanation: String;
begin
  Result := True;
  Owned := FileExists(ExpandConstant('{app}\vendor\vbcable-installed-by-a2router.flag'));
  RemoveDriver := ExpandConstant('{param:REMOVEVBCABLE|0}') = '1';
  if not UninstallSilent and not RemoveDriver then begin
    Explanation := 'Also uninstall the shared VB-CABLE audio driver? Other applications may use it. ' +
      'Close audio applications before continuing. Removal requires restarting Windows.';
    if Owned then
      Answer := MsgBox('A2Router installed VB-CABLE. ' + Explanation, mbConfirmation, MB_YESNOCANCEL or MB_DEFBUTTON1)
    else
      Answer := MsgBox('VB-CABLE was pre-existing or its ownership is unknown. ' + Explanation, mbConfirmation, MB_YESNOCANCEL or MB_DEFBUTTON2);
    if Answer = IDCANCEL then begin
      Result := False;
      Exit;
    end;
    RemoveDriver := Answer = IDYES;
  end;
  if RemoveDriver then begin
    Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{app}\vendor\install-vbcable.ps1') + '" -Directory "' +
      ExpandConstant('{app}\vendor\vb-cable') + '" -StateFile "' +
      ExpandConstant('{app}\vendor\vbcable-installed-by-a2router.flag') + '" -Uninstall';
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Parameters,
      '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then begin
      Result := False;
    end else begin
      Result := (ExitCode = 0) or (ExitCode = 3010);
      UninstallDriverNeedsRestart := ExitCode = 3010;
    end;
    if not Result then
      SuppressibleMsgBox('VB-CABLE removal failed. A2Router has been kept so its vendor installer remains available. ' +
        'See %TEMP%\A2Router-VBCABLE-install.log. Retry after restarting, or choose No to remove only A2Router.',
        mbError, MB_OK, IDOK);
  end;
end;

function UninstallNeedRestart(): Boolean;
begin
  Result := UninstallDriverNeedsRestart;
end;
