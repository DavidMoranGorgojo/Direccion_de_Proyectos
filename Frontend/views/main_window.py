from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import QSize
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (QLabel, QMainWindow, QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from paths import UI_FILE, icon, image


class MainWindow(QMainWindow):
    logged_out = Signal()

    def __init__(self, username: str = "anon"):
        super().__init__()
        self.setWindowTitle("MR BOT by ARSOFT · Asistente técnico")
        self.setWindowIcon(QIcon(image("logo.png")))
        self.resize(1100, 720)
        self.setMinimumSize(720, 480)

        self.ui = QUiLoader().load(str(UI_FILE), self)
        self.setCentralWidget(self.ui)
        f = self.ui.findChild
        self.btn_new: QPushButton = f(QPushButton, "btnNewChat")
        self.btn_send: QPushButton = f(QPushButton, "btnSend")
        self.prompt: QPlainTextEdit = f(QPlainTextEdit, "promptInput")
        self.chat_layout: QVBoxLayout = f(QVBoxLayout, "chatLayout")
        self.mode_label: QLabel = f(QLabel, "labelMode")
        self.brand_label: QLabel = f(QLabel, "labelBrand")
        self.user_label: QLabel = f(QLabel, "labelUser")
        self.btn_logout: QPushButton = f(QPushButton, "btnLogout")

        self.brand_label.setTextFormat(Qt.RichText)
        self.brand_label.setText('MR <span style="color:#0893fa;">BOT</span> '
                                 '<span style="font-size:11px; color:#b7d3df;">by ARSOFT</span>')
        self.user_label.setText(f"👤 {username}")
        self.btn_logout.clicked.connect(self.logged_out.emit)

        self.btn_new.setIcon(QIcon(icon("plus.svg")))
        self.btn_send.setIcon(QIcon(icon("send.svg")))
        self.btn_send.setIconSize(QSize(20, 20))

        # Solo vista: se desactiva todo lo que sirve para usar el chat.
        for w in (self.btn_new, self.btn_send, self.prompt):
            w.setEnabled(False)
        self._add_empty_state()
        self.chat_layout.addStretch()

    def _add_empty_state(self) -> None:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setAlignment(Qt.AlignHCenter)
        lay.setSpacing(6)
        ico = QLabel()
        ico.setPixmap(QPixmap(icon("app.svg")).scaled(56, 56, Qt.KeepAspectRatio,
                                                      Qt.SmoothTransformation))
        ico.setAlignment(Qt.AlignHCenter)
        t = QLabel("¿En qué puedo ayudarte?")
        t.setObjectName("labelEmptyTitle")
        t.setAlignment(Qt.AlignHCenter)
        s = QLabel("Pregunta cualquier duda técnica sobre un vehículo.\n"
                   "Responderé solo con la documentación disponible y te mostraré la fuente.")
        s.setObjectName("labelEmptyText")
        s.setAlignment(Qt.AlignHCenter)
        for w in (ico, t, s):
            lay.addWidget(w)
        box.setContentsMargins(0, 80, 0, 0)
        self.chat_layout.addWidget(box)
