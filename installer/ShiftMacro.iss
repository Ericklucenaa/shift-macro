; Instalador do Shift Macro (Inno Setup 6). Gerado por scripts\compilar.ps1 quando o ISCC está instalado.
; Compilação manual:  ISCC.exe /DAppVersion=1.0.0 installer\ShiftMacro.iss
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B1E3C2A-6F43-4E7D-9C1B-5A0F2D8E7C11}
AppName=Shift Macro
AppVersion={#AppVersion}
AppPublisher=Shift
DefaultDirName={localappdata}\Programs\Shift Macro
DefaultGroupName=Shift Macro
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ShiftMacro-{#AppVersion}-setup
SetupIconFile=..\assets\shiftmacro.ico
UninstallDisplayIcon={app}\ShiftMacro.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
CloseApplications=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; Flags: unchecked
Name: "assoc"; Description: "Abrir arquivos .shiftmacro com o Shift Macro"

[Files]
Source: "..\dist\ShiftMacro\*"; DestDir: "{app}"; Excludes: "instalar.ps1,desinstalar.ps1"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Shift Macro"; Filename: "{app}\ShiftMacro.exe"
Name: "{group}\Exemplos de macros"; Filename: "{app}\Exemplos"
Name: "{autodesktop}\Shift Macro"; Filename: "{app}\ShiftMacro.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\.shiftmacro"; ValueType: string; ValueData: "ShiftMacro.Macro"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\ShiftMacro.Macro"; ValueType: string; ValueData: "Macro do Shift Macro"; Flags: uninsdeletekey; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\ShiftMacro.Macro\DefaultIcon"; ValueType: string; ValueData: """{app}\ShiftMacro.exe"",0"; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\ShiftMacro.Macro\shell\open\command"; ValueType: string; ValueData: """{app}\ShiftMacro.exe"" ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\ShiftMacro.exe"; Description: "Abrir o Shift Macro"; Flags: nowait postinstall skipifsilent
