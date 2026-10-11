import sys
import os
import requests
import tempfile
import subprocess
from PySide6.QtCore import QThread, Signal

GITHUB_USER = "lunimo"
REPO_NAME = "HEIC-Converter-Studio"
CURRENT_VERSION = "v3.0.0"  


class CheckUpdateThread(QThread):
    """Поток для фоновой проверки наличия новых релизов на GitHub"""
    # Сигнал передает: (есть_ли_обновление, новая_версия, описание_релиза, direct_download_url)
    update_available = Signal(bool, str, str, str)

    def _parse_version(self, version_str: str) -> tuple:
        """Преобразует 'v3.0.0' или '3.0.0' в (3, 0, 0) для правильного сравнения версий."""
        clean_str = version_str.lstrip("v").strip()
        try:
            return tuple(map(int, clean_str.split(".")))
        except ValueError:
            return (0, 0, 0)

    def run(self):
        try:
            url = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/releases/latest"
            headers = {"Accept": "application/vnd.github.v3+json"}
            response = requests.get(url, headers=headers, timeout=5)

            if response.status_code == 200:
                data = response.json()
                latest_version = data.get("tag_name", "").strip()
                release_notes = data.get("body", "Описание изменений отсутствует.")

                # Ищем прямой .exe инсталлятор в прикрепленных asset'ах
                download_url = ""
                for asset in data.get("assets", []):
                    asset_name = asset.get("name", "").lower()
                    if asset_name.endswith(".exe"):
                        download_url = asset.get("browser_download_url", "")
                        break

                # Проверяем, что версия строго новее текущей и найден установочный файл
                if latest_version and self._parse_version(latest_version) > self._parse_version(CURRENT_VERSION):
                    self.update_available.emit(True, latest_version, release_notes, download_url)
                else:
                    self.update_available.emit(False, "", "", "")
            else:
                self.update_available.emit(False, "", "", "")
        except Exception as e:
            print(f"Ошибка проверки обновлений: {e}")
            self.update_available.emit(False, "", "", "")


class DownloadUpdateThread(QThread):
    """Поток для фоновой загрузки установочного файла с прогрессом"""
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, download_url: str):
        super().__init__()
        self.download_url = download_url

    def run(self):
        try:
            response = requests.get(self.download_url, stream=True, timeout=15)
            response.raise_for_status()

            total_length = response.headers.get("content-length")
            temp_dir = tempfile.gettempdir()
            installer_path = os.path.join(temp_dir, "HEIC_Converter_Studio_Setup.exe")

            if total_length is None:
                with open(installer_path, "wb") as f:
                    f.write(response.content)
                self.progress.emit(100)
            else:
                dl = 0
                total_length = int(total_length)
                with open(installer_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            dl += len(chunk)
                            f.write(chunk)
                            percent = int((dl / total_length) * 100)
                            self.progress.emit(percent)

            self.finished.emit(installer_path)
        except Exception as e:
            self.error.emit(str(e))


def run_installer_and_exit(installer_path: str):
    """Запускает скачанный инсталлятор и мгновенно закрывает текущую программу"""
    try:
        subprocess.Popen([installer_path], shell=True)
        sys.exit(0)
    except Exception as e:
        print(f"Ошибка запуска инсталлятора: {e}")