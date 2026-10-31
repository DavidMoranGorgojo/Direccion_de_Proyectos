from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QLabel, QLineEdit, QMainWindow, QPushButton

from paths import LOGIN_UI_FILE, image
from services import api, auth


class LoginWindow(QMainWindow):
    """Pantalla de inicio de sesión (diseñada en ui/login_window.ui)."""
    authenticated = Signal(object)  # AuthResult

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MR BOT by ARSOFT · Iniciar sesión")
        self.setWindowIcon(QIcon(image("logo.png")))
        self.resize(960, 620)
        self.setMinimumSize(820, 560)

        self.ui = QUiLoader().load(str(LOGIN_UI_FILE), self)
        self.setCentralWidget(self.ui)
        f = self.ui.findChild
        self.logo: QLabel = f(QLabel, "labelLogo")
        self.edit_user: QLineEdit = f(QLineEdit, "editUser")
        self.edit_pass: QLineEdit = f(QLineEdit, "editPassword")
        self.btn_show: QPushButton = f(QPushButton, "btnShowPassword")
        self.btn_login: QPushButton = f(QPushButton, "btnLogin")
        self.error: QLabel = f(QLabel, "labelError")
        self.mode: QLabel = f(QLabel, "labelMode")
        self._worker: auth.LoginWorker | None = None

        pix = QPixmap(image("logo.png"))
        self.logo.setPixmap(pix.scaledToHeight(260, Qt.SmoothTransformation))
        """
        if api.is_mock():
            self.mode.setText("Modo local simulado: sin backend conectado.\n"
                              "Usuario de prueba: demo · contraseña: demo1234")
        """

        self.btn_login.clicked.connect(self._submit)
        self.edit_user.returnPressed.connect(self.edit_pass.setFocus)
        self.edit_pass.returnPressed.connect(self._submit)
        self.btn_show.toggled.connect(self._toggle_password)
        self.edit_user.textChanged.connect(lambda: self.error.setText(""))
        self.edit_pass.textChanged.connect(lambda: self.error.setText(""))

    def reset(self) -> None:
        """Deja el formulario limpio (al volver tras cerrar sesión)."""
        self.edit_pass.clear()
        self.error.setText("")
        self.btn_show.setChecked(False)
        self._set_busy(False)
        self.edit_user.setFocus()

    def showEvent(self, e):
        super().showEvent(e)
        (self.edit_pass if self.edit_user.text() else self.edit_user).setFocus()

    def _toggle_password(self, shown: bool) -> None:
        self.edit_pass.setEchoMode(QLineEdit.Normal if shown else QLineEdit.Password)
        self.btn_show.setText("Ocultar" if shown else "Mostrar")

    def _set_busy(self, busy: bool) -> None:
        for w in (self.btn_login, self.edit_user, self.edit_pass):
            w.setEnabled(not busy)
        self.btn_login.setText("Entrando…" if busy else "Entrar")

    def _submit(self) -> None:
        if self._worker is not None:
            return
        user, pwd = self.edit_user.text().strip(), self.edit_pass.text()
        if not user or not pwd:
            self._show_error("Introduce tu usuario y tu contraseña.")
            return
        self._set_busy(True)
        self._worker = auth.LoginWorker(user, pwd)
        self._worker.done.connect(self._on_result)
        self._worker.start()

    def _on_result(self, res: auth.AuthResult) -> None:
        worker, self._worker = self._worker, None
        if worker:
            worker.wait()
        self._set_busy(False)
        if res.ok:
            self.edit_pass.clear()
            self.authenticated.emit(res)
        else:
            self.edit_pass.clear()          # antes del mensaje: borrar el texto limpia el error
            self._show_error(res.error)
            self.edit_pass.setFocus()

    def _show_error(self, msg: str) -> None:
        self.error.setText(msg)

    def closeEvent(self, e):
        if self._worker is not None:
            self._worker.wait(3000)
        super().closeEvent(e)
