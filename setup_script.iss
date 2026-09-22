[Setup]
AppName=HEIC Converter Studio
AppVersion=2.0.0
UninstallDisplayName=HEIC Converter Studio
AppPublisher=lunityl
DefaultDirName={autopf}\HEIC Converter Studio
DefaultGroupName=HEIC Converter Studio
UninstallDisplayIcon={app}\HEIC Converter Studio.exe
Compression=lzma2/ultra64
SolidCompression=yes
OutputDir=Output
OutputBaseFilename=HEIC_Converter_Studio_Setup
SetupIconFile=app_icon.ico

; Пункт 3: Закрывать приложение перед обновлением/установкой
CloseApplications=yes
CloseApplicationsFilter=HEIC Converter Studio.exe

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на Рабочем столе"; GroupDescription: "Ярлыки:"

[Files]
Source: "dist\HEIC Converter Studio.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\HEIC Converter Studio"; Filename: "{app}\HEIC Converter Studio.exe"
Name: "{group}\Удалить HEIC Converter Studio"; Filename: "{uninstallexe}"
Name: "{autodesktop}\HEIC Converter Studio"; Filename: "{app}\HEIC Converter Studio.exe"; Tasks: desktopicon

; Пункт 1: Автоматическая регистрация в контекстном меню (ПКМ)
[Registry]
; Контекстное меню для файлов .heic
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.heic\Shell\HEICConverter"; ValueType: string; ValueData: "Сконвертировать в HEIC Converter Studio"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.heic\Shell\HEICConverter"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\HEIC Converter Studio.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.heic\Shell\HEICConverter\command"; ValueType: string; ValueData: """{app}\HEIC Converter Studio.exe"" ""%1"""; Flags: uninsdeletekey

; Контекстное меню для папок
Root: HKCU; Subkey: "Software\Classes\Directory\shell\HEICConverter"; ValueType: string; ValueData: "Сконвертировать HEIC в этой папке"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\HEICConverter"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\HEIC Converter Studio.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\HEICConverter\command"; ValueType: string; ValueData: """{app}\HEIC Converter Studio.exe"" ""%1"""; Flags: uninsdeletekey

; Пункт 5: Полная очистка настроек при удалении программы
[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox('Удалить сохраненные пользовательские настройки программы?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      RegDeleteKeyIncludingSubkeys(HKCU, 'Software\lunityl\HEICConverterStudio');
    end;
  end;
end;

[Run]
Filename: "{app}\HEIC Converter Studio.exe"; Description: "Запустить HEIC Converter Studio"; Flags: nowait postinstall skipifsilent