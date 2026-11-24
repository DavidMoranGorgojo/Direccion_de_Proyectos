from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Source:
    """Elemento de `fuentes` (CTR-001 0.6 y CTR-006): fragmento en el que se apoya la respuesta."""
    documento: str
    seccion: str = ""
    pagina: int = 0                       # 0 = no consta
    versiones: list[str] = field(default_factory=list)
    obsoleto: bool = False                # True = documento sustituido por otro
    chunk_id: str = ""                    # informativo: el Frontend no lo muestra

    @property
    def citable(self) -> bool:
        if not isinstance(self.documento, str) or not isinstance(self.seccion, str):
            return False
        documento = self.documento.strip()
        return (
            bool(documento)
            and documento.casefold() not in {"doc_desconocido", "documento sin nombre"}
            and bool(self.seccion.strip())
            and type(self.pagina) is int
            and self.pagina >= 1
        )

    def to_dict(self) -> dict:
        return {"chunk_id": self.chunk_id, "documento": self.documento, "seccion": self.seccion,
                "pagina": self.pagina, "versiones": list(self.versiones),
                "obsoleto": self.obsoleto}

    @classmethod
    def from_dict(cls, d: dict) -> "Source":
        # También lee el formato antiguo (document/section/page) de historiales guardados.
        if not isinstance(d, dict):
            return cls(documento="", seccion="")
        page = d.get("pagina", d.get("page"))
        return cls(
            documento=d.get("documento") or d.get("document") or "Documento sin nombre",
            seccion=d.get("seccion") or d.get("section") or "",
            pagina=page if isinstance(page, int) else 0,
            versiones=[str(v) for v in (d.get("versiones") or [])],
            obsoleto=bool(d.get("obsoleto", False)),
            chunk_id=str(d.get("chunk_id") or ""),
        )
