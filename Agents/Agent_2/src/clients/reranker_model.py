
import threading


class RerankerModel:
    """
    Adaptador para utilizar un modelo de reranking dentro del Agente 2.

    Permite que el resto del sistema utilice el método predict()
    independientemente de la interfaz concreta del modelo de reranking.

    Protege la inferencia concurrente para evitar que varios hilos
    utilicen simultáneamente una misma instancia del modelo.
    """

    def __init__(self, model):
        """
        Args:
            model: modelo de reranking que implementa compute_score().
        """
        self.model = model
        self._inference_lock = threading.Lock()

    def predict(self, pairs):
        """
        Calcula las puntuaciones de relevancia para los pares
        consulta-documento.

        Serializa las llamadas a compute_score() sobre esta instancia
        para evitar problemas de concurrencia con el tokenizer.

        Args:
            pairs: lista de pares [query, texto].

        Returns:
            Lista de puntuaciones generadas por el modelo.
        """

        if not pairs:
            return []

        with self._inference_lock:
            return self.model.compute_score(
                pairs,
                normalize=True
            )
