"""Tokenizador y embeddings de BAAI/bge-m3 (paso 5.6 del diseño de ingesta)."""

from typing import List

from . import config


class Embebedor:
    """Carga el tokenizador al momento y el modelo solo cuando hacen falta vectores."""

    def __init__(self, modelo: str = config.MODELO_EMBEDDINGS, prefijo: str = config.PREFIJO_PASSAGE,
                 dispositivo: str = "cpu"):
        from transformers import AutoTokenizer
        self.nombre = modelo
        self.prefijo = prefijo
        self.dispositivo = dispositivo
        self.tokenizador = AutoTokenizer.from_pretrained(modelo)
        self._modelo = None

    def contar_tokens(self, texto: str) -> int:
        return len(self.tokenizador.encode(texto, add_special_tokens=False))

    @property
    def modelo(self):
        if self._modelo is None:
            from sentence_transformers import SentenceTransformer
            self._modelo = SentenceTransformer(self.nombre, device=self.dispositivo)
        return self._modelo

    def vectorizar(self, textos: List[str], intentos: int = 2) -> List[List[float]]:
        """Embeddings normalizados L2 del texto con el prefijo de indexación. Reintenta una vez si falla."""
        for intento in range(intentos):
            try:
                vectores = self.modelo.encode(
                    [self.prefijo + t for t in textos],
                    normalize_embeddings=True,
                    batch_size=8,
                    show_progress_bar=len(textos) > 20,
                )
                break
            except Exception:
                if intento == intentos - 1:
                    raise
        if vectores.shape[1] != config.DIMENSIONES:
            raise ValueError(f"El modelo devuelve {vectores.shape[1]} dimensiones; se esperaban {config.DIMENSIONES}.")
        return vectores.tolist()
