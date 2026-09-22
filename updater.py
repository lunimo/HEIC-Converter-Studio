import requests
from PySide6.QtCore import QThread, Signal

# Данные твоего репозитория на GitHub
GITHUB_USER = "lunimo"
REPO_NAME = "HEIC-Converter-Studio"
CURRENT_VERSION = "v2.1.0"  # Текущая версия приложения


class CheckUpdateThread(QThread):
  # Сигнал передает: (есть_ли_обновление, новая_версия, ссылка_на_страницу_релиза)
  update_available = Signal(bool, str, str)

  def run(self):
    try:
      url = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/releases/latest"
      headers = {"Accept": "application/vnd.github.v3+json"}
      response = requests.get(url, headers=headers, timeout=5)

      if response.status_code == 200:
        data = response.json()
        latest_version = data.get("tag_name", "").strip()
        html_url = data.get("html_url", "")

        # Если версия на GitHub выше/отличается от текущей
        if latest_version and latest_version != CURRENT_VERSION:
          self.update_available.emit(True, latest_version, html_url)
        else:
          self.update_available.emit(False, "", "")
      else:
        self.update_available.emit(False, "", "")
    except Exception as e:
      print(f"Ошибка проверки обновлений: {e}")
      self.update_available.emit(False, "", "")