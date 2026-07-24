#define AppName "爱弥斯"
#define AppVersion "1.0.0"
#ifndef BuildMode
  #define BuildMode "offline"
#endif
#ifndef StageDir
  #define StageDir "build\\installer\\offline"
#endif

[Setup]
AppId={{8E3B2B32-263F-4605-91B7-DC8CA146B4A0}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Personal use only
DefaultDirName={localappdata}\Programs\Ameath
DisableDirPage=no
UsePreviousAppDir=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=Ameath-{#BuildMode}-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\app\Ameath.exe

[Files]
Source: "{#StageDir}\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs ignoreversion
Source: "{#StageDir}\runtime\*"; DestDir: "{app}\runtime"; Flags: recursesubdirs ignoreversion
Source: "{#StageDir}\licenses\*"; DestDir: "{app}\licenses"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\爱弥斯"; Filename: "{app}\app\Ameath.exe"
Name: "{autodesktop}\启动爱弥斯"; Filename: "{app}\app\Ameath.exe"

[Run]
#if BuildMode == "online"
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\runtime\runtime-bootstrap.ps1"""; StatusMsg: "正在下载并验证爱弥斯运行环境…"; Flags: waituntilterminated
#endif
Filename: "{app}\app\Ameath.exe"; Description: "安装完成后启动爱弥斯"; Flags: nowait postinstall skipifsilent

[Code]
var DeleteData: Boolean;

procedure InitializeUninstallProgressForm();
begin
  DeleteData := MsgBox('是否同时删除爱弥斯的个人数据、记忆和已保存的模型凭据？选择“否”可在以后重新安装时恢复。', mbConfirmation, MB_YESNO) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DeleteData then
    DelTree(ExpandConstant('{localappdata}\Ameath'), True, True, True);
end;
