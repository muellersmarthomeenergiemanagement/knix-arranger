; KNiX Arranger – Inno Setup Installer-Skript
; Voraussetzungen:
;   1. Inno Setup 6 installiert: https://jrsoftware.org/isinfo.php
;   2. Nuitka-Build ausgefuehrt: python build.py  → dist\KNiX_Arranger\
;   3. LICENSE.txt vorhanden (Lizenztext fuer Installer-Wizard)
;
; Kompilieren: Inno Setup Compiler > File > Open > setup.iss > Build > Compile
; Ergebnis:    installer\KNiX_Arranger_Setup_v1.0.0.exe

#define AppName      "KNiX Arranger"
#define AppVersion   "1.1.4"   ; <- hier bei jedem Release anpassen
#define AppPublisher "Mueller SmartHome & EnergieManagement"
#define AppURL       "https://www.muellersmarthomeenergiemanagement.ch"
#define AppExeName   "KNiX_Arranger.exe"
#define AppId        "{{A3F2B1C4-7E9D-4F2A-B8C1-D3E5F6A7B890}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
; LicenseFile=LICENSE.txt
OutputDir=installer
OutputBaseFilename=KNiX_Arranger_Setup_v{#AppVersion}
SetupIconFile=icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
MinVersion=10.0
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknuepfung erstellen"; GroupDescription: "Zusaetzliche Symbole:"; Flags: unchecked
Name: "fileassoc";   Description: ".knxarr-Dateien mit KNiX Arranger verknuepfen"; GroupDescription: "Dateiverknuepfung:"

[Files]
Source: "dist\KNiX_Arranger\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";                  Filename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName} deinstallieren";   Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}";          Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; .knxarr Dateiverknuepfung
Root: HKCR; Subkey: ".knxarr";                                    ValueType: string; ValueName: ""; ValueData: "KNiXArranger.Project"; Flags: uninsdeletevalue;            Tasks: fileassoc
Root: HKCR; Subkey: "KNiXArranger.Project";                       ValueType: string; ValueName: ""; ValueData: "KNiX Arranger Projekt"; Flags: uninsdeletekey;            Tasks: fileassoc
Root: HKCR; Subkey: "KNiXArranger.Project\DefaultIcon";           ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName},0"; Flags: uninsdeletekey;            Tasks: fileassoc
Root: HKCR; Subkey: "KNiXArranger.Project\shell\open\command";    ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Flags: uninsdeletekey;  Tasks: fileassoc

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{#AppName} starten"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Konfiguration beim Deinstallieren behalten (Nutzerdaten in %APPDATA%)
; Nur die App selbst wird entfernt.
