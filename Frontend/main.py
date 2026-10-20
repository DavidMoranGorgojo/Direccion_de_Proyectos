import sys

from PySide6.QtWidgets import QApplication

from paths import STYLE_FILE
from services import session
from views.login_window import LoginWindow
from views.main_window import MainWindow


class App:
    """Controla el flujo: inicio de sesión -> chat -> (cerrar sesión) -> inicio de sesión."""

    def __init__(self, app: QApplication):
        self.app = app
        self.login = LoginWindow()
        self.login.authenticated.connect(self._on_login)
        self.chat: MainWindow | None = None

    def start(self) -> None:
        self.login.show()

    def _on_login(self, res) -> None:
        session.start(res.user, res.token, res.user_id)
        self.chat = MainWindow(res.user)
        self.chat.logged_out.connect(self._on_logout)
        self.chat.show()
        self.login.hide()

    def _on_logout(self) -> None:
        session.clear()
        chat, self.chat = self.chat, None
        if chat is not None:
            chat.close()
            chat.deleteLater()
        self.login.reset()
        self.login.show()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE_FILE.read_text(encoding="utf-8"))
    flow = App(app)
    flow.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
