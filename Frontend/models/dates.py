from __future__ import annotations
from datetime import datetime


def parse(iso: str) -> datetime | None:
    """Fecha ISO 8601 -> datetime local sin zona. Admite el sufijo Z (UTC) del Backend."""
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d
