"""Guarda el historial de conversaciones en un JSON local (~/.arsoft_asistente)."""
from __future__ import annotations
import json
from pathlib import Path

from models.conversation import Conversation

DATA_DIR = Path.home() / ".arsoft_asistente"
DATA_FILE = DATA_DIR / "conversations.json"


def path_for(user: str) -> Path:
    """Cada usuario tiene su propio historial."""
    safe = "".join(c for c in user.lower() if c.isalnum() or c in "-_.") or "anon"
    return DATA_DIR / f"conversations_{safe}.json"


def load_conversations(path: Path = DATA_FILE) -> list[Conversation]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [Conversation.from_dict(c) for c in raw]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


def save_conversations(convs: list[Conversation], path: Path = DATA_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([c.to_dict() for c in convs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
