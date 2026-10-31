from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from models.conversation import Conversation
from models.dates import parse


def _fmt(iso: str) -> str:
    d = parse(iso)
    if d is None:
        return ""
    return d.strftime("Hoy %H:%M") if d.date() == datetime.now().date() else d.strftime("%d/%m/%Y")


class ConversationItem(QWidget):
    """Elemento del historial (título, fecha y botón de borrar)."""
    delete_requested = Signal(str)

    def __init__(self, conv: Conversation, deletable: bool = True, parent=None):
        super().__init__(parent)
        self.conv_id = conv.id
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 6, 6)

        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = QLabel()
        self.title.setObjectName("convTitle")
        self.date = QLabel()
        self.date.setObjectName("convDate")
        col.addWidget(self.title)
        col.addWidget(self.date)
        row.addLayout(col, 1)

        btn = QPushButton("✕")
        btn.setObjectName("btnDeleteConv")
        btn.setFixedSize(24, 24)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("Eliminar conversación")
        btn.clicked.connect(lambda: self.delete_requested.emit(self.conv_id))
        btn.setVisible(deletable)
        row.addWidget(btn)
        self.refresh(conv)

    def refresh(self, conv: Conversation) -> None:
        fm = self.title.fontMetrics()
        self.title.setText(fm.elidedText(conv.title, Qt.ElideRight, 170))
        self.date.setText(_fmt(conv.updated_at))
