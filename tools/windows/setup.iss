#if VER < EncodeVer(6, 3, 0)
  #error Inno Setup 6.3 or newer is required
#endif
#ifndef SourceRoot
  #error SourceRoot is required
#endif
#ifndef PortableRoot
  #error PortableRoot is required
#endif

[Setup]
AppId={{D11A3D54-EDC4-4FD6-8A61-662AFB09A722}
AppName=A2Router
AppVersion=0.1.0
AppPublisher=A2Router contributors
AppPublisherURL=https://github.com/vkr-6/A2Router
DefaultDirName={localappdata}\Programs\A2Router
DefaultGroupName=A2Router
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
OutputBaseFilename=a2router-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
UsePreviousTasks=no
LicenseFile={#SourceRoot}\LICENSE
InfoBeforeFile={#SourceRoot}\LICENSING.md
InfoAfterFile={#SourceRoot}\vendor\vbcable\NOTICE.txt
SetupIconFile={#PortableRoot}\a2router.ico
UninstallDisplayIcon={app}\a2router.exe

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
Name: startmenuicon; Description: "Create a Start menu shortcut"
Name: launchapp; Description: "Launch A2Router after setup"; Flags: unchecked
Name: vbcable; Description: "Install VB-CABLE by VB-Audio Software (shared audio driver; administrator approval)"; Flags: unchecked

[Files]
Source: "{#PortableRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\A2Router"; Filename: "{app}\a2router.exe"; Tasks: desktopicon
Name: "{userprograms}\A2Router\A2Router"; Filename: "{app}\a2router.exe"; Tasks: startmenuicon

[Run]
Filename: "{app}\a2router.exe"; Tasks: launchapp; Flags: nowait runasoriginaluser skipifsilent

[Code]
var
  RemoveSharedDriver: Boolean;
  DriverNeedsRestart: Boolean;

procedure RunDriverOperation(Remove: Boolean);
var
  Parameters: String;
  ExitCode: Integer;
begin
  Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\vendor\install-vbcable.ps1') +
    '" -Directory "' + ExpandConstant('{app}\vendor\vb-cable') + '"';
  if Remove then Parameters := Parameters + ' -Uninstall';
  if not ShellExec('runas', ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Parameters, ExpandConstant('{app}\vendor'), SW_SHOWNORMAL, ewWaitUntilTerminated, ExitCode) then
    MsgBox('Driver operation was cancelled or could not start. The shared driver was not confirmed changed. ' + SysErrorMessage(ExitCode), mbError, MB_OK)
  else if ExitCode = 3010 then
    DriverNeedsRestart := True
  else if ExitCode <> 0 then
    MsgBox('VB-CABLE operation failed verification. A2Router remains separate from the shared driver. Review the vendor installer and %TEMP%\A2Router-VBCABLE-install.log. Exit code: ' + IntToStr(ExitCode), mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('vbcable') then
    RunDriverOperation(False);
end;

function NeedRestart(): Boolean;
begin
  Result := DriverNeedsRestart;
end;

function InitializeUninstall(): Boolean;
var
  Form: TSetupForm;
  Choice: TNewCheckBox;
  Description: TNewStaticText;
  ContinueButton, CancelButton: TNewButton;
begin
  RemoveSharedDriver := False;
  Result := True;
  if UninstallSilent then Exit;
#if VER >= EncodeVer(6, 6, 0)
  Form := CreateCustomForm(ScaleX(460), ScaleY(210), False, False);
#else
  Form := CreateCustomForm;
  Form.ClientWidth := ScaleX(460);
  Form.ClientHeight := ScaleY(210);
#endif
  try
    Form.Caption := 'Remove A2Router';
    Description := TNewStaticText.Create(Form);
    Description.Parent := Form;
    Description.SetBounds(ScaleX(20), ScaleY(18), ScaleX(420), ScaleY(66));
    Description.AutoSize := False;
    Description.WordWrap := True;
    Description.Caption := 'The application will be removed. VB-CABLE is shared by other applications. Leave it installed unless you explicitly want to remove it. Close audio applications first. Saved profiles are retained.';
    Choice := TNewCheckBox.Create(Form);
    Choice.Parent := Form;
    Choice.SetBounds(ScaleX(20), ScaleY(96), ScaleX(420), ScaleY(32));
    Choice.Caption := 'Also remove the shared VB-CABLE driver';
    Choice.Checked := False;
    ContinueButton := TNewButton.Create(Form);
    ContinueButton.Parent := Form;
    ContinueButton.SetBounds(ScaleX(252), ScaleY(162), ScaleX(90), ScaleY(26));
    ContinueButton.Caption := 'Uninstall';
    ContinueButton.Default := True;
    ContinueButton.ModalResult := mrOk;
    CancelButton := TNewButton.Create(Form);
    CancelButton.Parent := Form;
    CancelButton.SetBounds(ScaleX(350), ScaleY(162), ScaleX(90), ScaleY(26));
    CancelButton.Caption := 'Cancel';
    CancelButton.Cancel := True;
    CancelButton.ModalResult := mrCancel;
    Result := Form.ShowModal = mrOk;
    if Result then RemoveSharedDriver := Choice.Checked;
  finally
    Form.Free;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usUninstall) and RemoveSharedDriver then
    RunDriverOperation(True);
end;

function UninstallNeedRestart(): Boolean;
begin
  Result := DriverNeedsRestart;
end;
