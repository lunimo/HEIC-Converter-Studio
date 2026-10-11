import os
import sys
import winreg
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
import pillow_avif  # Поддержка AVIF
from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal, QUrl, QTranslator, QCoreApplication
from PySide6.QtGui import QColor, QIcon, QPixmap, QDesktopServices, QPainter, QPainterPath
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
    QMessageBox, 
    QProgressDialog
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    FluentIcon as FIF,
    FluentWindow,
    PushSettingCard,
    IconWidget,
    MessageBox,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PrimaryPushSettingCard,
    ProgressBar,
    PushButton,
    SettingCard,
    SwitchSettingCard,
    RadioButton,
    ScrollArea,
    SettingCardGroup,
    Slider,
    SubtitleLabel,
    Theme,
    TitleLabel,
    setTheme,
    isDarkTheme,
)

from updater import CURRENT_VERSION, CheckUpdateThread, DownloadUpdateThread, run_installer_and_exit

register_heif_opener()

os.environ["QF_DISABLE_INFO"] = "1"
APP_DIR = os.path.dirname(os.path.abspath(__file__))

SUPPORTED_EXTENSIONS = (
    ".heic", ".heif", ".avif", ".webp", 
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff"
)


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


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

        key_path = r"Software\Classes\SystemFileAssociations\.heic\Shell\HEICConverter"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, "Сконвертировать в HEIC Converter Studio")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
            winreg.SetValueEx(key, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
            
            with winreg.CreateKey(key, "command") as cmd_key:
                winreg.SetValue(cmd_key, "", winreg.REG_SZ, f'{exe_path} "%1"')

        folder_key_path = r"Software\Classes\Directory\shell\HEICConverter"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, folder_key_path) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, "Сконвертировать изображения в этой папке")
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
            abs_file_path = os.path.abspath(os.path.normpath(file_path))
            parent_dir = os.path.dirname(abs_file_path)
            filename = os.path.basename(abs_file_path)
            name_no_ext = os.path.splitext(filename)[0]

            custom_dir = self.settings.get("custom_dir", "").strip()
            use_subfolder = self.settings.get("use_subfolder", True)

            base_dir = os.path.abspath(os.path.normpath(custom_dir)) if custom_dir else parent_dir

            if use_subfolder:
                out_dir = os.path.join(base_dir, "Converted")
            else:
                out_dir = base_dir

            os.makedirs(out_dir, exist_ok=True)

            fmt = str(self.settings.get("fmt", "JPEG")).lower()
            ext = "jpg" if fmt in ("jpeg", "jpg") else fmt
            output_path = os.path.join(out_dir, f"{name_no_ext}.{ext}")

            with Image.open(abs_file_path) as img:
                try:
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass

                scale_map = {
                    "75% размера": 0.75, "75% size": 0.75,
                    "50% размера": 0.50, "50% size": 0.50,
                    "25% размера": 0.25, "25% size": 0.25,
                }
                res_text = self.settings.get("resize_option", "")
                if res_text in scale_map:
                    sc = scale_map[res_text]
                    new_size = (int(img.width * sc), int(img.height * sc))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)

                exif_data = img.info.get("exif") if self.settings.get("keep_exif") else None
                save_kwargs = {}
                if exif_data:
                    save_kwargs["exif"] = exif_data

                quality = int(self.settings.get("quality", 90))

                if fmt in ("jpeg", "jpg"):
                    if img.mode in ("RGBA", "LA", "P"):
                        img = img.convert("RGB")
                    save_kwargs["quality"] = quality
                    img.save(output_path, "JPEG", **save_kwargs)
                elif fmt == "webp":
                    save_kwargs["quality"] = quality
                    img.save(output_path, "WEBP", **save_kwargs)
                elif fmt == "avif":
                    save_kwargs["quality"] = quality
                    img.save(output_path, "AVIF", **save_kwargs)
                else:  # PNG
                    img.save(output_path, "PNG", **save_kwargs)

            if os.path.exists(output_path):
                if self.settings.get("delete_original"):
                    try:
                        os.remove(abs_file_path)
                    except Exception:
                        pass
                return True, out_dir, abs_file_path
        except Exception as e:
            print(f"Ошибка конвертации для {file_path}: {e}")
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

        self.setAcceptDrops(True)
        self.main_app = parent
        self.selected_files = []
        self.last_output_dir = ""

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 20, 30, 20)
        main_layout.setSpacing(14)

        # 1. Заголовок
        self.title = TitleLabel(self.tr("HEIC Converter Studio"), self)
        self.subtitle = CaptionLabel(
            self.tr("Быстрая и удобная пакетная конвертация изображений"), self
        )
        self.subtitle.setStyleSheet("color: #888888;")
        main_layout.addWidget(self.title)
        main_layout.addWidget(self.subtitle)

        # 2. Область Drag-and-Drop (Drop Zone)
        self.drop_card = CardWidget(self)
        self.drop_card.setMinimumHeight(120)
        drop_layout = QVBoxLayout(self.drop_card)
        drop_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.setSpacing(6)

        self.drop_icon = IconWidget(FIF.DOWNLOAD, self.drop_card)
        self.drop_icon.setFixedSize(36, 36)
        
        self.drop_text = SubtitleLabel(self.tr("Перетащите файлы или папки сюда"), self.drop_card)
        self.drop_subtext = CaptionLabel(self.tr("Поддерживаются HEIC, AVIF, WEBP, JPG, PNG и другие"), self.drop_card)
        self.drop_subtext.setStyleSheet("color: #888888;")

        drop_layout.addWidget(self.drop_icon, 0, Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(self.drop_text, 0, Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(self.drop_subtext, 0, Qt.AlignmentFlag.AlignCenter)

        main_layout.addWidget(self.drop_card)

        # 3. Кнопки выбора
        btn_layout = QHBoxLayout()
        self.btn_select_files = PushButton(FIF.DOCUMENT, self.tr("Выбрать файлы"), self)
        self.btn_select_files.clicked.connect(self.select_files)

        self.btn_select_folder = PushButton(FIF.FOLDER, self.tr("Выбрать папку"), self)
        self.btn_select_folder.clicked.connect(self.select_folder)

        self.btn_clear = PushButton(FIF.DELETE, self.tr("Очистить список"), self)
        self.btn_clear.clicked.connect(self.clear_files)
        self.btn_clear.setEnabled(False)

        btn_layout.addWidget(self.btn_select_files)
        btn_layout.addWidget(self.btn_select_folder)
        btn_layout.addWidget(self.btn_clear)
        main_layout.addLayout(btn_layout)

        # 4. Список выбранных файлов
        self.file_list_widget = QListWidget(self)
        self.file_list_widget.hide()
        main_layout.addWidget(self.file_list_widget, 1)

        # 5. Информационная панель текущих настроек
        self.summary_card = CardWidget(self)
        summary_layout = QHBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(12, 8, 12, 8)
        
        self.lbl_summary_fmt = CaptionLabel(self.tr("Формат: JPEG"), self.summary_card)
        self.lbl_summary_size = CaptionLabel(self.tr("Размер: 100%"), self.summary_card)
        self.lbl_summary_quality = CaptionLabel(self.tr("Качество: 90%"), self.summary_card)
        self.lbl_summary_dir = CaptionLabel(self.tr("Назначение: Рядом с оригиналом"), self.summary_card)
        
        for lbl in (self.lbl_summary_fmt, self.lbl_summary_size, self.lbl_summary_quality, self.lbl_summary_dir):
            summary_layout.addWidget(lbl)
            summary_layout.addStretch(1)

        main_layout.addWidget(self.summary_card)

        # 6. Прогресс-бар и статус
        self.progress_bar = ProgressBar(self)
        self.progress_bar.hide()
        main_layout.addWidget(self.progress_bar)

        self.status_label = CaptionLabel("", self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.status_label)

        # 7. Действия (Старт / Открыть папку)
        actions_layout = QHBoxLayout()
        self.btn_start = PrimaryPushButton(FIF.PLAY, self.tr("Начать конвертацию"), self)
        self.btn_start.clicked.connect(self.start_conversion)
        self.btn_start.setEnabled(False)

        self.btn_open_folder = PushButton(FIF.FOLDER, self.tr("Открыть папку с результатом"), self)
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        self.btn_open_folder.hide()

        actions_layout.addWidget(self.btn_start, 2)
        actions_layout.addWidget(self.btn_open_folder, 1)
        main_layout.addLayout(actions_layout)

        # Применяем адаптивные стили
        self.apply_theme_styles()

    def apply_theme_styles(self):
        """Адаптивные динамические стили под светлую и тёмную темы"""
        is_dark = isDarkTheme()

        # Цвета для DropZone
        border_dashed = "rgba(255, 255, 255, 0.15)" if is_dark else "rgba(0, 0, 0, 0.15)"
        drop_hover_bg = "rgba(0, 120, 212, 0.08)" if is_dark else "rgba(0, 120, 212, 0.05)"

        self.drop_card.setStyleSheet(f"""
            CardWidget {{
                border: 2px dashed {border_dashed};
                border-radius: 10px;
                background: transparent;
            }}
            CardWidget:hover {{
                border-color: #0078d4;
                background: {drop_hover_bg};
            }}
        """)

        # Цвета для QListWidget
        bg_list = "rgba(255, 255, 255, 0.03)" if is_dark else "rgba(0, 0, 0, 0.02)"
        border_list = "rgba(255, 255, 255, 0.08)" if is_dark else "rgba(0, 0, 0, 0.1)"
        text_color = "#ffffff" if is_dark else "#1a1a1a"
        hover_bg = "rgba(255, 255, 255, 0.08)" if is_dark else "rgba(0, 0, 0, 0.05)"
        item_border = "rgba(255, 255, 255, 0.04)" if is_dark else "rgba(0, 0, 0, 0.04)"

        self.file_list_widget.setStyleSheet(f"""
            QListWidget {{
                background: {bg_list};
                border: 1px solid {border_list};
                border-radius: 8px;
                padding: 4px;
                color: {text_color};
            }}
            QListWidget::item {{
                color: {text_color};
                padding: 6px 8px;
                border-bottom: 1px solid {item_border};
            }}
            QListWidget::item:hover {{
                background: {hover_bg};
                border-radius: 4px;
            }}
        """)

        # Вспомогательный текст
        subtext_color = "#aaaaaa" if is_dark else "#666666"
        for lbl in (self.lbl_summary_fmt, self.lbl_summary_size, self.lbl_summary_quality, self.lbl_summary_dir, self.status_label):
            lbl.setStyleSheet(f"color: {subtext_color};")

    def showEvent(self, event):
        super().showEvent(event)
        self.update_summary_info()
        self.apply_theme_styles()

    def update_summary_info(self):
        if not hasattr(self.main_app, 'settings_interface'):
            return
        st = self.main_app.settings_interface
        self.lbl_summary_fmt.setText(f"{self.tr('Формат:')} {st.fmtCombo.currentText()}")
        self.lbl_summary_size.setText(f"{self.tr('Размер:')} {st.resizeCombo.currentText()}")
        self.lbl_summary_quality.setText(f"{self.tr('Качество:')} {st.qualitySlider.value()}%")
        
        c_dir = getattr(st, 'custom_dir', '')
        if c_dir:
            folder_name = os.path.basename(c_dir) or c_dir
            self.lbl_summary_dir.setText(f"{self.tr('Папка:')} {folder_name}")
        else:
            self.lbl_summary_dir.setText(self.tr("Папка: Рядом с оригиналом"))

    def retranslate_ui(self):
        self.title.setText(self.tr("HEIC Converter Studio"))
        self.subtitle.setText(self.tr("Быстрая и удобная пакетная конвертация изображений"))
        self.drop_text.setText(self.tr("Перетащите файлы или папки сюда"))
        self.drop_subtext.setText(self.tr("Поддерживаются HEIC, AVIF, WEBP, JPG, PNG и другие"))
        self.btn_select_files.setText(self.tr("Выбрать файлы"))
        self.btn_select_folder.setText(self.tr("Выбрать папку"))
        self.btn_clear.setText(self.tr("Очистить список"))
        self.btn_start.setText(self.tr("Начать конвертацию"))
        self.btn_open_folder.setText(self.tr("Открыть папку с результатом"))
        self.apply_theme_styles()
        self.update_summary_info()
        self.update_ui_state()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.drop_card.setStyleSheet(
                "CardWidget { border: 2px dashed #0078d4; border-radius: 10px; background: rgba(0, 120, 212, 0.12); }"
            )

    def dragLeaveEvent(self, event):
        self.apply_theme_styles()

    def dropEvent(self, event):
        self.dragLeaveEvent(event)
        dropped = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path) and path.lower().endswith(SUPPORTED_EXTENSIONS):
                dropped.append(path)
            elif os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for f in files:
                        if f.lower().endswith(SUPPORTED_EXTENSIONS):
                            dropped.append(os.path.join(root, f))

        if dropped:
            current = list(self.selected_files)
            for f in dropped:
                if f not in current:
                    current.append(f)
            self.selected_files = current
            self.update_ui_state()

    def select_files(self):
        filter_str = self.tr("Изображения (*.heic *.heif *.avif *.webp *.jpg *.jpeg *.png *.bmp *.tiff);;Все файлы (*.*)")
        files, _ = QFileDialog.getOpenFileNames(
            self, self.tr("Выберите изображения"), "", filter_str
        )
        if files:
            self.selected_files = files
            self.update_ui_state()

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, self.tr("Выберите папку с изображениями")
        )
        if folder:
            found = []
            for root, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(SUPPORTED_EXTENSIONS):
                        found.append(os.path.join(root, f))
            if found:
                self.selected_files = found
                self.update_ui_state()
            else:
                InfoBar.warning(
                    self.tr("Пусто"),
                    self.tr("В выбранной папке не найдены поддерживаемые изображения"),
                    parent=self,
                    position=InfoBarPosition.TOP_RIGHT,
                )

    def clear_files(self):
        self.selected_files = []
        self.update_ui_state()

    def format_size(self, num_bytes):
        units = [self.tr("Б"), self.tr("КБ"), self.tr("МБ"), self.tr("ГБ")]
        for unit in units:
            if abs(num_bytes) < 1024.0:
                return f"{num_bytes:.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} {self.tr('ТБ')}"

    def update_ui_state(self):
        count = len(self.selected_files)
        self.file_list_widget.clear()

        if count > 0:
            total_bytes = 0
            for f in self.selected_files:
                try:
                    sz = os.path.getsize(f)
                    total_bytes += sz
                    file_info = f"{os.path.basename(f)}  ({self.format_size(sz)})"
                except Exception:
                    file_info = os.path.basename(f)

                self.file_list_widget.addItem(file_info)

            total_str = self.format_size(total_bytes)
            self.status_label.setText(f"{self.tr('Готово к обработке:')} {count} {self.tr('файлов')} (~{total_str})")
            
            self.file_list_widget.show()
            self.btn_start.setEnabled(True)
            self.btn_clear.setEnabled(True)
        else:
            self.status_label.setText("")
            self.file_list_widget.hide()
            self.btn_start.setEnabled(False)
            self.btn_clear.setEnabled(False)

        self.btn_open_folder.hide()
        self.progress_bar.hide()
        self.update_summary_info()

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
        custom_dir = str(getattr(settings, "custom_dir", "")).strip()

        settings_data = {
            "fmt": settings.fmtCombo.currentText(),
            "quality": settings.qualitySlider.value(),
            "resize_option": settings.resizeCombo.currentText(),
            "keep_exif": settings.exifCard.isChecked(),
            "delete_original": settings.deleteCard.isChecked(),
            "use_subfolder": settings.subfolderCard.isChecked(),
            "custom_dir": custom_dir,
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
                f"{self.tr('Успешно обработано:')} {converted} {self.tr('из')} {total} {self.tr('файлов')}"
            )
            self.btn_open_folder.show()
            InfoBar.success(
                self.tr("Готово!"),
                self.tr("Конвертация успешно завершена!"),
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )

            if self.main_app.tray_icon:
                self.main_app.tray_icon.showMessage(
                    "HEIC Converter Studio",
                    f"{self.tr('Сконвертировано:')} {converted} {self.tr('из')} {total} {self.tr('файлов')}.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
        else:
            self.status_label.setText(self.tr("Ошибка конвертации"))
            InfoBar.error(
                self.tr("Ошибка"),
                self.tr("Не удалось обработать файлы"),
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )

        if failed_files:
            InfoBar.warning(
                self.tr("Внимание"),
                f"{self.tr('Пропущены поврежденные файлы')} ({len(failed_files)} {self.tr('шт.')})",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )


# === СТРАНИЦА НАСТРОЕК ===
class SettingsInterface(ScrollArea):

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("settings_interface")
        self.main_app = parent
        self.custom_dir = ""

        self.scrollWidget = QWidget()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
        self.setWidget(self.scrollWidget)

        self.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        self.scrollWidget.setStyleSheet("QWidget { background-color: transparent; }")

        layout = QVBoxLayout(self.scrollWidget)
        layout.setContentsMargins(36, 20, 36, 36)
        layout.setSpacing(20)

        self.title_label = TitleLabel(self.tr("Настройки"), self.scrollWidget)
        layout.addWidget(self.title_label)

        # 1. ГРУППА: Внешний вид
        self.appearanceGroup = SettingCardGroup(self.tr("Внешний вид"), self.scrollWidget)

        self.themeCard = SettingCard(
            FIF.BRUSH,
            self.tr("Тема оформления"),
            self.tr("Выберите тему интерфейса приложения"),
            parent=self.appearanceGroup
        )
        self.themeCombo = ComboBox(self.themeCard)
        self.themeCombo.addItems([self.tr("Тёмная"), self.tr("Светлая")])
        self.themeCombo.setCurrentIndex(0 if Theme.DARK else 1)
        self.themeCombo.currentIndexChanged.connect(self.on_theme_changed)
        self.themeCard.hBoxLayout.addWidget(self.themeCombo)
        self.themeCard.hBoxLayout.addSpacing(16)
        self.appearanceGroup.addSettingCard(self.themeCard)

        self.langCard = SettingCard(
            FIF.LANGUAGE,
            self.tr("Язык интерфейса"),
            self.tr("Выберите язык приложения"),
            parent=self.appearanceGroup
        )
        self.langCombo = ComboBox(self.langCard)
        self.langCombo.addItems(["Русский", "English"])
        self.langCombo.currentIndexChanged.connect(self.on_language_changed)
        self.langCard.hBoxLayout.addWidget(self.langCombo)
        self.langCard.hBoxLayout.addSpacing(16)
        self.appearanceGroup.addSettingCard(self.langCard)

        layout.addWidget(self.appearanceGroup)

        # 2. ГРУППА: Параметры конвертации
        self.convertGroup = SettingCardGroup(self.tr("Параметры конвертации"), self.scrollWidget)

        self.fmtCard = SettingCard(
            FIF.PHOTO,
            self.tr("Выходной формат"),
            self.tr("Формат итогового изображения"),
            parent=self.convertGroup
        )
        self.fmtCombo = ComboBox(self.fmtCard)
        self.fmtCombo.addItems(["JPEG", "PNG", "WEBP", "AVIF"])
        self.fmtCombo.currentTextChanged.connect(self.save_settings)
        self.fmtCard.hBoxLayout.addWidget(self.fmtCombo)
        self.fmtCard.hBoxLayout.addSpacing(16)
        self.convertGroup.addSettingCard(self.fmtCard)

        self.resizeCard = SettingCard(
            FIF.ZOOM_IN,
            self.tr("Разрешение"),
            self.tr("Масштабирование исходного изображения"),
            parent=self.convertGroup
        )
        self.resizeCombo = ComboBox(self.resizeCard)
        self.resizeCombo.addItems([
            self.tr("100% (Оригинал)"),
            self.tr("75% размера"),
            self.tr("50% размера"),
            self.tr("25% размера")
        ])
        self.resizeCombo.currentTextChanged.connect(self.save_settings)
        self.resizeCard.hBoxLayout.addWidget(self.resizeCombo)
        self.resizeCard.hBoxLayout.addSpacing(16)
        self.convertGroup.addSettingCard(self.resizeCard)

        self.qualCard = SettingCard(
            FIF.SETTING,
            self.tr("Качество сжатия (90%)"),
            self.tr("Степень сжатия для JPEG, WEBP и AVIF"),
            parent=self.convertGroup
        )
        self.qualitySlider = Slider(Qt.Orientation.Horizontal, self.qualCard)
        self.qualitySlider.setRange(50, 100)
        self.qualitySlider.setValue(90)
        self.qualitySlider.setFixedWidth(160)
        self.qualitySlider.valueChanged.connect(self.on_quality_changed)
        self.qualCard.hBoxLayout.addWidget(self.qualitySlider)
        self.qualCard.hBoxLayout.addSpacing(16)
        self.convertGroup.addSettingCard(self.qualCard)

        # EXIF Card
        self.exifCard = SwitchSettingCard(
            FIF.INFO,
            self.tr("Сохранять EXIF-метаданные"),
            self.tr("Переносить дату съемки, местоположение и параметры камеры"),
            parent=self.convertGroup
        )
        self.exifCard.switchButton.setOnText(self.tr("Вкл."))
        self.exifCard.switchButton.setOffText(self.tr("Выкл."))
        self.exifCard.setChecked(True)
        self.exifCard.checkedChanged.connect(self.force_switch_text)
        self.exifCard.checkedChanged.connect(self.save_settings)
        self.convertGroup.addSettingCard(self.exifCard)

        # Delete Card
        self.deleteCard = SwitchSettingCard(
            FIF.DELETE,
            self.tr("Удалять исходные файлы"),
            self.tr("Автоматически удалять оригиналы после успешной конвертации"),
            parent=self.convertGroup
        )
        self.deleteCard.switchButton.setOnText(self.tr("Вкл."))
        self.deleteCard.switchButton.setOffText(self.tr("Выкл."))
        self.deleteCard.checkedChanged.connect(self.force_switch_text)
        self.deleteCard.checkedChanged.connect(self.save_settings)
        self.convertGroup.addSettingCard(self.deleteCard)

        layout.addWidget(self.convertGroup)

        # 3. ГРУППА: Сохранение и система
        self.systemGroup = SettingCardGroup(self.tr("Сохранение и система"), self.scrollWidget)

        # Subfolder Card
        self.subfolderCard = SwitchSettingCard(
            FIF.FOLDER,
            self.tr("Сохранять в подпапку Converted"),
            self.tr("Создавать подпапку Converted в месте сохранения (рядом с оригиналом или в выбранной папке)"),
            parent=self.systemGroup
        )
        self.subfolderCard.switchButton.setOnText(self.tr("Вкл."))
        self.subfolderCard.switchButton.setOffText(self.tr("Выкл."))
        self.subfolderCard.setChecked(True)
        self.subfolderCard.checkedChanged.connect(self.force_switch_text)
        self.subfolderCard.checkedChanged.connect(self.save_settings)
        self.systemGroup.addSettingCard(self.subfolderCard)

        self.folderCard = SettingCard(
            FIF.FOLDER,
            self.tr("Пользовательская папка"),
            self.tr("Сохранять файлы в фиксированную папку"),
            parent=self.systemGroup
        )
        self.btn_select_folder = PushButton(FIF.FOLDER, self.tr("Выбрать"), self.folderCard)
        self.btn_select_folder.clicked.connect(self.select_custom_dir)

        self.btn_reset_folder = PushButton(FIF.CLOSE, self.tr("Сбросить"), self.folderCard)
        self.btn_reset_folder.clicked.connect(self.reset_custom_dir)

        self.folderCard.hBoxLayout.addWidget(self.btn_select_folder)
        self.folderCard.hBoxLayout.addWidget(self.btn_reset_folder)
        self.folderCard.hBoxLayout.addSpacing(16)

        self.systemGroup.addSettingCard(self.folderCard)

        self.contextMenuCard = PrimaryPushSettingCard(
            self.tr("Добавить"),
            FIF.APPLICATION,
            self.tr("Контекстное меню Windows (ПКМ)"),
            self.tr("Интегрировать пункт конвертации в проводник Windows"),
            parent=self.systemGroup
        )
        self.contextMenuCard.clicked.connect(self.add_to_context_menu)
        self.systemGroup.addSettingCard(self.contextMenuCard)

        layout.addWidget(self.systemGroup)

        layout.addStretch(1)
        self.load_settings()

    def force_switch_text(self):
        """Жестко переписываем текст кнопок после их внутреннего обновления"""
        self.exifCard.switchButton.setText(self.tr("Вкл.") if self.exifCard.isChecked() else self.tr("Выкл."))
        self.deleteCard.switchButton.setText(self.tr("Вкл.") if self.deleteCard.isChecked() else self.tr("Выкл."))
        self.subfolderCard.switchButton.setText(self.tr("Вкл.") if self.subfolderCard.isChecked() else self.tr("Выкл."))

    def update_folder_card_ui(self):
        if self.custom_dir:
            self.folderCard.setContent(f"{self.tr('Папка:')} {self.custom_dir}")
            self.btn_reset_folder.setEnabled(True)
        else:
            self.folderCard.setContent(self.tr("Сохранять рядом с оригиналами (кастомный путь не задан)"))
            self.btn_reset_folder.setEnabled(False)

    def retranslate_ui(self):
        self.title_label.setText(self.tr("Настройки"))
        
        self.appearanceGroup.titleLabel.setText(self.tr("Внешний вид"))
        self.convertGroup.titleLabel.setText(self.tr("Параметры конвертации"))
        self.systemGroup.titleLabel.setText(self.tr("Сохранение и система"))

        self.themeCard.titleLabel.setText(self.tr("Тема оформления"))
        self.themeCard.contentLabel.setText(self.tr("Выберите тему интерфейса приложения"))
        
        curr_theme_idx = self.themeCombo.currentIndex()
        self.themeCombo.blockSignals(True)
        self.themeCombo.clear()
        self.themeCombo.addItems([self.tr("Тёмная"), self.tr("Светлая")])
        self.themeCombo.setCurrentIndex(curr_theme_idx)
        self.themeCombo.blockSignals(False)

        self.langCard.titleLabel.setText(self.tr("Язык интерфейса"))
        self.langCard.contentLabel.setText(self.tr("Выберите язык приложения"))

        self.fmtCard.titleLabel.setText(self.tr("Выходной формат"))
        self.fmtCard.contentLabel.setText(self.tr("Формат итогового изображения"))
        
        self.resizeCard.titleLabel.setText(self.tr("Разрешение"))
        self.resizeCard.contentLabel.setText(self.tr("Масштабирование исходного изображения"))

        curr_res_idx = self.resizeCombo.currentIndex()
        self.resizeCombo.blockSignals(True)
        self.resizeCombo.clear()
        self.resizeCombo.addItems([
            self.tr("100% (Оригинал)"),
            self.tr("75% размера"),
            self.tr("50% размера"),
            self.tr("25% размера")
        ])
        self.resizeCombo.setCurrentIndex(curr_res_idx)
        self.resizeCombo.blockSignals(False)

        self.qualCard.titleLabel.setText(f"{self.tr('Качество сжатия')} ({self.qualitySlider.value()}%)")
        self.qualCard.contentLabel.setText(self.tr("Степень сжатия для JPEG, WEBP и AVIF"))

        self.exifCard.titleLabel.setText(self.tr("Сохранять EXIF-метаданные"))
        self.exifCard.contentLabel.setText(self.tr("Переносить дату съемки, местоположение и параметры камеры"))
        self.exifCard.switchButton.setOnText(self.tr("Вкл."))
        self.exifCard.switchButton.setOffText(self.tr("Выкл."))

        self.deleteCard.titleLabel.setText(self.tr("Удалять исходные файлы"))
        self.deleteCard.contentLabel.setText(self.tr("Автоматически удалять оригиналы после успешной конвертации"))
        self.deleteCard.switchButton.setOnText(self.tr("Вкл."))
        self.deleteCard.switchButton.setOffText(self.tr("Выкл."))

        self.subfolderCard.titleLabel.setText(self.tr("Сохранять в подпапку Converted"))
        self.subfolderCard.contentLabel.setText(self.tr("Создавать подпапку Converted в месте сохранения (рядом с оригиналом или в выбранной папке)"))
        self.subfolderCard.switchButton.setOnText(self.tr("Вкл."))
        self.subfolderCard.switchButton.setOffText(self.tr("Выкл."))

        self.folderCard.titleLabel.setText(self.tr("Пользовательская папка"))
        self.btn_select_folder.setText(self.tr("Выбрать"))
        self.btn_reset_folder.setText(self.tr("Сбросить"))
        self.update_folder_card_ui()

        self.contextMenuCard.titleLabel.setText(self.tr("Контекстное меню Windows (ПКМ)"))
        self.contextMenuCard.contentLabel.setText(self.tr("Интегрировать пункт конвертации в проводник Windows"))
        self.contextMenuCard.button.setText(self.tr("Добавить"))

        # Принудительно дергаем тексты тумблеров при смене языка
        self.force_switch_text()

    def on_theme_changed(self, index):
        if index == 0:
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.LIGHT)
        
        if hasattr(self.main_app, 'converter_interface'):
            self.main_app.converter_interface.apply_theme_styles()

    def on_language_changed(self, index):
        lang = "en" if index == 1 else "ru"
        if hasattr(self.main_app, 'load_language'):
            self.main_app.load_language(lang)
        self.save_settings()

    def on_quality_changed(self, value):
        self.qualCard.titleLabel.setText(f"{self.tr('Качество сжатия')} ({value}%)")
        self.save_settings()

    def select_custom_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, self.tr("Выберите папку для сохранения")
        )
        if path:
            self.custom_dir = os.path.normpath(path)
            self.update_folder_card_ui()
            self.save_settings()

    def reset_custom_dir(self):
        self.custom_dir = ""
        self.update_folder_card_ui()
        self.save_settings()

    def add_to_context_menu(self):
        if register_context_menu():
            InfoBar.success(
                self.tr("Успех!"),
                self.tr("Пункт меню с иконкой успешно обновлен!"),
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
        else:
            InfoBar.error(
                self.tr("Ошибка"),
                self.tr("Не удалось внести изменения в реестр."),
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )

    def save_settings(self):
        settings = QSettings("lunityl", "HEICConverterStudio")
        settings.setValue("fmt", self.fmtCombo.currentText())
        settings.setValue("resize", self.resizeCombo.currentIndex())
        settings.setValue("quality", self.qualitySlider.value())
        settings.setValue("keep_exif", self.exifCard.isChecked())
        settings.setValue("delete_original", self.deleteCard.isChecked())
        settings.setValue("use_subfolder", self.subfolderCard.isChecked())
        settings.setValue("custom_dir", self.custom_dir)
        settings.setValue("language", "en" if self.langCombo.currentIndex() == 1 else "ru")

    def load_settings(self):
        settings = QSettings("lunityl", "HEICConverterStudio")
        self.fmtCombo.setCurrentText(settings.value("fmt", "JPEG"))
        
        res_val = settings.value("resize", 0)
        try:
            res_idx = int(res_val)
        except (ValueError, TypeError):
            res_idx = 0

        if 0 <= res_idx < self.resizeCombo.count():
            self.resizeCombo.setCurrentIndex(res_idx)

        self.qualitySlider.setValue(int(settings.value("quality", 90)))
        
        # Временно отключаем сигналы, чтобы не затирать текст при программном изменении
        self.exifCard.blockSignals(True)
        self.exifCard.setChecked(settings.value("keep_exif", True, type=bool))
        self.exifCard.blockSignals(False)

        self.deleteCard.blockSignals(True)
        self.deleteCard.setChecked(settings.value("delete_original", False, type=bool))
        self.deleteCard.blockSignals(False)

        self.subfolderCard.blockSignals(True)
        self.subfolderCard.setChecked(settings.value("use_subfolder", True, type=bool))
        self.subfolderCard.blockSignals(False)

        self.custom_dir = str(settings.value("custom_dir", "") or "")
        
        lang = settings.value("language", "ru")
        self.langCombo.blockSignals(True)
        self.langCombo.setCurrentIndex(1 if lang == "en" else 0)
        self.langCombo.blockSignals(False)

        self.retranslate_ui()


# === СТРАНИЦА О ПРОГРАММЕ ===
class AboutInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget()
        self.expandLayout = QVBoxLayout(self.scrollWidget)
        
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
        self.setWidget(self.scrollWidget)
        self.setObjectName("aboutInterface")
        
        self.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        self.scrollWidget.setStyleSheet("QWidget { background-color: transparent; }")

        self.expandLayout.setContentsMargins(36, 20, 36, 36)
        self.expandLayout.setSpacing(20)
        self.expandLayout.setAlignment(Qt.AlignTop)

        self.headerLayout = QHBoxLayout()
        self.headerLayout.setSpacing(16)
        
        self.avatarLabel = QLabel(self.scrollWidget)
        self.avatarLabel.setFixedSize(72, 72)
        pixmap = QPixmap(resource_path("avatar.png"))
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(72, 72, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            rounded = QPixmap(72, 72)
            rounded.fill(Qt.transparent)
            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addEllipse(0, 0, 72, 72)
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, scaled_pixmap)
            painter.end()
            self.avatarLabel.setPixmap(rounded)

        self.titleLayout = QVBoxLayout()
        self.titleLayout.setSpacing(4)
        self.titleLabel = TitleLabel(self.tr("HEIC Converter Studio"), self.scrollWidget)
        
        version_str = CURRENT_VERSION if not CURRENT_VERSION.startswith('v') else CURRENT_VERSION[1:]
        self.versionLabel = CaptionLabel(f"{self.tr('Версия')} {version_str}", self.scrollWidget)
        self.versionLabel.setStyleSheet("color: #888888;")
        
        self.descLabel = BodyLabel(self.tr("Универсальный инструмент для конвертации медиа с интеграцией в Windows."), self.scrollWidget)
        self.descLabel.setStyleSheet("color: #aaaaaa;")
        
        self.titleLayout.addWidget(self.titleLabel)
        self.titleLayout.addWidget(self.versionLabel)
        self.titleLayout.addWidget(self.descLabel)

        self.headerLayout.addWidget(self.avatarLabel)
        self.headerLayout.addLayout(self.titleLayout)
        self.headerLayout.addStretch(1)

        self.linksGroup = SettingCardGroup(self.tr("О программе и ссылки"), self.scrollWidget)

        self.updateCard = PrimaryPushSettingCard(
            self.tr("Проверить обновления"),
            FIF.SYNC,
            self.tr("Обновление"),
            self.tr("Поиск новых релизов на GitHub"),
            self.linksGroup
        )
        if hasattr(parent, 'check_for_updates'):
            self.updateCard.button.clicked.connect(lambda *args: parent.check_for_updates(manual=True))

        self.githubCard = PushSettingCard(
            self.tr("Открыть"),
            FIF.GITHUB,
            self.tr("GitHub Репозиторий"),
            self.tr("Просмотр исходного кода и отчёты об ошибках"),
            self.linksGroup
        )
        self.githubCard.button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/lunimo/HEIC-Converter-Studio"))
        )

        self.telegramCard = PushSettingCard(
            self.tr("Перейти"),
            FIF.SEND,
            self.tr("Telegram канал"),
            self.tr("Новости разработки и связь с автором"),
            self.linksGroup
        )
        self.telegramCard.button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://t.me/lunibio"))
        )

        self.linksGroup.addSettingCard(self.updateCard)
        self.linksGroup.addSettingCard(self.githubCard)
        self.linksGroup.addSettingCard(self.telegramCard)

        self.copyrightLabel = CaptionLabel(self.tr("© 2026 lunimo. Распространяется по лицензии MIT."), self.scrollWidget)
        self.copyrightLabel.setAlignment(Qt.AlignCenter)
        self.copyrightLabel.setStyleSheet("color: #888888;")

        self.expandLayout.addLayout(self.headerLayout)
        self.expandLayout.addWidget(self.linksGroup)
        self.expandLayout.addSpacing(10)
        self.expandLayout.addWidget(self.copyrightLabel)

    def retranslate_ui(self):
        version_str = CURRENT_VERSION if not CURRENT_VERSION.startswith('v') else CURRENT_VERSION[1:]
        self.titleLabel.setText(self.tr("HEIC Converter Studio"))
        self.versionLabel.setText(f"{self.tr('Версия')} {version_str}")
        self.descLabel.setText(self.tr("Универсальный инструмент для конвертации медиа с интеграцией в Windows."))

        self.linksGroup.titleLabel.setText(self.tr("О программе и ссылки"))

        self.updateCard.button.setText(self.tr("Проверить обновления"))
        self.updateCard.titleLabel.setText(self.tr("Обновление"))
        self.updateCard.contentLabel.setText(self.tr("Поиск новых релизов на GitHub"))

        self.githubCard.button.setText(self.tr("Открыть"))
        self.githubCard.titleLabel.setText(self.tr("GitHub Репозиторий"))
        self.githubCard.contentLabel.setText(self.tr("Просмотр исходного кода и отчёты об ошибках"))

        self.telegramCard.button.setText(self.tr("Перейти"))
        self.telegramCard.titleLabel.setText(self.tr("Telegram канал"))
        self.telegramCard.contentLabel.setText(self.tr("Новости разработки и связь с автором"))

        self.copyrightLabel.setText(self.tr("© 2026 lunimo. Распространяется по лицензии MIT."))


