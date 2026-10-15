#ifndef AppVersion
  #define AppVersion GetDateTimeString('yyyy.mm.dd', '', '')
#endif
#ifndef AppPublisher
  #define AppPublisher "Video Công Thức"
#endif
#define AppName "Video Công Thức"
#define PackageDir AddBackslash(SourcePath) + "..\dist\VideoCongThuc"

[Setup]
AppId={{BA04C9A9-AF3A-4C28-9CF5-FC86E91715F1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\VideoCongThuc
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=VideoCongThuc-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
UninstallDisplayIcon={app}\VideoCongThuc.exe

; Inno Setup 6.7.3 does not ship Vietnamese.isl. Keep the English base
; for error messages, with Vietnamese text for the main installation screens.
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
SetupAppTitle=Cài đặt
SetupWindowTitle=Cài đặt - %1
ButtonBack=< &Quay lại
ButtonNext=&Tiếp tục >
ButtonInstall=&Cài đặt
ButtonCancel=&Hủy
ButtonFinish=&Hoàn tất
ButtonBrowse=&Chọn...
ButtonWizardBrowse=&Chọn...
WelcomeLabel1=Chào mừng đến với trình cài đặt [name]
WelcomeLabel2=Trình cài đặt sẽ cài [name/ver] cho tài khoản Windows hiện tại, không cần quyền quản trị.%n%nHãy đóng Video Công Thức trước khi nâng cấp. Cấu hình và dữ liệu cá nhân được giữ nguyên.
ClickNext=Nhấn Tiếp tục để tiếp tục, hoặc Hủy để thoát.
WizardSelectDir=Chọn thư mục cài đặt
SelectDirDesc=Bạn muốn cài [name] ở đâu?
SelectDirLabel3=Ứng dụng và dữ liệu cá nhân nằm trong thư mục sau. Hãy chọn thư mục mà tài khoản của bạn có quyền ghi.
SelectDirBrowseLabel=Nhấn Tiếp tục, hoặc Chọn để đổi thư mục.
WizardSelectProgramGroup=Chọn thư mục Start menu
SelectStartMenuFolderDesc=Tạo lối tắt ở đâu?
SelectStartMenuFolderLabel3=Trình cài đặt sẽ tạo lối tắt ứng dụng và tài liệu hướng dẫn trong thư mục Start menu sau.
SelectStartMenuFolderBrowseLabel=Nhấn Tiếp tục, hoặc Chọn để đổi thư mục.
WizardSelectTasks=Tùy chọn bổ sung
SelectTasksDesc=Chọn lối tắt cần tạo
SelectTasksLabel2=Chọn các tác vụ bổ sung, sau đó nhấn Tiếp tục.
WizardReady=Sẵn sàng cài đặt
ReadyLabel1=Đã sẵn sàng cài [name] trên máy tính của bạn.
ReadyLabel2a=Nhấn Cài đặt để bắt đầu, hoặc Quay lại để thay đổi lựa chọn.
ReadyLabel2b=Nhấn Cài đặt để bắt đầu.
WizardPreparing=Chuẩn bị cài đặt
PreparingDesc=Đang chuẩn bị cài [name].
WizardInstalling=Đang cài đặt
InstallingLabel=Vui lòng đợi trong khi cài [name].
FinishedHeadingLabel=Hoàn tất cài đặt [name]
FinishedLabel=Đã cài đặt [name].%n%nỨng dụng cần Microsoft Edge WebView2 Runtime. Nếu chưa có, tải tại:%nhttps://go.microsoft.com/fwlink/p/?LinkId=2124703%n%nKhi gỡ cài đặt, config, data, output và profile vẫn được giữ lại; không có hộp thoại yêu cầu xóa dữ liệu.
FinishedLabelNoIcons=Đã cài đặt [name].%n%nỨng dụng cần Microsoft Edge WebView2 Runtime:%nhttps://go.microsoft.com/fwlink/p/?LinkId=2124703%n%nGỡ cài đặt vẫn giữ config, data, output và profile.
ClickFinish=Nhấn Hoàn tất để đóng trình cài đặt.
UninstalledAll=Đã gỡ %1. Cấu hình và dữ liệu cá nhân vẫn được giữ trong thư mục cài đặt.

[CustomMessages]
DesktopIcon=Tạo biểu tượng trên màn hình Desktop
RunApp=Chạy Video Công Thức
UserGuide=Hướng dẫn sử dụng Video Công Thức

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"

[InstallDelete]
; Replace bundled application files, never the adjacent user-owned folders.
Type: filesandordirs; Name: "{app}\app"

[Files]
Source: "{#PackageDir}\VideoCongThuc.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PackageDir}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PackageDir}\config\*"; DestDir: "{app}\config"; Flags: onlyifdoesntexist uninsneveruninstall recursesubdirs createallsubdirs
Source: "{#PackageDir}\HUONG-DAN.pdf"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\data"; Flags: uninsneveruninstall
Name: "{app}\output"; Flags: uninsneveruninstall
Name: "{app}\profile"; Flags: uninsneveruninstall
Name: "{app}\config"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\VideoCongThuc.exe"; WorkingDir: "{app}"
Name: "{group}\{cm:UserGuide}"; Filename: "{app}\HUONG-DAN.pdf"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\VideoCongThuc.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\VideoCongThuc.exe"; WorkingDir: "{app}"; Description: "{cm:RunApp}"; Flags: nowait postinstall skipifsilent
