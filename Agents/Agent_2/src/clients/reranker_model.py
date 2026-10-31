class RerankerModel:
    """
    Adaptador para utilizar un modelo de reranking dentro del Agente 2.

    Permite que el resto del sistema utilice el método predict()
    independientemente de la interfaz concreta del modelo de reranking.
    """

    def __init__(self, model):
        """
        Args:
            model: modelo de reranking que implementa compute_score().
        """
        self.model = model

    def predict(self, pairs):
        """
        Calcula las puntuaciones de relevancia para los pares
        consulta-documento.

        Args:
            pairs: lista de pares [query, texto].

        Returns:
            Lista de puntuaciones generadas por el modelo.
        """

        if not pairs:
            return []

        return self.model.compute_score(pairs, normalize=True)