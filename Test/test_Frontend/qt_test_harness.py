"""
Arnés de pruebas para PySide6 (Headless / Pure Python Mock).
============================================================
Permite instanciar y probar componentes visuales y ventanas de la interfaz
(LoginWindow, MainWindow, ChatMessage, ConversationItem, SourceCard) sin
depender de servidores X11/Wayland, DLLs gráficas nativas o configuraciones
de pantalla.
"""

from __future__ import annotations
import sys
import types
import xml.etree.ElementTree as ET


def setup_qt_harness() -> None:
    """Configura los módulos mock de PySide6 en sys.modules si no están cargados."""
    # Módulos a crear o sobreescribir
    pyside6 = sys.modules.get("PySide6", types.ModuleType("PySide6"))
    qt_core = types.ModuleType("PySide6.QtCore")
    qt_gui = types.ModuleType("PySide6.QtGui")
    qt_widgets = types.ModuleType("PySide6.QtWidgets")
    qt_uitools = types.ModuleType("PySide6.QtUiTools")

    # ------------------------------------------------------------- QtCore
    class Signal:
        def __init__(self, *types_):
            self._slots = []

        def connect(self, slot):
            if slot not in self._slots:
                self._slots.append(slot)

        def disconnect(self, slot=None):
            if slot is None:
                self._slots.clear()
            elif slot in self._slots:
                self._slots.remove(slot)

        def emit(self, *args, **kwargs):
            for slot in list(self._slots):
                try:
                    slot(*args, **kwargs)
                except TypeError:
                    try:
                        slot()
                    except Exception:
                        pass

    class Qt:
        Key_Return = 0x01000004
        Key_Enter = 0x01000005
        Key_Escape = 0x01000000
        ShiftModifier = 0x02000000
        RichText = 1
        PlainText = 0
        MarkdownText = 2
        AlignCenter = 0x0084
        AlignRight = 0x0002
        AlignHCenter = 0x0004
        AlignTop = 0x0020
        UserRole = 32
        KeepAspectRatio = 1
        SmoothTransformation = 2
        ElideRight = 1
        TextSelectableByMouse = 1
        WA_TransparentForMouseEvents = 1

    class QSize:
        def __init__(self, w=0, h=0):
            self._w, self._h = w, h

        def width(self):
            return self._w

        def height(self):
            return self._h

    class QEvent:
        KeyPress = 6

        def __init__(self, event_type, key=None, modifiers=0):
            self._type = event_type
            self._key = key
            self._modifiers = modifiers

        def type(self):
            return self._type

        def key(self):
            return self._key

        def modifiers(self):
            return self._modifiers

    class QObject:
        def __init__(self, parent=None):
            self._parent = parent

        def eventFilter(self, watched, event):
            return False

    class QTimer:
        @staticmethod
        def singleShot(ms, callback):
            try:
                callback()
            except Exception:
                pass

    class QThread:
        def __init__(self, parent=None):
            pass

        def start(self):
            self.run()

        def wait(self, timeout=None):
            pass

        def run(self):
            pass

    qt_core.Signal = Signal
    qt_core.Qt = Qt
    qt_core.QSize = QSize
    qt_core.QEvent = QEvent
    qt_core.QObject = QObject
    qt_core.QTimer = QTimer
    qt_core.QThread = QThread

    # ------------------------------------------------------------- QtGui
    class QIcon:
        def __init__(self, path=None):
            self.path = path

    class QPixmap:
        def __init__(self, path=None):
            self.path = path

        def scaled(self, w, h, *args):
            return self

        def scaledToHeight(self, h, *args):
            return self

    qt_gui.QIcon = QIcon
    qt_gui.QPixmap = QPixmap

    # ------------------------------------------------------------- QtWidgets
    class FontMetricsMock:
        def elidedText(self, text, mode, width):
            if len(text) > 25:
                return text[:22] + "…"
            return text

        def horizontalAdvance(self, text):
            return len(text) * 8

    class QWidget(QObject):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._object_name = ""
            self._properties = {}
            self._enabled = True
            self._visible = True
            self._window_title = ""
            self._window_icon = None
            self._layout = None
            self._children = []
            self._minimum_width = 0
            self._maximum_width = 16777215
            self._fixed_height = None
            self._focused = False
            if parent is not None and hasattr(parent, "_add_child"):
                parent._add_child(self)

        def _add_child(self, child):
            if child not in self._children:
                self._children.append(child)

        def objectName(self):
            return self._object_name

        def setObjectName(self, name):
            self._object_name = name

        def property(self, name):
            return self._properties.get(name)

        def setProperty(self, name, value):
            self._properties[name] = value

        def windowTitle(self):
            return self._window_title

        def setWindowTitle(self, title):
            self._window_title = title

        def setWindowIcon(self, icon):
            self._window_icon = icon

        def resize(self, w, h):
            pass

        def setMinimumSize(self, w, h):
            pass

        def setContentsMargins(self, *args):
            pass

        def setAttribute(self, attr, value):
            pass

        def setSizePolicy(self, h, v):
            pass

        def isEnabled(self):
            return self._enabled

        def setEnabled(self, enabled):
            self._enabled = bool(enabled)

        def setFocus(self):
            self._focused = True

        def hasFocus(self):
            return self._focused

        def show(self):
            self._visible = True

        def hide(self):
            self._visible = False

        def close(self):
            self._visible = False

        def deleteLater(self):
            if self._parent and hasattr(self._parent, "_children"):
                if self in self._parent._children:
                    self._parent._children.remove(self)

        def setParent(self, parent):
            self._parent = parent

        def layout(self):
            return self._layout

        def setLayout(self, layout):
            self._layout = layout

        def setMaximumWidth(self, w):
            self._maximum_width = w

        def setMinimumWidth(self, w):
            self._minimum_width = w

        def setFixedHeight(self, h):
            self._fixed_height = h

        def findChild(self, cls, name=None):
            def search(obj):
                for child in getattr(obj, "_children", []):
                    type_match = isinstance(child, cls) if cls else True
                    name_match = (name is None or getattr(child, "_object_name", "") == name)
                    if type_match and name_match:
                        return child
                    found = search(child)
                    if found:
                        return found
                return None
            return search(self)

        def findChildren(self, cls, name=None):
            res = []
            seen = set()
            def search(obj):
                for child in getattr(obj, "_children", []):
                    type_match = isinstance(child, cls) if cls else True
                    name_match = (name is None or getattr(child, "_object_name", "") == name)
                    if type_match and name_match and id(child) not in seen:
                        seen.add(id(child))
                        res.append(child)
                    search(child)
            search(self)
            return res

    class QMainWindow(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._central_widget = None

        def setCentralWidget(self, widget):
            self._central_widget = widget
            self._add_child(widget)

        def centralWidget(self):
            return self._central_widget

    class QLabel(QWidget):
        def __init__(self, text="", parent=None):
            super().__init__(parent)
            self._text = str(text) if text is not None else ""
            self._pixmap = None
            self._alignment = None
            self._format = Qt.PlainText
            self._word_wrap = False
            self._style_sheet = ""

        def text(self):
            return self._text

        def setText(self, text):
            self._text = str(text) if text is not None else ""

        def pixmap(self):
            return self._pixmap

        def setPixmap(self, pixmap):
            self._pixmap = pixmap

        def setAlignment(self, align):
            self._alignment = align

        def setTextFormat(self, fmt):
            self._format = fmt

        def setTextInteractionFlags(self, flags):
            pass

        def setWordWrap(self, wrap):
            self._word_wrap = wrap

        def setStyleSheet(self, css):
            self._style_sheet = css

        def fontMetrics(self):
            return FontMetricsMock()

    class QLineEdit(QWidget):
        Normal = 0
        Password = 2

        def __init__(self, parent=None):
            super().__init__(parent)
            self._text = ""
            self._echo_mode = QLineEdit.Normal
            self.returnPressed = Signal()
            self.textChanged = Signal(str)

        def text(self):
            return self._text

        def setText(self, text):
            self._text = str(text)
            self.textChanged.emit(self._text)

        def clear(self):
            self.setText("")

        def echoMode(self):
            return self._echo_mode

        def setEchoMode(self, mode):
            self._echo_mode = mode

    class QPushButton(QWidget):
        def __init__(self, text="", parent=None):
            super().__init__(parent)
            self._text = text
            self._icon = None
            self._icon_size = None
            self._checkable = False
            self._checked = False
            self.clicked = Signal()
            self.toggled = Signal(bool)

        def text(self):
            return self._text

        def setText(self, text):
            self._text = text

        def setIcon(self, icon):
            self._icon = icon

        def setIconSize(self, size):
            self._icon_size = size

        def isChecked(self):
            return self._checked

        def setChecked(self, checked):
            if self._checked != bool(checked):
                self._checked = bool(checked)
                self.toggled.emit(self._checked)

        def isCheckable(self):
            return self._checkable

        def setCheckable(self, checkable):
            self._checkable = bool(checkable)

        def click(self):
            if self._enabled:
                if self._checkable:
                    self.setChecked(not self._checked)
                self.clicked.emit()

    class DocumentMock:
        class SizeMock:
            def height(self):
                return 40

        def size(self):
            return self.SizeMock()

    class QPlainTextEdit(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._text = ""
            self._filter = None
            self.textChanged = Signal()

        def toPlainText(self):
            return self._text

        def setPlainText(self, text):
            self._text = str(text)
            self.textChanged.emit()

        def clear(self):
            self.setPlainText("")

        def document(self):
            return DocumentMock()

        def installEventFilter(self, filter_obj):
            self._filter = filter_obj

    class QListWidgetItem:
        def __init__(self, text="", parent=None):
            self._text = text
            self._data = {}
            self._size_hint = None

        def setData(self, role, value):
            self._data[role] = value

        def data(self, role):
            return self._data.get(role)

        def setSizeHint(self, size):
            self._size_hint = size

    class QListWidget(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._items: list[QListWidgetItem] = []
            self._item_widgets: dict[QListWidgetItem, QWidget] = {}
            self._current_item = None
            self._signals_blocked = False
            self.currentItemChanged = Signal(object, object)

        def addItem(self, item):
            self._items.append(item)

        def setItemWidget(self, item, widget):
            self._item_widgets[item] = widget
            self._add_child(widget)

        def itemWidget(self, item):
            return self._item_widgets.get(item)

        def clear(self):
            self._items.clear()
            self._item_widgets.clear()
            self._current_item = None

        def count(self):
            return len(self._items)

        def item(self, index):
            return self._items[index] if 0 <= index < len(self._items) else None

        def currentItem(self):
            return self._current_item

        def setCurrentItem(self, item):
            prev = self._current_item
            self._current_item = item
            if not self._signals_blocked:
                self.currentItemChanged.emit(item, prev)

        def blockSignals(self, block):
            prev = self._signals_blocked
            self._signals_blocked = bool(block)
            return prev

    class ScrollBarMock:
        def __init__(self):
            self._val = 0

        def setValue(self, val):
            self._val = val

        def value(self):
            return self._val

        def maximum(self):
            return 1000

    class ViewportMock:
        def width(self):
            return 800

    class QScrollArea(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._viewport = ViewportMock()
            self._vbar = ScrollBarMock()

        def viewport(self):
            return self._viewport

        def verticalScrollBar(self):
            return self._vbar

    class QLayoutItem:
        def __init__(self, widget=None, is_stretch=False):
            self._widget = widget
            self._is_stretch = is_stretch

        def widget(self):
            return self._widget

        def spacerItem(self):
            return self if self._is_stretch else None

    class QBoxLayout(QObject):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._object_name = ""
            self._items: list[QLayoutItem] = []
            self._spacing = 0
            self._alignment = None
            self._children = []
            if parent is not None and hasattr(parent, "_add_child"):
                parent._add_child(self)
                if hasattr(parent, "setLayout"):
                    parent.setLayout(self)

        def _add_child(self, child):
            if child not in self._children:
                self._children.append(child)

        def setObjectName(self, name):
            self._object_name = name

        def objectName(self):
            return self._object_name

        def setContentsMargins(self, *args):
            pass

        def setSpacing(self, spacing):
            self._spacing = spacing

        def setAlignment(self, align):
            self._alignment = align

        def addWidget(self, widget):
            self._items.append(QLayoutItem(widget=widget))
            self._add_child(widget)
            if hasattr(self._parent, "_add_child"):
                self._parent._add_child(widget)

        def addLayout(self, layout, stretch=0):
            self._add_child(layout)

        def addStretch(self):
            self._items.append(QLayoutItem(is_stretch=True))

        def count(self):
            return len(self._items)

        def itemAt(self, index):
            return self._items[index] if 0 <= index < len(self._items) else None

        def takeAt(self, index):
            if 0 <= index < len(self._items):
                return self._items.pop(index)
            return None

        def removeWidget(self, widget):
            self._items = [i for i in self._items if i.widget() != widget]

        def insertWidget(self, index, widget):
            self._items.insert(index, QLayoutItem(widget=widget))
            self._add_child(widget)
            if hasattr(self._parent, "_add_child"):
                self._parent._add_child(widget)

    class QVBoxLayout(QBoxLayout):
        pass

    class QHBoxLayout(QBoxLayout):
        pass

    class QFrame(QWidget):
        pass

    class QSizePolicy:
        Maximum = 1
        Fixed = 0

        def __init__(self, h, v):
            pass

    class QMessageBox:
        Information = 1
        Warning = 2
        Retry = 1
        Cancel = 2

        @classmethod
        def information(cls, parent, title, text, *args):
            return cls.Cancel

        @classmethod
        def warning(cls, parent, title, text, *args):
            return cls.Cancel

    class QApplication:
        def __init__(self, argv=None):
            pass

        def setStyleSheet(self, css):
            pass

        def exec(self):
            return 0

    qt_widgets.QWidget = QWidget
    qt_widgets.QMainWindow = QMainWindow
    qt_widgets.QLabel = QLabel
    qt_widgets.QLineEdit = QLineEdit
    qt_widgets.QPushButton = QPushButton
    qt_widgets.QPlainTextEdit = QPlainTextEdit
    qt_widgets.QListWidget = QListWidget
    qt_widgets.QListWidgetItem = QListWidgetItem
    qt_widgets.QScrollArea = QScrollArea
    qt_widgets.QBoxLayout = QBoxLayout
    qt_widgets.QVBoxLayout = QVBoxLayout
    qt_widgets.QHBoxLayout = QHBoxLayout
    qt_widgets.QFrame = QFrame
    qt_widgets.QSizePolicy = QSizePolicy
    qt_widgets.QMessageBox = QMessageBox
    qt_widgets.QApplication = QApplication

    # ------------------------------------------------------------- QtUiTools
    class QUiLoader:
        def load(self, file_path, parent=None):
            tree = ET.parse(file_path)
            root = tree.getroot()
            root_elem = root.find("widget")
            if root_elem is None:
                return QWidget(parent)

            widget_dict = {
                "QWidget": QWidget,
                "QFrame": QFrame,
                "QLabel": QLabel,
                "QLineEdit": QLineEdit,
                "QPushButton": QPushButton,
                "QPlainTextEdit": QPlainTextEdit,
                "QListWidget": QListWidget,
                "QScrollArea": QScrollArea,
            }
            layout_dict = {
                "QVBoxLayout": QVBoxLayout,
                "QHBoxLayout": QHBoxLayout,
            }

            def parse_node(elem, p_obj):
                if elem.tag == "widget":
                    w_class = elem.attrib.get("class", "QWidget")
                    w_name = elem.attrib.get("name", "")
                    cls = widget_dict.get(w_class, QWidget)
                    if cls in (QLabel, QPushButton):
                        inst = cls("", parent=p_obj)
                    else:
                        inst = cls(parent=p_obj)
                    inst.setObjectName(w_name)
                    for prop in elem.findall("property"):
                        p_name = prop.attrib.get("name")
                        if p_name == "text":
                            str_elem = prop.find("string")
                            if str_elem is not None and str_elem.text:
                                inst.setText(str_elem.text)
                        elif p_name == "echoMode":
                            enum_elem = prop.find("enum")
                            if enum_elem is not None and "Password" in (enum_elem.text or ""):
                                inst.setEchoMode(QLineEdit.Password)
                    for child in elem:
                        parse_node(child, inst)
                    return inst
                elif elem.tag == "layout":
                    l_class = elem.attrib.get("class", "QVBoxLayout")
                    l_name = elem.attrib.get("name", "")
                    l_cls = layout_dict.get(l_class, QVBoxLayout)
                    l_inst = l_cls(parent=p_obj)
                    l_inst.setObjectName(l_name)
                    for child in elem:
                        parse_node(child, p_obj)
                    return l_inst
                elif elem.tag == "item":
                    for child in elem:
                        parse_node(child, p_obj)
                return None

            return parse_node(root_elem, parent)

    qt_uitools.QUiLoader = QUiLoader

    # Inyectar en sys.modules
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qt_core
    sys.modules["PySide6.QtGui"] = qt_gui
    sys.modules["PySide6.QtWidgets"] = qt_widgets
    sys.modules["PySide6.QtUiTools"] = qt_uitools
    pyside6.QtCore = qt_core
    pyside6.QtGui = qt_gui
    pyside6.QtWidgets = qt_widgets
    pyside6.QtUiTools = qt_uitools


setup_qt_harness()