# === ГЛАВНОЕ ОКНО ===
class MainWindow(FluentWindow):

    def __init__(self):
        super().__init__()
        self.translator = QTranslator()
        
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

        self.nav_converter = self.addSubInterface(self.converter_interface, FIF.HOME, self.tr("Конвертер"))
        self.nav_settings = self.addSubInterface(self.settings_interface, FIF.SETTING, self.tr("Настройки"))
        self.nav_about = self.addSubInterface(self.about_interface, FIF.INFO, self.tr("О программе"))

        settings = QSettings("lunityl", "HEICConverterStudio")
        self.load_language(settings.value("language", "ru"))

        self.check_for_updates()

    def load_language(self, lang_code):
        QCoreApplication.removeTranslator(self.translator)
        
        if lang_code == "en":
            qm_path = get_resource_path("translations/en_US.qm")
            if os.path.exists(qm_path):
                if self.translator.load(qm_path):
                    QCoreApplication.installTranslator(self.translator)

        self.retranslate_ui()

    def retranslate_ui(self):
        self.nav_converter.setText(self.tr("Конвертер"))
        self.nav_settings.setText(self.tr("Настройки"))
        self.nav_about.setText(self.tr("О программе"))

        self.converter_interface.retranslate_ui()
        self.settings_interface.retranslate_ui()
        self.about_interface.retranslate_ui()

    def check_for_updates(self, manual=False):
        """Запуск фоновой проверки обновлений"""
        self.is_manual_check = manual
        self.update_thread = CheckUpdateThread()
        self.update_thread.update_available.connect(self.on_update_check_finished)
        self.update_thread.start()

    def on_update_check_finished(
        self, has_update, new_version, release_notes, download_url
    ):

        parent_window = self.window()

        # 1. Если обновлений нет (или ошибка)
        if not has_update or not download_url:
            if getattr(self, "is_manual_check", False):
                InfoBar.info(
                    title=self.tr("Обновлений не найдено"),
                    content=self.tr("У вас установлена самая свежая версия!"),
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=3000,
                    parent=parent_window,
                )
            return

        # 2. Если обновление найдено — показываем модальное диалоговое окно по центру приложения
        from qfluentwidgets import MessageBox
        
        msg_box = MessageBox(
            self.tr("Доступно обновление {0}").format(new_version),
            self.tr("Хотите скачать и установить новую версию приложения прямо сейчас?"),
            parent_window
        )
        msg_box.yesButton.setText(self.tr("Установить"))
        msg_box.cancelButton.setText(self.tr("Позже"))

        if msg_box.exec():
            self.start_download_and_install(download_url)

    def start_download_and_install(self, download_url):
        """Запуск скачивания инсталлятора с плашкой прогресса"""
        parent_window = self.window()

        # Показываем уведомление о начале скачивания
        self.download_info_bar = InfoBar.info(
            title=self.tr("Загрузка обновления..."),
            content=self.tr("Пожалуйста, подождите, идёт скачивание установочного файла. Не закрывайте приложение."),
            orient=Qt.Orientation.Horizontal,
            isClosable=False,
            position=InfoBarPosition.TOP_RIGHT,
            duration=-1,
            parent=parent_window,
        )

        self.download_thread = DownloadUpdateThread(download_url)
        self.download_thread.progress.connect(self.on_download_progress)
        self.download_thread.finished.connect(self.on_download_finished)
        self.download_thread.error.connect(self.on_download_error)

        self.download_thread.start()

    def on_download_progress(self, percent):
        # Выводим процент загрузки в заголовок окна, чтобы не вызывать ошибку InfoBar
        self.setWindowTitle(f"HEIC Converter Studio — {self.tr('Загрузка:')} {percent}%")

    def on_download_finished(self, installer_path):
        self.setWindowTitle("HEIC Converter Studio")
        if hasattr(self, "download_info_bar") and self.download_info_bar:
            self.download_info_bar.close()
        run_installer_and_exit(installer_path)

    def on_download_error(self, error_msg):
        self.setWindowTitle("HEIC Converter Studio")
        if hasattr(self, "download_info_bar") and self.download_info_bar:
            self.download_info_bar.close()

        InfoBar.error(
            title=self.tr("Ошибка скачивания"),
            content=self.tr("Не удалось загрузить обновление: {0}").format(error_msg),
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
            parent=self.window(),
        )

