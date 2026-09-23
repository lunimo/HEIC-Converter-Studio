import requests
from PySide6.QtCore import QThread, Signal

# Данные твоего репозитория на GitHub
GITHUB_USER = "lunimo"
REPO_NAME = "HEIC-Converter-Studio"
CURRENT_VERSION = "v2.2.0"  # Текущая версия приложения


class CheckUpdateThread(QThread):
    # Сигнал передает: (есть_ли_обновление, новая_версия, ссылка_на_страницу_релиза)
    update_available = Signal(bool, str, str)

    def _parse_version(self, version_str: str) -> tuple:
        """Преобразует строку версии вида 'v2.2.0' или '2.2.0' в кортеж чисел (2, 2, 0) для сравнения."""
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
                html_url = data.get("html_url", "")

                # Проверяем, что версия с GitHub строго БОЛЬШЕ текущей локальной версии
                if latest_version and self._parse_version(
                    latest_version
                ) > self._parse_version(CURRENT_VERSION):
                    self.update_available.emit(True, latest_version, html_url)
                else:
                    self.update_available.emit(False, "", "")
            else:
                self.update_available.emit(False, "", "")
        except Exception as e:
            print(f"Ошибка проверки обновлений: {e}")
            self.update_available.emit(False, "", "")