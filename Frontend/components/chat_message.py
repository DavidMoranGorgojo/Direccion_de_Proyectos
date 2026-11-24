from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from components.source_card import SourceCard
from models.message import Message
from models.dates import parse
from models.response import (STATUS_CLARIFY, STATUS_ERROR, STATUS_NO_EVIDENCE, STATUS_OK,
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

    rating_requested = Signal(bool)           # True = útil (👍), False = no útil (👎)

    def __init__(self, message: Message | None = None, text: str | None = None, parent=None):
        super().__init__(parent)
        self.btn_up = self.btn_down = self.rating_error = None   # solo existen en respuestas valorables
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
            if message.status == STATUS_OK and message.trace_id:   # el Backend solo valora "respuesta"
                col.addLayout(self._build_rating(message.rating))

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

    # ------------------------------------------------------------ valoración
    def _build_rating(self, current: bool | None) -> QHBoxLayout:
        box = QHBoxLayout()
        box.setSpacing(6)
        self.btn_up = self._rate_button("👍", "Respuesta útil", True)
        self.btn_down = self._rate_button("👎", "Respuesta no útil", False)
        self.rating_error = QLabel()
        self.rating_error.setObjectName("ratingError")
        self.rating_error.setWordWrap(True)
        self.rating_error.hide()
        box.addWidget(self.btn_up)
        box.addWidget(self.btn_down)
        box.addWidget(self.rating_error)
        self.set_rating(current)
        return box

    def _rate_button(self, icon: str, tip: str, util: bool) -> QPushButton:
        b = QPushButton(icon)
        b.setObjectName("btnRate")
        b.setToolTip(tip)
        b.setCheckable(True)                       # el botón elegido queda marcado (:checked)
        b.clicked.connect(lambda _=False, u=util: self.rating_requested.emit(u))
        return b

    def set_rating(self, util: bool | None) -> None:
        """Marca el botón elegido (None = ninguno)."""
        if self.btn_up is None:
            return
        for btn, value in ((self.btn_up, True), (self.btn_down, False)):
            btn.setChecked(util is value)

    def set_rating_enabled(self, enabled: bool) -> None:
        if self.btn_up is not None:
            self.btn_up.setEnabled(enabled)
            self.btn_down.setEnabled(enabled)

    def show_rating_error(self, text: str) -> None:
        if self.rating_error is not None:
            self.rating_error.setText(text)
            self.rating_error.show()

    def clear_rating_error(self) -> None:
        if self.rating_error is not None:
            self.rating_error.setText("")
            self.rating_error.hide()

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
