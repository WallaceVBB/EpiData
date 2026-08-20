; packaging/EpiData.iss  
#define MyAppName "EpiData"  
#define MyAppVersion GetEnv('APP_VERSION')   ; injectée par la CI (ex: 1.2.0)  
#define MyAppExeName "EpiData.exe"  
  
[Setup]  
AppName={#MyAppName}  
AppVersion={#MyAppVersion}  
DefaultDirName={autopf}\{#MyAppName}  
DefaultGroupName={#MyAppName}  
OutputDir=Output  
OutputBaseFilename=EpiData-Setup-{#MyAppVersion}  
Compression=lzma2  
SolidCompression=yes  
; installation par utilisateur = pas besoin de droits admin (utile pour l'auto-update)  
PrivilegesRequired=lowest  
ArchitecturesInstallIn64BitMode=x64  
  
[Files]  
; tout le contenu du build onedir  
Source: "..\dist\EpiData\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs  
  
[Icons]  
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"  
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"  
  
[Run]  
; relance l'app après une installation silencieuse (auto-update)  
Filename: "{app}\{#MyAppExeName}"; Flags: nowait postinstall skipifsilent