from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
UI_FILE = BASE_DIR / "ui" / "main_window.ui"
STYLE_FILE = BASE_DIR / "assets" / "style.qss"
ICONS_DIR = BASE_DIR / "assets" / "icons"


def icon(name: str) -> str:
    return str(ICONS_DIR / name)

LOGIN_UI_FILE = BASE_DIR / "ui" / "login_window.ui"
IMAGES_DIR = BASE_DIR / "assets" / "images"


def image(name: str) -> str:
    return str(IMAGES_DIR / name)
