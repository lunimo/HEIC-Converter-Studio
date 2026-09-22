import sys
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = "HEICConverterStudio_SingleInstance_Server"

class SingleInstanceApp(QObject):
    # Сигнал, который передаст полученный путь в главное окно
    file_received = Signal(str)

    def __init__(self):
        super().__init__()
        self.server = None

    def is_running(self) -> bool:
        """Проверяет, запущен ли уже другой экземпляр программы."""
        socket = QLocalSocket()
        socket.connectToServer(SERVER_NAME)
        
        # Если удалось подключиться за 500мс — экземпляр уже есть
        if socket.waitForConnected(500):
            # Если передали файл через аргумент командной строки — отправляем его
            if len(sys.argv) > 1:
                file_path = sys.argv[1]
                socket.write(file_path.encode('utf-8'))
                socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
            return True
        
        # Если не подключились — мы первый экземпляр, создаем сервер
        self._start_server()
        return False

    def _start_server(self):
        # Удаляем старый сервер, если остался после сбоя
        QLocalServer.removeServer(SERVER_NAME)
        self.server = QLocalServer()
        self.server.newConnection.connect(self._on_new_connection)
        self.server.listen(SERVER_NAME)

    def _on_new_connection(self):
        socket = self.server.nextPendingConnection()
        if socket:
            if socket.waitForReadyRead(1000):
                file_path = socket.readAll().data().decode('utf-8')
                if file_path:
                    self.file_received.emit(file_path)
            socket.disconnectFromServer()