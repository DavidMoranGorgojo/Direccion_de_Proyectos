class BgeM3Client:
    def __init__(self, encoder, use_prefix=True):
        self.encoder = encoder
        self.use_prefix = use_prefix

    def encode_query(self, text):
        if not isinstance(text, str):
            raise TypeError("text debe ser texto.")

        query = f"query: {text}" if self.use_prefix else text
        return self._encode([query])[0]

    def encode_passages(self, texts):
        passages = list(texts)

        if any(not isinstance(text, str) for text in passages):
            raise TypeError("Cada passage debe ser texto.")

        if self.use_prefix:
            passages = [f"passage: {text}" for text in passages]

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

        if len(vectors) != len(texts):
            raise ValueError(
                "El codificador devolvió una cantidad inesperada de vectores."
            )

        return vectors