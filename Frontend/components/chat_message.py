from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from components.source_card import SourceCard
from models.message import Message
from models.dates import parse
from models.response import (STATUS_CLARIFY, STATUS_ERROR, STATUS_NO_EVIDENCE,
                             STATUS_OUT_OF_SCOPE)

BADGES = {
    STATUS_CLARIFY: "Necesito más datos",
    STATUS_NO_EVIDENCE: "Sin evidencia en la documentación",
    STATUS_OUT_OF_SCOPE: "Fuera de ámbito",
    STATUS_ERROR: "Error",
}


def _badge(text: str, kind: str) -> QLabel:
    b = QLabel(text)
    b.setObjectName("badge")
    b.setProperty("kind", kind)
    b.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return b


class ChatMessage(QWidget):
    """Una fila del chat: burbuja del usuario (derecha) o del asistente (izquierda)."""

    def __init__(self, message: Message | None = None, text: str | None = None, parent=None):
        super().__init__(parent)
        self.bubble = QFrame()
        col = QVBoxLayout(self.bubble)
        col.setContentsMargins(16, 12, 16, 10)
        col.setSpacing(8)

        if message is None:                       # burbuja "escribiendo…"
            self.bubble.setObjectName("bubbleBot")
            self.label = QLabel(text or "Buscando en la documentación…")
            self.label.setStyleSheet("color:#8a93a3; font-style:italic;")
            col.addWidget(self.label)
        elif message.is_user:
            self.bubble.setObjectName("bubbleUser")
            self._add_text(col, message.text, markdown=False)
        else:
            self.bubble.setObjectName("bubbleBot")
            self.bubble.setProperty("status", message.status)
            badges = QHBoxLayout()
            badges.setSpacing(6)
            if message.status in BADGES:
                badges.addWidget(_badge(BADGES[message.status], message.status))
            if badges.count():
                badges.addStretch()
                col.addLayout(badges)
            self._add_text(col, message.text, markdown=True)
            if message.sources:
                title = QLabel("FUENTES")
                title.setObjectName("sourcesTitle")
                col.addWidget(title)
                for s in message.sources:
                    col.addWidget(SourceCard(s))

        if message is not None and message.timestamp:
            d = parse(message.timestamp)
            hhmm = d.strftime("%H:%M") if d else ""
            t = QLabel(hhmm)
            t.setObjectName("timeLabel")
            t.setAlignment(Qt.AlignRight)
            col.addWidget(t)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        if message is not None and message.is_user:
            row.addStretch()
            row.addWidget(self.bubble)
        else:
            row.addWidget(self.bubble)
            row.addStretch()

    def _add_text(self, layout, text: str, markdown: bool) -> None:
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setTextFormat(Qt.MarkdownText if markdown else Qt.PlainText)
        layout.addWidget(self.label)

    def set_max_width(self, width: int) -> None:
        width = max(240, width)
        self.bubble.setMaximumWidth(width)
        # Ancho natural del texto (para que las burbujas cortas no se envuelvan)
        fm = self.label.fontMetrics()
        lines = self.label.text().splitlines() or [""]
        natural = max(fm.horizontalAdvance(l) for l in lines) + 8
        has_extras = self.bubble.findChild(SourceCard) is not None
        wanted = width - 32 if has_extras else min(natural, width - 32)
        self.label.setMinimumWidth(max(40, wanted))
