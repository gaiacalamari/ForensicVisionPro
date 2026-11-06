; Inno Setup 6: crea l'installer Windows dalla cartella generata da PyInstaller.
; Compilare con: iscc packaging\installer.iss
#define AppName "Forensic Vision Pro"
#define AppVersion "1.2.0"
[Setup]
AppId={{6F1C2A54-8C1E-4D7B-9A3F-2B7E5D1C0A91}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\ForensicVisionPro
DefaultGroupName={#AppName}
OutputDir=..\dist\installer
OutputBaseFilename=ForensicVisionPro-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
[Files]
Source: "..\dist\ForensicVisionPro\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\docs\*"; DestDir: "{app}\docs"; Flags: recursesubdirs ignoreversion
[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\ForensicVisionPro.exe"
Name: "{group}\Manuale utente"; Filename: "{app}\docs\MANUALE_UTENTE.md"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ForensicVisionPro.exe"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Crea un'icona sul desktop"; Flags: unchecked
