from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from models.source import Source
from paths import icon


class SourceCard(QFrame):
    """Tarjeta con documento, sección, página y versiones en que se basa la respuesta."""

    def __init__(self, source: Source, parent=None):
        super().__init__(parent)
        self.setObjectName("sourceCard")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)

        ico = QLabel()
        ico.setPixmap(QPixmap(icon("document.svg")).scaled(
            20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        ico.setAlignment(Qt.AlignTop)
        row.addWidget(ico)

        col = QVBoxLayout()
        col.setSpacing(1)
        doc = QLabel(source.documento)
        doc.setObjectName("sourceDoc")
        col.addWidget(doc)

        meta = " · ".join(p for p in (
            source.seccion and f"sección {source.seccion}",
            source.pagina and f"pág. {source.pagina}",
            source.versiones and "versiones " + ", ".join(source.versiones)) if p)
        if meta:
            m = QLabel(meta)
            m.setObjectName("sourceMeta")
            col.addWidget(m)
        if source.obsoleto:
            o = QLabel("Documento sustituido (obsoleto)")
            o.setObjectName("sourceObsolete")
            col.addWidget(o)
        row.addLayout(col, 1)
