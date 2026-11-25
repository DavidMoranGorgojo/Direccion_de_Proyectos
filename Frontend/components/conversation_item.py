from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from models.conversation import Conversation
from models.dates import parse


def _fmt(iso: str) -> str:
    d = parse(iso)
    if d is None:
        return ""
    return d.strftime("Hoy %H:%M") if d.date() == datetime.now().date() else d.strftime("%d/%m/%Y")


class ConversationItem(QWidget):
    """Elemento del historial con acciones para chats persistidos."""

    rename_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, conv: Conversation, parent=None, editable: bool = True):
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

        self.btn_rename = QPushButton("✎")
        self.btn_rename.setObjectName("btnRenameConv")
        self.btn_rename.setToolTip("Renombrar conversación")
        self.btn_rename.setAccessibleName("Renombrar conversación")
        self.btn_rename.setFixedSize(26, 28)
        self.btn_rename.setFocusPolicy(Qt.NoFocus)
        self.btn_rename.clicked.connect(lambda: self.rename_requested.emit(self.conv_id))
        row.addWidget(self.btn_rename)

        self.btn_delete = QPushButton("×")
        self.btn_delete.setObjectName("btnDeleteConv")
        self.btn_delete.setToolTip("Eliminar conversación")
        self.btn_delete.setAccessibleName("Eliminar conversación")
        self.btn_delete.setFixedSize(26, 28)
        self.btn_delete.setFocusPolicy(Qt.NoFocus)
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit(self.conv_id))
        row.addWidget(self.btn_delete)

        self.btn_rename.setVisible(editable)
        self.btn_delete.setVisible(editable)
        self.refresh(conv)

    def set_actions_enabled(self, enabled: bool) -> None:
        self.btn_rename.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)

    def refresh(self, conv: Conversation) -> None:
        fm = self.title.fontMetrics()
        self.title.setText(fm.elidedText(conv.title, Qt.ElideRight, 170))
        self.date.setText(_fmt(conv.updated_at))
