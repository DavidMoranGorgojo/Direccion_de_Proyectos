from datetime import datetime

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from components.chat_message import ChatMessage
from components.conversation_item import ConversationItem
from models.conversation import Conversation
from models.dates import parse
from models.message import ROLE_USER, Message
from models.response import Response
from paths import UI_FILE, icon, image
from services import api

MAX_BUBBLE_RATIO = 0.80
MAX_BUBBLE_PX = 780


class _EnterToSend(QObject):
    """Enter envía; Shift+Enter inserta salto de línea."""
    def __init__(self, on_send):
        super().__init__()
        self._on_send = on_send

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not (ev.modifiers() & Qt.ShiftModifier):
                self._on_send()
                return True
        return False


class MainWindow(QMainWindow):
    logged_out = Signal()

    def __init__(self, username: str = "anon"):
        super().__init__()
        self.username = username
        self.setWindowTitle("MR BOT by ARSOFT · Asistente técnico")
        self.setWindowIcon(QIcon(image("logo.png")))
        self.resize(1100, 720)
        self.setMinimumSize(720, 480)

        # --- cargar la interfaz diseñada en Qt Designer ---
        self.ui = QUiLoader().load(str(UI_FILE), self)
        self.setCentralWidget(self.ui)
        f = self.ui.findChild
        self.conversation_list: QListWidget = f(QListWidget, "conversationList")
        self.btn_new: QPushButton = f(QPushButton, "btnNewChat")
        self.btn_send: QPushButton = f(QPushButton, "btnSend")
        self.prompt: QPlainTextEdit = f(QPlainTextEdit, "promptInput")
        self.scroll: QScrollArea = f(QScrollArea, "chatScroll")
        self.chat_layout: QVBoxLayout = f(QVBoxLayout, "chatLayout")
        self.title_label: QLabel = f(QLabel, "labelChatTitle")
        self.mode_label: QLabel = f(QLabel, "labelMode")
        self.brand_label: QLabel = f(QLabel, "labelBrand")
        self.user_label: QLabel = f(QLabel, "labelUser")
        self.btn_logout: QPushButton = f(QPushButton, "btnLogout")
        self.brand_label.setTextFormat(Qt.RichText)
        self.brand_label.setText('MR <span style="color:#0893fa;">BOT</span> '
                                 '<span style="font-size:11px; color:#b7d3df;">by ARSOFT</span>')
        self.user_label.setText(f"👤 {username}")
        self.btn_logout.clicked.connect(self._logout)

        # iconos + modo
        self.btn_new.setIcon(QIcon(icon("plus.svg")))
        self.btn_send.setIcon(QIcon(icon("send.svg")))
        self.btn_send.setIconSize(QSize(20, 20))
        self._mock = api.is_mock()
        if self._mock:
            self.mode_label.setText("⚠ Modo simulado: sin backend conectado.\n"
                                    "Configura ARSOFT_API_URL en .env para usar el asistente real.")

        # --- estado ---
        # Modo real y simulado obtienen el historial por la misma vía: GET /chats (CTR-006).
        # El Frontend no guarda nada en local ni borra chats: el contrato no lo cubre.
        self.conversations = []
        self.current: Conversation | None = None
        self._rows: list[ChatMessage] = []
        self._typing: ChatMessage | None = None
        self._worker: api.ChatWorker | None = None
        self._hist_worker: api.HistoryWorker | None = None
        self._rating_workers: list[api.RatingWorker] = []

        # --- señales ---
        self.btn_new.clicked.connect(self.new_chat)
        self.btn_send.clicked.connect(self.send)
        self.conversation_list.currentItemChanged.connect(self._on_select)
        self._filter = _EnterToSend(self.send)
        self.prompt.installEventFilter(self._filter)
        self.prompt.textChanged.connect(self._autosize_prompt)

        self._refresh_list()
        self.new_chat()
        self._load_history()

    # ------------------------------------------------------------ historial
    def _load_history(self) -> None:
        """GET /chats (CTR-006) en un hilo aparte, con estado de carga."""
        self.mode_label.setText("Cargando historial…")
        self.btn_send.setEnabled(False)
        self._hist_worker = api.HistoryWorker()
        self._hist_worker.done.connect(self._on_history)
        self._hist_worker.start()

    def _on_history(self, res: api.HistoryResult) -> None:
        worker, self._hist_worker = self._hist_worker, None
        if worker:
            worker.wait()
        if res.ok:
            if self._mock:
                self.mode_label.setText("⚠ Modo simulado: sin backend conectado.\n"
                                        "Configura ARSOFT_API_URL en .env para usar el asistente real.")
            else:
                self.mode_label.setText(
                    "" if res.conversations else "Todavía no tienes conversaciones.")
            self.conversations = res.conversations
            self.current = None
            if self.conversations:
                self.conversations.sort(key=self._sort_key, reverse=True)
                self._select(self.conversations[0].id)
            else:
                self.new_chat()
            self._refresh_list()
            self.btn_send.setEnabled(True)
            return
        if res.session_expired:
            QMessageBox.information(self, "Sesión caducada", res.error)
            self.logged_out.emit()
            return
        self.mode_label.setText("No se ha podido cargar el historial.")
        self.btn_send.setEnabled(True)
        if QMessageBox.warning(self, "Historial", f"{res.error}\n¿Quieres reintentarlo?",
                               QMessageBox.Retry | QMessageBox.Cancel) == QMessageBox.Retry:
            self._load_history()

    @staticmethod
    def _sort_key(c: Conversation) -> datetime:
        return parse(c.updated_at) or datetime.min

    def _refresh_list(self) -> None:
        self.conversations.sort(key=self._sort_key, reverse=True)
        self.conversation_list.blockSignals(True)
        self.conversation_list.clear()
        for c in self.conversations:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, c.id)
            w = ConversationItem(c)
            item.setSizeHint(QSize(0, 52))
            self.conversation_list.addItem(item)
            self.conversation_list.setItemWidget(item, w)
            if self.current and c.id == self.current.id:
                self.conversation_list.setCurrentItem(item)
        self.conversation_list.blockSignals(False)

    def _on_select(self, item, _prev=None) -> None:
        if item is not None:
            self._select(item.data(Qt.UserRole))

    def _select(self, conv_id: str) -> None:
        conv = next((c for c in self.conversations if c.id == conv_id), None)
        if conv is None or (self.current and self.current.id == conv_id and self._rows):
            return
        self.current = conv
        self.title_label.setText(conv.title)
        self._render_conversation()
        self._refresh_list()

    def new_chat(self) -> None:
        # Si ya hay un chat vacío, se reutiliza en vez de apilar chats vacíos.
        empty = next((c for c in self.conversations if not c.messages), None)
        if empty is None:
            empty = Conversation()
            self.conversations.append(empty)
        self.current = None
        self._select(empty.id)
        self.prompt.setFocus()

    # ---------------------------------------------------------------- chat
    def _clear_chat(self) -> None:
        while self.chat_layout.count():
            w = self.chat_layout.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._rows.clear()
        self._typing = None
        self._empty = None

    def _render_conversation(self) -> None:
        self._clear_chat()
        if not self.current.messages:
            self._add_empty_state()
        for m in self.current.messages:
            self._add_bubble(m)
        self.chat_layout.addStretch()
        self._update_widths()
        self._scroll_bottom()

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
        self._empty = box

    def _remove_empty_state(self) -> None:
        box = getattr(self, "_empty", None)
        if box is not None:
            self.chat_layout.removeWidget(box)
            box.hide()
            box.setParent(None)
            box.deleteLater()
            self._empty = None

    def _add_bubble(self, m: Message) -> ChatMessage:
        row = ChatMessage(m)
        if row.btn_up is not None:                # respuesta valorable (estado "respuesta" con trace_id)
            row.rating_requested.connect(lambda util, r=row, msg=m: self._rate(r, msg, util))
        self._insert_row(row)
        return row

    # ----------------------------------------------------------- valoración
    def _rate(self, row: ChatMessage, msg: Message, util: bool) -> None:
        """POST /valoracion. Se marca el botón al momento; si falla, se vuelve al valor anterior."""
        if msg.rating is util or not msg.trace_id:
            row.set_rating(msg.rating)            # el botón es marcable: se deja como estaba
            return
        previous = msg.rating
        row.clear_rating_error()
        row.set_rating(util)
        row.set_rating_enabled(False)
        worker = api.RatingWorker(msg.trace_id, util)
        worker.done.connect(lambda res, r=row, m=msg, p=previous, w=worker:
                            self._on_rating(r, m, p, w, res))
        self._rating_workers.append(worker)
        worker.start()

    def _on_rating(self, row: ChatMessage, msg: Message, previous: bool | None,
                   worker: api.RatingWorker, res: api.RatingResult) -> None:
        worker.wait()
        if worker in self._rating_workers:
            self._rating_workers.remove(worker)
        alive = row in self._rows                 # la fila ya no existe si se cambió de chat
        if res.ok:
            msg.rating = res.util
            if alive:
                row.set_rating(res.util)
                row.set_rating_enabled(True)
            return
        if alive:
            row.set_rating(previous)
            row.set_rating_enabled(True)
            row.show_rating_error(res.error)
        if res.session_expired:
            QMessageBox.information(self, "Sesión caducada", res.error)
            self.logged_out.emit()

    def _insert_row(self, row: ChatMessage) -> None:
        # inserta antes del stretch final (si existe)
        idx = self.chat_layout.count()
        if idx and self.chat_layout.itemAt(idx - 1).spacerItem():
            idx -= 1
        self.chat_layout.insertWidget(idx, row)
        self._rows.append(row)
        row.set_max_width(self._bubble_width())

    def _bubble_width(self) -> int:
        return min(MAX_BUBBLE_PX, int(self.scroll.viewport().width() * MAX_BUBBLE_RATIO))

    def _update_widths(self) -> None:
        for r in self._rows:
            r.set_max_width(self._bubble_width())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_widths()

    def _scroll_bottom(self) -> None:
        QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def _autosize_prompt(self) -> None:
        h = int(self.prompt.document().size().height()) + 14
        self.prompt.setFixedHeight(max(40, min(140, h)))

    # -------------------------------------------------------------- envío
    def send(self) -> None:
        # CTR-001: la pregunta llega a Agentes EXACTAMENTE como se escribió (sin strip ni recortes).
        text = self.prompt.toPlainText()
        if not text.strip() or self._worker is not None or self.current is None:
            return
        if self._hist_worker is not None:         # mientras carga el historial
            return
        conv = self.current
        if not conv.messages:                     # primer mensaje: quitar pantalla vacía
            self._remove_empty_state()
            short = text.strip()
            conv.title = short[:40] + ("…" if len(short) > 40 else "")
            self.title_label.setText(conv.title)
            if not self._mock:
                self.mode_label.setText("")

        user_msg = Message(ROLE_USER, text)
        conv.messages.append(user_msg)
        conv.touch()
        self._add_bubble(user_msg)
        self.prompt.clear()
        self._refresh_list()

        self._typing = ChatMessage(None)
        self._insert_row(self._typing)
        self._set_busy(True)
        self._scroll_bottom()

        self._worker = api.ChatWorker(conv.server_id, text)   # sin historial: lo guarda Agentes
        self._worker.finished_ok.connect(lambda r, c=conv: self._on_response(c, r))
        self._worker.start()

    def _on_response(self, conv: Conversation, resp: Response) -> None:
        worker, self._worker = self._worker, None
        if worker:
            worker.wait()
        if self._typing is not None:
            self._rows.remove(self._typing)
            self._typing.deleteLater()
            self._typing = None
        if resp.conversacion_id:
            conv.server_id = resp.conversacion_id
        msg = Message.from_response(resp)
        conv.messages.append(msg)
        conv.touch()
        if self.current is conv:                 # solo se pinta si sigue abierta
            self._add_bubble(msg)
            self._scroll_bottom()
        self._refresh_list()
        self._set_busy(False)
        self.prompt.setFocus()
        if resp.codigo_error == "sesion_caducada":   # como con el historial: no se deja seguir sin sesión
            QMessageBox.information(self, "Sesión caducada", resp.texto)
            self.logged_out.emit()

    def _set_busy(self, busy: bool) -> None:
        self.btn_send.setEnabled(not busy)

    def _logout(self) -> None:
        if self._worker is not None or self._hist_worker is not None:
            QMessageBox.information(self, "Cerrar sesión",
                                    "Espera a que termine la respuesta en curso.")
            return
        self.logged_out.emit()

    def closeEvent(self, e):
        for w in (self._worker, self._hist_worker, *self._rating_workers):
            if w is not None:
                w.wait(3000)
        super().closeEvent(e)