try:
    from single_instance import SingleInstanceApp
except ImportError:
    SingleInstanceApp = None

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("HEIC Converter Studio")
    app.setOrganizationName("lunityl")
    setTheme(Theme.DARK)

    single_app = SingleInstanceApp() if SingleInstanceApp else None
    if single_app and single_app.is_running():
        sys.exit(0)

    icon_path = get_resource_path("app_icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    w = MainWindow()
    if os.path.exists(icon_path):
        w.setWindowIcon(QIcon(icon_path))

    def handle_incoming_path(path_data: str):
        paths = [p.strip() for p in path_data.split("\n") if p.strip()]
        new_files = []
        for path in paths:
            if os.path.isfile(path) and path.lower().endswith(SUPPORTED_EXTENSIONS):
                new_files.append(path)
            elif os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for f in files:
                        if f.lower().endswith(SUPPORTED_EXTENSIONS):
                            new_files.append(os.path.join(root, f))

        if new_files:
            current_files = list(w.converter_interface.selected_files)
            for f in new_files:
                if f not in current_files:
                    current_files.append(f)

            w.converter_interface.selected_files = current_files
            w.converter_interface.update_ui_state()

            if w.isMinimized():
                w.showNormal()
            w.activateWindow()
            w.raise_()

    if single_app:
        single_app.file_received.connect(handle_incoming_path)

    if len(sys.argv) > 1:
        handle_incoming_path("\n".join(sys.argv[1:]))

    w.show()
    sys.exit(app.exec())