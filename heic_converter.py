import os
import sys
import winreg
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    FluentIcon as FIF,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    RadioButton,
    Slider,
    SubtitleLabel,
    Theme,
    TitleLabel,
    setTheme,
)
from updater import CURRENT_VERSION, CheckUpdateThread

register_heif_opener()

os.environ["QF_DISABLE_INFO"] = "1"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_NAME = "HEICConverterStudio_SingleInstance_Socket"


def get_resource_path(relative_path):
  base_path = getattr(sys, "_MEIPASS", APP_DIR)
  return os.path.join(base_path, relative_path)


def register_context_menu():
    try:
        if getattr(sys, "frozen", False):
            exe_path = f'"{sys.executable}"'
            icon_path = f'"{sys.executable}"'
        else:
            python_exe = sys.executable
            pythonw_exe = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
            exe_path = f'"{pythonw_exe if os.path.exists(pythonw_exe) else python_exe}" "{os.path.abspath(__file__)}"'
            icon_file = get_resource_path("app_icon.ico")
            icon_path = f'"{icon_file}"' if os.path.exists(icon_file) else f'"{sys.executable}"'

        # Запись для файлов .heic
        key_path = r"Software\Classes\SystemFileAssociations\.heic\Shell\HEICConverter"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, "Сконвертировать в HEIC Converter Studio")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
            # Ограничиваем количество параллельных процессов
            winreg.SetValueEx(key, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
            
            with winreg.CreateKey(key, "command") as cmd_key:
                winreg.SetValue(cmd_key, "", winreg.REG_SZ, f'{exe_path} "%1"')

        # Запись для папок
        folder_key_path = r"Software\Classes\Directory\shell\HEICConverter"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, folder_key_path) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, "Сконвертировать HEIC в этой папке")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
            with winreg.CreateKey(key, "command") as cmd_key:
                winreg.SetValue(cmd_key, "", winreg.REG_SZ, f'{exe_path} "%1"')

        return True
    except Exception as e:
        print(f"Ошибка регистрации контекстного меню: {e}")
        return False


# === МНОГОПОТОЧНЫЙ ВОРКЕР ===
class ConvertWorker(QObject):
  progress_changed = Signal(int)
  conversion_finished = Signal(int, int, str, list)

  def __init__(self, selected_files, settings_data):
    super().__init__()
    self.selected_files = selected_files
    self.settings = settings_data

  def convert_single_file(self, file_path):
    try:
      directory, filename = os.path.split(file_path)
      name_no_ext = os.path.splitext(filename)[0]

      out_dir = (
          self.settings["custom_dir"]
          if (self.settings["use_custom_dir"] and self.settings["custom_dir"])
          else directory
      )
      fmt = self.settings["fmt"].lower()
      ext = "jpg" if fmt == "jpeg" else "png"
      output_path = os.path.join(out_dir, f"{name_no_ext}.{ext}")

      with Image.open(file_path) as img:
        try:
          img = ImageOps.exif_transpose(img)
        except Exception:
          pass

        scale_map = {
            "75% размера": 0.75,
            "50% размера": 0.50,
            "25% размера": 0.25,
        }
        res_text = self.settings["resize_option"]
        if res_text in scale_map:
          sc = scale_map[res_text]
          new_size = (int(img.width * sc), int(img.height * sc))
          img = img.resize(new_size, Image.Resampling.LANCZOS)

        exif_data = img.info.get("exif") if self.settings["keep_exif"] else None

        if ext == "jpg":
          if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
          save_kwargs = {"quality": self.settings["quality"]}
          if exif_data:
            save_kwargs["exif"] = exif_data
          img.save(output_path, "JPEG", **save_kwargs)
        else:
          save_kwargs = {}
          if exif_data:
            save_kwargs["exif"] = exif_data
          img.save(output_path, "PNG", **save_kwargs)

      if os.path.exists(output_path):
        if self.settings["delete_original"]:
          try:
            os.remove(file_path)
          except Exception:
            pass
        return True, out_dir, file_path
    except Exception as e:
      print(f"Ошибка с {file_path}: {e}")
    return False, "", file_path

  def run(self):
    total = len(self.selected_files)
    converted = 0
    last_dir = ""
    processed_count = 0
    failed_files = []

    max_workers = min(32, (os.cpu_count() or 1) + 4)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
      results = executor.map(self.convert_single_file, self.selected_files)
      for success, out_dir, fpath in results:
        processed_count += 1
        if success:
          converted += 1
          last_dir = out_dir
        else:
          failed_files.append(os.path.basename(fpath))
        self.progress_changed.emit(int((processed_count / total) * 100))

    self.conversion_finished.emit(converted, total, last_dir, failed_files)


