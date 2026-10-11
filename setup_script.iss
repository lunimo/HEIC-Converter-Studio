[Setup]
AppName=HEIC Converter Studio
AppVersion=3.0.0
UninstallDisplayName=HEIC Converter Studio
AppPublisher=lunityl
DefaultDirName={autopf}\HEIC Converter Studio
DefaultGroupName=HEIC Converter Studio
UninstallDisplayIcon={app}\HEIC Converter Studio.exe
Compression=lzma2/ultra64
SolidCompression=yes
OutputDir=Output
OutputBaseFilename=HEIC_Converter_Studio_Setup_v3.0.0
SetupIconFile=app_icon.ico

; Поддержка установки без прав администратора / для всех пользователей
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Лицензия (раскомментируйте, если есть файл LICENSE рядом)
; LicenseFile=LICENSE

; Закрывать приложение перед обновлением/установкой
CloseApplications=yes
CloseApplicationsFilter=HEIC Converter Studio.exe

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на Рабочем столе"; GroupDescription: "Ярлыки:"
Name: "contextmenu"; Description: "Добавить «Сконвертировать в HEIC Converter Studio» в контекстное меню Explorer"; GroupDescription: "Интеграция:"; Flags: checkedonce

[Files]
; Захватываем все файлы и подпапки из папки сборки dist\HEIC Converter Studio
Source: "dist\HEIC Converter Studio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\HEIC Converter Studio"; Filename: "{app}\HEIC Converter Studio.exe"
Name: "{group}\Удалить HEIC Converter Studio"; Filename: "{uninstallexe}"
Name: "{autodesktop}\HEIC Converter Studio"; Filename: "{app}\HEIC Converter Studio.exe"; Tasks: desktopicon

; Автоматическая регистрация в контекстном меню (ПКМ) по выбору пользователя
[Registry]
; Контекстное меню для файлов .heic
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.heic\Shell\HEICConverter"; ValueType: string; ValueData: "Сконвертировать в HEIC Converter Studio"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.heic\Shell\HEICConverter"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\HEIC Converter Studio.exe"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.heic\Shell\HEICConverter\command"; ValueType: string; ValueData: """{app}\HEIC Converter Studio.exe"" ""%1"""; Flags: uninsdeletekey; Tasks: contextmenu

; Контекстное меню для папок
Root: HKCU; Subkey: "Software\Classes\Directory\shell\HEICConverter"; ValueType: string; ValueData: "Сконвертировать HEIC в этой папке"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\HEICConverter"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\HEIC Converter Studio.exe"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\HEICConverter\command"; ValueType: string; ValueData: """{app}\HEIC Converter Studio.exe"" ""%1"""; Flags: uninsdeletekey; Tasks: contextmenu

[Code]
// Уведомляем Explorer об изменениях в реестре (чтобы контекстное меню сразу появилось)
procedure SHChangeNotify(EventId: LongInt; Flags: UINT; Item1: LongInt; Item2: LongInt);
external 'SHChangeNotify@shell32.dll stdcall';

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    SHChangeNotify($08000000, $0000, 0, 0); // SHCNE_ASSOCCHANGED
  end;
end;

// Полная очистка настроек при удалении программы
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    SHChangeNotify($08000000, $0000, 0, 0);
    if MsgBox('Удалить сохраненные пользовательские настройки программы?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      RegDeleteKeyIncludingSubkeys(HKCU, 'Software\lunityl\HEICConverterStudio');
    end;
  end;
end;

[Run]
Filename: "{app}\HEIC Converter Studio.exe"; Description: "Запустить HEIC Converter Studio"; Flags: nowait postinstall skipifsilent