"""Adaptador local del modelo BGE-M3 (A2-01).

Importar este módulo no descarga ni instancia BGE-M3. La dependencia
FlagEmbedding se importa únicamente al llamar a load_bge_m3_client(),
de modo que las pruebas y el resto del servicio funcionan sin el modelo.
"""

from __future__ import annotations

from ..core.config import EMBEDDINGS_MODEL


QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "


def _with_prefix(text, prefix):
    """Antepone el prefijo sin duplicarlo si ya está presente."""
    if text.startswith(prefix):
        return text
    return f"{prefix}{text}"


class BgeM3Client:
    def __init__(self, encoder, use_prefix=True):
        self.encoder = encoder
        self.use_prefix = use_prefix

    def encode_query(self, text):
        """Antepone 'query: ' si use_prefix está activo (ALB-7)."""
        if not isinstance(text, str):
            raise TypeError("text debe ser texto.")

        if self.use_prefix:
            query = _with_prefix(text, QUERY_PREFIX)
        else:
            query = text
        return self._encode([query])[0]

    def encode(self, text, use_prefix=None):
        """Método unificado de codificación para compatibilidad directa."""
        if isinstance(text, str):
            if use_prefix is not None:
                old = self.use_prefix
                self.use_prefix = use_prefix
                try:
                    return self.encode_query(text)
                finally:
                    self.use_prefix = old
            return self.encode_query(text)
        elif isinstance(text, (list, tuple)):
            if use_prefix is not None:
                old = self.use_prefix
                self.use_prefix = use_prefix
                try:
                    return self.encode_passages(text)
                finally:
                    self.use_prefix = old
            return self.encode_passages(text)
        raise TypeError("text debe ser texto o una secuencia de textos.")

    def encode_passages(self, texts):
        passages = list(texts)

        if any(not isinstance(text, str) for text in passages):
            raise TypeError("Cada passage debe ser texto.")

        if self.use_prefix:
            passages = [
                _with_prefix(text, PASSAGE_PREFIX)
                for text in passages
            ]

        return self._encode(passages)

    def _encode(self, texts):
        output = self.encoder.encode(
            texts,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )

        if not isinstance(output, dict) or "dense_vecs" not in output:
            raise ValueError(
                "El codificador debe devolver la clave 'dense_vecs'."
            )

        vectors = output["dense_vecs"]

        if hasattr(vectors, "tolist"):
            vectors = vectors.tolist()

        if not isinstance(vectors, (list, tuple)):
            raise ValueError(
                "'dense_vecs' debe contener una lista de vectores."
            )

        if len(vectors) != len(texts):
            raise ValueError(
                "El codificador devolvió una cantidad inesperada de vectores."
            )

        return vectors


def load_bge_m3_client(
    model_name=None,
    *,
    device=None,
    use_prefix=None,
    use_fp16=True,
):
    """Carga BGE-M3 en local y devuelve un BgeM3Client."""
    if model_name is None:
        model_name = EMBEDDINGS_MODEL

    try:
        from FlagEmbedding import BGEM3FlagModel
    except ImportError as error:
        raise RuntimeError(
            "FlagEmbedding no está instalado. Instala las dependencias de "
            "Agents/Agent_2/requirements.txt para cargar BGE-M3 en local."
        ) from error

    model_kwargs = {"use_fp16": use_fp16}
    if device is not None:
        model_kwargs["device"] = device

    encoder = BGEM3FlagModel(model_name, **model_kwargs)
    return BgeM3Client(encoder, use_prefix=use_prefix if use_prefix is not None else True)


__all__ = ["BgeM3Client", "load_bge_m3_client", "QUERY_PREFIX", "PASSAGE_PREFIX"]