# === СТРАНИЦА КОНВЕРТЕРА ===
class ConverterInterface(QWidget):

  def __init__(self, parent=None):
    super().__init__(parent)
    self.setObjectName("converter_interface")

    self.setAcceptDrops(True)  # Поддержка Drag-and-Drop

    self.main_app = parent
    self.selected_files = []
    self.last_output_dir = ""

    layout = QVBoxLayout(self)
    layout.setContentsMargins(30, 25, 30, 25)
    layout.setSpacing(12)

    self.title = TitleLabel("HEIC Converter Studio", self)
    self.subtitle = BodyLabel(
        "Перетащите файлы сюда или выберите через кнопки", self
    )
    self.subtitle.setTextColor(QColor(150, 150, 150), QColor(150, 150, 150))

    layout.addWidget(self.title)
    layout.addWidget(self.subtitle)

    self.info_card = CardWidget(self)
    info_layout = QVBoxLayout(self.info_card)
    info_layout.setContentsMargins(15, 10, 15, 10)

    self.status_label = SubtitleLabel("Файлы не выбраны", self.info_card)
    self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    info_layout.addWidget(self.status_label)

    # Виджет списка файлов
    self.file_list_widget = QListWidget(self.info_card)
    self.file_list_widget.setStyleSheet(
        "QListWidget { background: transparent; border: none; font-size:"
        " 12px; }"
    )
    self.file_list_widget.hide()
    info_layout.addWidget(self.file_list_widget)

    layout.addWidget(self.info_card)

    btn_layout = QHBoxLayout()
    self.btn_select_files = PushButton(FIF.DOCUMENT, "Выбрать файлы", self)
    self.btn_select_files.clicked.connect(self.select_files)

    self.btn_select_folder = PushButton(FIF.FOLDER, "Выбрать папку", self)
    self.btn_select_folder.clicked.connect(self.select_folder)

    self.btn_clear = PushButton(FIF.DELETE, "Очистить", self)
    self.btn_clear.clicked.connect(self.clear_files)
    self.btn_clear.setEnabled(False)

    btn_layout.addWidget(self.btn_select_files)
    btn_layout.addWidget(self.btn_select_folder)
    btn_layout.addWidget(self.btn_clear)
    layout.addLayout(btn_layout)

    self.progress_bar = ProgressBar(self)
    self.progress_bar.hide()
    layout.addWidget(self.progress_bar)

    self.btn_start = PrimaryPushButton(FIF.PLAY, "Начать конвертацию", self)
    self.btn_start.clicked.connect(self.start_conversion)
    self.btn_start.setEnabled(False)
    layout.addWidget(self.btn_start)

    self.btn_open_folder = PushButton(
        FIF.FOLDER, "Открыть папку с результатами", self
    )
    self.btn_open_folder.clicked.connect(self.open_output_folder)
    self.btn_open_folder.hide()
    layout.addWidget(self.btn_open_folder)

  # Обработка Drag-and-Drop
  def dragEnterEvent(self, event):
    if event.mimeData().hasUrls():
      event.acceptProposedAction()

  def dropEvent(self, event):
    dropped = []
    for url in event.mimeData().urls():
      path = url.toLocalFile()
      if os.path.isfile(path) and path.lower().endswith((".heic", ".heif")):
        dropped.append(path)
      elif os.path.isdir(path):
        for root, _, files in os.walk(path):
          for f in files:
            if f.lower().endswith((".heic", ".heif")):
              dropped.append(os.path.join(root, f))

    if dropped:
      current = list(self.selected_files)
      for f in dropped:
        if f not in current:
          current.append(f)
      self.selected_files = current
      self.update_ui_state()

  def select_files(self):
    files, _ = QFileDialog.getOpenFileNames(
        self, "Выберите HEIC снимки", "", "HEIC Files (*.heic *.HEIC)"
    )
    if files:
      self.selected_files = files
      self.update_ui_state()

  def select_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self, "Выберите папку с HEIC снимками"
    )
    if folder:
      found = []
      for root, _, files in os.walk(folder):
        for f in files:
          if f.lower().endswith((".heic", ".heif")):
            found.append(os.path.join(root, f))
      if found:
        self.selected_files = found
        self.update_ui_state()
      else:
        InfoBar.warning(
            "Пусто",
            "В выбранной папке нет HEIC файлов",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

  def clear_files(self):
    self.selected_files = []
    self.update_ui_state()

  def update_ui_state(self):
    count = len(self.selected_files)
    self.status_label.setText(f"Выбрано файлов: {count}")

    self.file_list_widget.clear()
    if count > 0:
      for f in self.selected_files[:15]:
        self.file_list_widget.addItem(os.path.basename(f))
      if count > 15:
        self.file_list_widget.addItem(f"... и ещё {count - 15} файлов")
      self.file_list_widget.show()
      self.btn_start.setEnabled(True)
      self.btn_clear.setEnabled(True)
    else:
      self.file_list_widget.hide()
      self.btn_start.setEnabled(False)
      self.btn_clear.setEnabled(False)

    self.btn_open_folder.hide()
    self.progress_bar.hide()

  def open_output_folder(self):
    if self.last_output_dir and os.path.exists(self.last_output_dir):
      os.startfile(self.last_output_dir)

  def start_conversion(self):
    self.btn_select_files.setEnabled(False)
    self.btn_select_folder.setEnabled(False)
    self.btn_clear.setEnabled(False)
    self.btn_start.setEnabled(False)
    self.progress_bar.setValue(0)
    self.progress_bar.show()

    settings = self.main_app.settings_interface
    settings_data = {
        "fmt": settings.fmt_combo.currentText(),
        "quality": settings.quality_slider.value(),
        "resize_option": settings.resize_combo.currentText(),
        "keep_exif": settings.chk_exif.isChecked(),
        "delete_original": settings.chk_delete.isChecked(),
        "use_custom_dir": settings.radio_custom.isChecked(),
        "custom_dir": settings.custom_dir,
    }

    self.thread = QThread()
    self.worker = ConvertWorker(self.selected_files, settings_data)
    self.worker.moveToThread(self.thread)

    self.thread.started.connect(self.worker.run)
    self.worker.progress_changed.connect(self.progress_bar.setValue)
    self.worker.conversion_finished.connect(self.on_finished)

    self.thread.start()

  def on_finished(self, converted, total, last_dir, failed_files):
    self.thread.quit()
    self.thread.wait()

    self.last_output_dir = last_dir
    self.btn_select_files.setEnabled(True)
    self.btn_select_folder.setEnabled(True)
    self.btn_clear.setEnabled(True)

    if converted > 0:
      self.status_label.setText(
          f"Успешно обработано: {converted} из {total} файлов"
      )
      self.btn_open_folder.show()
      InfoBar.success(
          "Готово!",
          "Конвертация успешно завершена!",
          parent=self,
          position=InfoBarPosition.TOP_RIGHT,
      )

      if self.main_app.tray_icon:
        self.main_app.tray_icon.showMessage(
            "HEIC Converter Studio",
            f"Сконвертировано: {converted} из {total} файлов.",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )
    else:
      self.status_label.setText("Ошибка конвертации")
      InfoBar.error(
          "Ошибка",
          "Не удалось обработать файлы",
          parent=self,
          position=InfoBarPosition.TOP_RIGHT,
      )

    if failed_files:
      InfoBar.warning(
          "Внимание",
          f"Пропущены поврежденные файлы ({len(failed_files)} шт.)",
          parent=self,
          position=InfoBarPosition.TOP_RIGHT,
      )


# === СТРАНИЦА НАСТРОЕК С АВТОСОХРАНЕНИЕМ ===
class SettingsInterface(QWidget):

  def __init__(self, parent=None):
    super().__init__(parent)
    self.setObjectName("settings_interface")

    self.custom_dir = ""

    layout = QVBoxLayout(self)
    layout.setContentsMargins(30, 30, 30, 30)
    layout.setSpacing(15)

    layout.addWidget(TitleLabel("Настройки", self))

    fmt_layout = QHBoxLayout()
    fmt_layout.addWidget(BodyLabel("Выходной формат:", self))
    self.fmt_combo = ComboBox(self)
    self.fmt_combo.addItems(["JPEG", "PNG"])
    self.fmt_combo.currentTextChanged.connect(self.save_settings)
    fmt_layout.addWidget(self.fmt_combo)

    fmt_layout.addWidget(BodyLabel(" Разрешение:", self))
    self.resize_combo = ComboBox(self)
    self.resize_combo.addItems(
        ["100% (Оригинал)", "75% размера", "50% размера", "25% размера"]
    )
    self.resize_combo.currentTextChanged.connect(self.save_settings)
    fmt_layout.addWidget(self.resize_combo)
    layout.addLayout(fmt_layout)

    self.lbl_qual = BodyLabel("Качество JPEG (90%):", self)
    layout.addWidget(self.lbl_qual)

    self.quality_slider = Slider(Qt.Orientation.Horizontal, self)
    self.quality_slider.setRange(50, 100)
    self.quality_slider.setValue(90)
    self.quality_slider.valueChanged.connect(self.on_quality_changed)
    layout.addWidget(self.quality_slider)

    self.chk_exif = CheckBox("Сохранять EXIF-метаданные (дата, GPS)", self)
    self.chk_exif.setChecked(True)
    self.chk_exif.stateChanged.connect(self.save_settings)
    layout.addWidget(self.chk_exif)

    self.chk_delete = CheckBox("Удалять исходные .HEIC после конвертации", self)
    self.chk_delete.stateChanged.connect(self.save_settings)
    layout.addWidget(self.chk_delete)

    layout.addWidget(BodyLabel("Сохранение результатов:", self))
    self.radio_same = RadioButton("В ту же папку, где лежит оригинал", self)
    self.radio_same.setChecked(True)
    self.radio_same.toggled.connect(self.save_settings)

    self.radio_custom = RadioButton("В выбранную папку", self)
    self.radio_custom.toggled.connect(self.save_settings)

    layout.addWidget(self.radio_same)
    layout.addWidget(self.radio_custom)

    self.btn_choose_dir = PushButton(
        FIF.FOLDER, "Выбрать папку для сохранения...", self
    )
    self.btn_choose_dir.setEnabled(False)
    self.btn_choose_dir.clicked.connect(self.select_custom_dir)
    self.radio_custom.toggled.connect(self.btn_choose_dir.setEnabled)

    layout.addWidget(self.btn_choose_dir)

    self.btn_register_menu = PushButton(
        FIF.APPLICATION,
        "Добавить программу в контекстное меню Windows (ПКМ)",
        self,
    )
    self.btn_register_menu.clicked.connect(self.add_to_context_menu)
    layout.addWidget(self.btn_register_menu)

    layout.addStretch(1)

    self.load_settings()

  def on_quality_changed(self, value):
    self.lbl_qual.setText(f"Качество JPEG ({value}%):")
    self.save_settings()

  def select_custom_dir(self):
    path = QFileDialog.getExistingDirectory(
        self, "Выберите папку для сохранения"
    )
    if path:
      self.custom_dir = path
      self.btn_choose_dir.setText(f"Папка: {path}")
      self.save_settings()

  def add_to_context_menu(self):
    if register_context_menu():
      InfoBar.success(
          "Успех!",
          "Пункт меню с иконкой успешно обновлен!",
          parent=self,
          position=InfoBarPosition.TOP_RIGHT,
      )
    else:
      InfoBar.error(
          "Ошибка",
          "Не удалось внести изменения в реестр.",
          parent=self,
          position=InfoBarPosition.TOP_RIGHT,
      )

  def save_settings(self):
    settings = QSettings("lunityl", "HEICConverterStudio")
    settings.setValue("fmt", self.fmt_combo.currentText())
    settings.setValue("resize", self.resize_combo.currentText())
    settings.setValue("quality", self.quality_slider.value())
    settings.setValue("keep_exif", self.chk_exif.isChecked())
    settings.setValue("delete_original", self.chk_delete.isChecked())
    settings.setValue("use_custom_dir", self.radio_custom.isChecked())
    settings.setValue("custom_dir", self.custom_dir)

  def load_settings(self):
    settings = QSettings("lunityl", "HEICConverterStudio")
    self.fmt_combo.setCurrentText(settings.value("fmt", "JPEG"))
    self.resize_combo.setCurrentText(settings.value("resize", "100% (Оригинал)"))
    self.quality_slider.setValue(int(settings.value("quality", 90)))
    self.chk_exif.setChecked(settings.value("keep_exif", True, type=bool))
    self.chk_delete.setChecked(
        settings.value("delete_original", False, type=bool)
    )

    use_custom = settings.value("use_custom_dir", False, type=bool)
    self.radio_custom.setChecked(use_custom)
    self.radio_same.setChecked(not use_custom)

    self.custom_dir = settings.value("custom_dir", "")
    if self.custom_dir:
      self.btn_choose_dir.setText(f"Папка: {self.custom_dir}")


# === СТРАНИЦА О ПРОГРАММЕ ===
class AboutInterface(QWidget):

  def __init__(self, parent=None):
    super().__init__(parent)
    self.setObjectName("about_interface")

    layout = QVBoxLayout(self)
    layout.setContentsMargins(30, 30, 30, 30)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

    avatar_pix = self.get_avatar_pixmap()
    avatar_label = BodyLabel(self)
    avatar_label.setPixmap(avatar_pix)
    avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(avatar_label)

    title = TitleLabel("HEIC Converter Studio", self)
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title)

    author = SubtitleLabel("Автор: lunityl  •  2026", self)
    author.setAlignment(Qt.AlignmentFlag.AlignCenter)
    author.setTextColor(QColor(0, 120, 212), QColor(0, 120, 212))
    layout.addWidget(author)

    desc = BodyLabel(
        "Современный конвертер HEIC-изображений\nв стиле Fluent Design Windows"
        " 11 с локальной\nобработкой и переносом EXIF-данных.",
        self,
    )
    desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(desc)

  def get_avatar_pixmap(self):
    for ext in ["png", "jpg", "jpeg"]:
      avatar_path = get_resource_path(f"avatar.{ext}")
      if os.path.exists(avatar_path):
        pix = QPixmap(avatar_path)
        return pix.scaled(
            240,
            240,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    pix = QPixmap(140, 140)
    pix.fill(Qt.GlobalColor.transparent)
    return pix


# === ГЛАВНОЕ ОКНО ===
class MainWindow(FluentWindow):

  def __init__(self):
    super().__init__()
    self.setWindowTitle("HEIC Converter Studio")
    self.resize(800, 560)

    icon_path = get_resource_path("app_icon.ico")
    if os.path.exists(icon_path):
      self.setWindowIcon(QIcon(icon_path))

    self.tray_icon = None
    if QSystemTrayIcon.isSystemTrayAvailable():
      self.tray_icon = QSystemTrayIcon(self)
      if os.path.exists(icon_path):
        self.tray_icon.setIcon(QIcon(icon_path))
      self.tray_icon.show()

    self.converter_interface = ConverterInterface(self)
    self.settings_interface = SettingsInterface(self)
    self.about_interface = AboutInterface(self)

    self.addSubInterface(self.converter_interface, FIF.HOME, "Конвертер")
    self.addSubInterface(self.settings_interface, FIF.SETTING, "Настройки")
    self.addSubInterface(self.about_interface, FIF.INFO, "О программе")

    # -----------------------------------------------------------
    # ДОБАВЛЯЕМ СТРОКУ НИЖЕ: Запуск проверки обновлений при старте
    # -----------------------------------------------------------
    self.check_for_updates()

  # -----------------------------------------------------------
  # ДОБАВЛЯЕМ ДВА НОВЫХ МЕТОДА ВНУТРИ КЛАССА MainWindow:
  # -----------------------------------------------------------
  def check_for_updates(self):
    """Запускает фоновый поток для проверки обновлений на GitHub."""
    self.update_thread = CheckUpdateThread()
    self.update_thread.update_available.connect(self.on_update_checked)
    self.update_thread.start()

  def on_update_checked(self, available, latest_version, url):
    """Срабатывает, когда сервер GitHub прислал ответ."""
    if available:
      # Показываем всплывающее окно в стиле Windows 11
      info_bar = InfoBar.info(
          title="Доступно обновление!",
          content=(
              f"Вышла новая версия {latest_version}. Нажмите сюда, чтобы"
              " скачать."
          ),
          orient=Qt.Orientation.Vertical,
          isClosable=True,
          position=InfoBarPosition.TOP_RIGHT,
          duration=-1,  # Окно не закроется, пока пользователь не кликнет
          parent=self,
      )
      # При клике на уведомление открывается страница релиза в браузере
      info_bar.clicked.connect(lambda: webbrowser.open(url))


# === ТОЧКА ВХОДА С ВНЕШНИМ МОДУЛЕМ ===
from single_instance import SingleInstanceApp

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("HEIC Converter Studio")
    app.setOrganizationName("lunityl")
    setTheme(Theme.DARK)

    # 1. Проверяем, запущен ли уже экземпляр программы
    single_app = SingleInstanceApp()
    if single_app.is_running():
        # Передали файлы первому экземпляру и закрываемся
        sys.exit(0)

    icon_path = get_resource_path("app_icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    w = MainWindow()
    if os.path.exists(icon_path):
        w.setWindowIcon(QIcon(icon_path))

    # 2. Метод добавления входящих путей в интерфейс
    def handle_incoming_path(path_data: str):
        paths = [p.strip() for p in path_data.split("\n") if p.strip()]
        new_files = []
        for path in paths:
            if os.path.isfile(path) and path.lower().endswith((".heic", ".heif")):
                new_files.append(path)
            elif os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for f in files:
                        if f.lower().endswith((".heic", ".heif")):
                            new_files.append(os.path.join(root, f))

        if new_files:
            current_files = list(w.converter_interface.selected_files)
            for f in new_files:
                if f not in current_files:
                    current_files.append(f)

            w.converter_interface.selected_files = current_files
            w.converter_interface.update_ui_state()

            # Фокусируем окно на передний план
            if w.isMinimized():
                w.showNormal()
            w.activateWindow()
            w.raise_()

    # 3. Подключаем сигнал сервера к функции добавления файлов
    single_app.file_received.connect(handle_incoming_path)

    # 4. Если первый запуск был сразу с файлами (ПКМ при закрытом приложении)
    if len(sys.argv) > 1:
        handle_incoming_path("\n".join(sys.argv[1:]))

    w.show()
    sys.exit(app.exec())