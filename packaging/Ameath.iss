#define AppName "爱弥斯"
#ifndef AppVersion
  #error AppVersion must be supplied by packaging/build_release.py
#endif
#ifndef AppGuid
  #define AppGuid "8E3B2B32-263F-4605-91B7-DC8CA146B4A0"
#endif
#ifndef StageDir
  #define StageDir "build\\installer\\offline"
#endif

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=NingYan678
AppPublisherURL=https://github.com/NingYan678/ameath-desktop
AppSupportURL=https://github.com/NingYan678/ameath-desktop/issues
AppUpdatesURL=https://github.com/NingYan678/ameath-desktop/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Ameath
DisableDirPage=no
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=Ameath-{#AppVersion}-offline-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\app\Ameath.exe
CloseApplications=force
CloseApplicationsFilter=Ameath.exe
RestartApplications=no

[InstallDelete]
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\licenses"

[Files]
Source: "{#StageDir}\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs ignoreversion
Source: "{#StageDir}\runtime\*"; DestDir: "{app}\runtime"; Flags: recursesubdirs ignoreversion
Source: "{#StageDir}\licenses\*"; DestDir: "{app}\licenses"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\爱弥斯"; Filename: "{app}\app\Ameath.exe"
Name: "{autodesktop}\启动爱弥斯"; Filename: "{app}\app\Ameath.exe"

[Run]
Filename: "{app}\app\Ameath.exe"; Description: "安装完成后启动爱弥斯"; Flags: nowait postinstall skipifsilent

[Code]
var
  DeleteData: Boolean;
  IsDowngrade: Boolean;
  ResetDowngradeDataPage: TInputOptionWizardPage;

function VersionPart(Version: string; Index: Integer): Integer;
var
  I, Separator, Suffix: Integer;
  Part: string;
begin
  for I := 1 to Index - 1 do
  begin
    Separator := Pos('.', Version);
    if Separator = 0 then
      Version := ''
    else
      Delete(Version, 1, Separator);
  end;
  Separator := Pos('.', Version);
  if Separator = 0 then
    Part := Version
  else
    Part := Copy(Version, 1, Separator - 1);
  Suffix := Pos('-', Part);
  if Suffix > 0 then
    Part := Copy(Part, 1, Suffix - 1);
  Result := StrToIntDef(Part, 0);
end;

function CompareVersions(LeftVersion, RightVersion: string): Integer;
var
  Index, LeftPart, RightPart: Integer;
begin
  Result := 0;
  for Index := 1 to 3 do
  begin
    LeftPart := VersionPart(LeftVersion, Index);
    RightPart := VersionPart(RightVersion, Index);
    if LeftPart < RightPart then
    begin
      Result := -1;
      Exit;
    end;
    if LeftPart > RightPart then
    begin
      Result := 1;
      Exit;
    end;
  end;
end;

function InitializeSetup(): Boolean;
var
  InstalledVersion: string;
begin
  IsDowngrade := RegQueryStringValue(
    HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{' + '{#AppGuid}' + '}_is1',
    'DisplayVersion',
    InstalledVersion) and (CompareVersions('{#AppVersion}', InstalledVersion) < 0);
  Result := not IsDowngrade or
    (MsgBox(
      '检测到已安装版本 ' + InstalledVersion + '，高于当前安装包 {#AppVersion}。' + #13#10 + #13#10 +
      '降级可能导致旧程序无法理解新版数据。是否仍要继续？',
      mbConfirmation, MB_YESNO) = IDYES);
end;

procedure InitializeWizard();
begin
  ResetDowngradeDataPage := CreateInputOptionPage(
    wpSelectDir,
    '降级数据处理',
    '选择如何处理现有爱弥斯数据',
    '默认保留设置、状态和凭据。只有需要完全重新配置时才选择重置。',
    True, False);
  ResetDowngradeDataPage.Add('重置 %LOCALAPPDATA%\Ameath 中的爱弥斯用户数据');
  ResetDowngradeDataPage.Values[0] := False;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = ResetDowngradeDataPage.ID) and not IsDowngrade;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
begin
  if (CurStep = ssPostInstall) and IsDowngrade and ResetDowngradeDataPage.Values[0] then
  begin
    if (not Exec(ExpandConstant('{app}\app\Ameath.exe'), '--reset-data', '', SW_HIDE,
      ewWaitUntilTerminated, ExitCode)) or (ExitCode <> 0) then
      MsgBox(
        '无法安全重置用户数据。程序文件已完成安装，但原数据已保留。请退出正在运行的独立 Hermes Gateway 后重试。',
        mbError, MB_OK);
  end;
end;

procedure InitializeUninstallProgressForm();
begin
  if UninstallSilent then
    DeleteData := False
  else
    DeleteData := MsgBox('是否同时删除爱弥斯的个人数据、记忆和已保存的模型凭据？选择“否”可在以后重新安装时恢复。', mbConfirmation, MB_YESNO) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ExitCode: Integer;
begin
  if (CurUninstallStep = usUninstall) and DeleteData then
  begin
    if (not Exec(ExpandConstant('{app}\app\Ameath.exe'), '--reset-data', '', SW_HIDE,
      ewWaitUntilTerminated, ExitCode)) or (ExitCode <> 0) then
    begin
      DeleteData := False;
      MsgBox('无法安全删除用户数据；数据已保留。', mbError, MB_OK);
    end;
  end;
end;
