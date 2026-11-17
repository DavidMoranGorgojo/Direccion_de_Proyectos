"""Orquestador principal del Agente 2 (recuperación híbrida y evidencias).

Implementa el pipeline completo de recuperación respetando los contratos
CTR-002 y CTR-004, integrando:
- Inferencia y combinación de filtros (A2-10).
- Búsqueda vectorial y léxica vía Backend (A2-01).
- Parseo de respuestas y validación (A2-02, A2-03).
- Fusión recíproca de rangos RRF (A2-04).
- Reranking con modelo cruzado y filtrado por umbral (A2-05).
- Cálculo de estados documentales, vigencia y vecinos (A2-06).
- Empaquetado de evidencias CTR-004 para Agente 1 (A2-07).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

import requests

from ..clients.backend import BackendAPIClient, split_ctr002_requests
from ..clients.bge_m3 import BgeM3Client, get_bge_m3_client
from ..core import config
from ..core.errors import BackendRequestError
from ..models.retrieval import RetrievalDecision
from ..services.candidate_adapter import to_fusion_candidates
from ..services.evidence_builder import build_evidence_response
from ..services.filter_inference import infer_filters, merge_filters
from ..services.filter_vocab import adapt_explicit_filters
from ..services.filters import filter_chunks
from ..services.fusion import rrf
from ..services.reranker import apply_threshold, rerank_results, rerank_with_threshold
from ..services.vector_parser import parse_vector_response
from ..services.vigencia import classify_state, resolve_retrieval

logger = logging.getLogger("Agent2Pipeline")


class Agent2Pipeline:
    """Clase orquestadora configurable con inyección de dependencias para tests."""

    def __init__(
        self,
        backend_client: Optional[BackendAPIClient] = None,
        embedding_client: Optional[Any] = None,
        reranker_model: Optional[Any] = None,
        threshold: Optional[float] = None,
        default_top_k: int = 30,
        require_reranker: bool = False,
    ):
        self._backend_client = backend_client
        self._embedding_client = embedding_client
        self.reranker_model = reranker_model
        self.threshold = threshold if threshold is not None else config.RERANK_THRESHOLD
        self.default_top_k = default_top_k
        self.require_reranker = require_reranker

    @property
    def backend_client(self) -> BackendAPIClient:
        if self._backend_client is None:
            self._backend_client = BackendAPIClient(
                base_url=config.BACKEND_API_BASE,
                model_embeddings=config.EMBEDDINGS_MODEL,
            )
        return self._backend_client

    @property
    def embedding_client(self) -> Any:
        if self._embedding_client is None:
            self._embedding_client = get_bge_m3_client()
        return self._embedding_client

    def procesar_consulta(self, query_json: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta el pipeline completo y devuelve el formato contractual CTR-004."""
        t_inicio = time.monotonic()
        metricas: Dict[str, Any] = {}

        # 1. Validación inicial de entrada (F07)
        if not isinstance(query_json, dict):
            return {
                "estado": "error",
                "resultados": [],
                "evidencias": [],
                "codigo_error": "entrada_invalida",
                "mensaje_error": "query_json debe ser un diccionario.",
            }

        # 2. Extracción y validación estricta de texto (F06, F07)
        # Campo contractual CTR-004 §3: 'texto_preprocesado', con fallback a alias existentes
        raw_texto = None
        for campo in ("texto_preprocesado", "texto_busqueda", "query_busqueda"):
            if campo in query_json:
                raw_texto = query_json[campo]
                break

        if raw_texto is None:
            return {
                "estado": "error",
                "resultados": [],
                "evidencias": [],
                "codigo_error": "entrada_invalida",
                "mensaje_error": "Falta el campo de texto de búsqueda obligatorio.",
            }

        if not isinstance(raw_texto, str):
            return {
                "estado": "error",
                "resultados": [],
                "evidencias": [],
                "codigo_error": "entrada_invalida",
                "mensaje_error": "El texto de búsqueda debe ser una cadena de texto.",
            }

        texto_busqueda = raw_texto.strip()
        if not texto_busqueda:
            return {
                "estado": "sin_evidencia",
                "resultados": [],
                "evidencias": [],
                "codigo_error": None,
                "mensaje_error": "Texto de búsqueda vacío.",
            }

        # Validación de filtros (F07)
        filtros_explicit = {}
        if "filtros" in query_json:
            if not isinstance(query_json["filtros"], dict):
                return {
                    "estado": "error",
                    "resultados": [],
                    "evidencias": [],
                    "codigo_error": "entrada_invalida",
                    "mensaje_error": "El campo 'filtros' debe ser un diccionario.",
                }
            filtros_explicit = query_json["filtros"]

        # Validación de opciones (F07)
        opciones = {}
        if "opciones" in query_json:
            if not isinstance(query_json["opciones"], dict):
                return {
                    "estado": "error",
                    "resultados": [],
                    "evidencias": [],
                    "codigo_error": "entrada_invalida",
                    "mensaje_error": "El campo 'opciones' debe ser un diccionario.",
                }
            opciones = query_json["opciones"]

        # Validación de top_k (F07)
        top_k = self.default_top_k
        if "top_k" in opciones:
            raw_top_k = opciones["top_k"]
            if type(raw_top_k) is not int or raw_top_k < 1:
                return {
                    "estado": "error",
                    "resultados": [],
                    "evidencias": [],
                    "codigo_error": "entrada_invalida",
                    "mensaje_error": "El campo 'top_k' debe ser un entero mayor o igual a 1.",
                }
            top_k = raw_top_k

        # Validación estricta de incluir_obsoletos (F07: no aceptar bool("false") ingenua)
        incluir_obsoletos_opt = None
        if "incluir_obsoletos" in opciones:
            raw_obsoletos = opciones["incluir_obsoletos"]
            if type(raw_obsoletos) is not bool:
                return {
                    "estado": "error",
                    "resultados": [],
                    "evidencias": [],
                    "codigo_error": "entrada_invalida",
                    "mensaje_error": "El campo 'incluir_obsoletos' debe ser un booleano estricto.",
                }
            incluir_obsoletos_opt = raw_obsoletos

        # 3, 4, 5. Inferencia y combinación de filtros
        try:
            inferred = infer_filters(texto_busqueda, backend_client=self._backend_client)
            merged_filters = merge_filters(filtros_explicit, inferred)
            if incluir_obsoletos_opt is not None:
                merged_filters["incluir_obsoletos"] = incluir_obsoletos_opt
        except (TypeError, ValueError) as err:
            return {
                "estado": "error",
                "resultados": [],
                "evidencias": [],
                "codigo_error": "filtro_invalido" if isinstance(err, ValueError) else "entrada_invalida",
                "mensaje_error": f"Filtros inválidos: {err}",
            }
        except (FileNotFoundError, BackendRequestError) as err:
            logger.error("Catálogos de Backend no disponibles para inferir filtros: %s", err)
            code = getattr(err, "codigo_error", "indice_no_disponible")
            return {
                "estado": "error", "resultados": [], "evidencias": [],
                "codigo_error": code,
                "mensaje_error": "Los catálogos del índice no están disponibles.",
            }

        # 6. Preparar peticiones para CTR-002
        sub_requests = split_ctr002_requests(merged_filters)

        # 7 & 8. Búsqueda vectorial y léxica
        vector_candidates_all: List[Dict[str, Any]] = []
        bm25_candidates_all: List[Dict[str, Any]] = []
        version_indice_global: Optional[str] = None

        try:
            # Generar vector con prefijo obligatorio según CTR-002 (F01, F12)
            t_vec0 = time.monotonic()
            if hasattr(self.embedding_client, "encode_query"):
                vector = self.embedding_client.encode_query(texto_busqueda)
            elif hasattr(self.embedding_client, "encode"):
                vector = self.embedding_client.encode(texto_busqueda, use_prefix=True)
            elif callable(self.embedding_client):
                vector = self.embedding_client(texto_busqueda)
            else:
                raise RuntimeError("El cliente de embeddings no es invocable ni contiene método encode.")

            # F14: Validación de dimensión de vector
            if len(vector) != config.EMBEDDING_DIMENSION:
                return {
                    "estado": "error",
                    "resultados": [],
                    "evidencias": [],
                    "codigo_error": "modelo_incompatible",
                    "mensaje_error": f"Dimensión del vector ({len(vector)}) no coincide con la esperada ({config.EMBEDDING_DIMENSION}).",
                }

            metricas["tiempo_embedding_ms"] = int((time.monotonic() - t_vec0) * 1000)

            t_search0 = time.monotonic()
            for req_filtros in sub_requests:
                # Búsqueda vectorial
                raw_vec = self.backend_client.search_vector(
                    vector=vector,
                    filtros=req_filtros,
                    k=top_k,
                )
                parsed_vec = parse_vector_response(raw_vec)

                # F14: Validación estricta del modelo de embeddings anunciado por el índice vectorial
                indice_modelo_vec = getattr(parsed_vec.indice, "modelo_embeddings", None)
                version_vec = getattr(parsed_vec.indice, "version", None)
                esperado = getattr(self.backend_client, "model_embeddings", config.EMBEDDINGS_MODEL)
                if indice_modelo_vec != esperado:
                    return {
                        "estado": "error",
                        "resultados": [],
                        "evidencias": [],
                        "codigo_error": "modelo_incompatible",
                        "mensaje_error": f"El índice vectorial utiliza el modelo {indice_modelo_vec!r}, incompatible con el configurado {esperado!r}.",
                    }

                if version_indice_global is not None and version_vec != version_indice_global:
                    return {"estado": "error", "resultados": [], "evidencias": [],
                            "codigo_error": "indice_no_disponible",
                            "mensaje_error": "El índice vectorial cambió de versión entre subconsultas."}
                version_indice_global = version_vec
                vector_candidates_all.extend(to_fusion_candidates(parsed_vec.resultados))

                # Búsqueda léxica (BM25 recibe el texto limpio original sin prefijo query:)
                parsed_lex = self.backend_client.search_lexical_candidates(
                    text=texto_busqueda,
                    filtros=req_filtros,
                    k=top_k,
                )

                # F14: Validación del modelo e índice léxico y coherencia de versiones entre índices
                indice_modelo_lex = getattr(parsed_lex.indice, "modelo_embeddings", None)
                version_lex = getattr(parsed_lex.indice, "version", None)

                if indice_modelo_lex != esperado:
                    return {
                        "estado": "error",
                        "resultados": [],
                        "evidencias": [],
                        "codigo_error": "modelo_incompatible",
                        "mensaje_error": f"El índice léxico utiliza el modelo {indice_modelo_lex!r}, incompatible con el configurado {esperado!r}.",
                    }

                if version_vec and version_lex and version_vec != version_lex:
                    return {
                        "estado": "error",
                        "resultados": [],
                        "evidencias": [],
                        "codigo_error": "indice_no_disponible",
                        "mensaje_error": f"Incompatibilidad de versiones de índice entre búsqueda vectorial ({version_vec!r}) y léxica ({version_lex!r}).",
                    }

                bm25_candidates_all.extend([c.to_rrf_dict() for c in parsed_lex.resultados])

            metricas["tiempo_backend_ms"] = int((time.monotonic() - t_search0) * 1000)

        except requests.Timeout as err:
            logger.warning("Timeout al comunicar con Backend: %s", err)
            return {
                "estado": "error",
                "resultados": [],
                "evidencias": [],
                "codigo_error": "tiempo_agotado",
                "mensaje_error": "Tiempo agotado en Backend.",
            }
        except (requests.RequestException, BackendRequestError) as err:
            logger.warning("Error al comunicar con Backend: %s", err)
            code = getattr(err, "codigo_error", "servicio_no_disponible")
            return {
                "estado": "error",
                "resultados": [],
                "evidencias": [],
                "codigo_error": code,
                "mensaje_error": str(err),
            }
        except Exception as err:
            logger.error("Error inesperado en recuperación: %s", err)
            return {
                "estado": "error",
                "resultados": [],
                "evidencias": [],
                "codigo_error": "servicio_no_disponible",
                "mensaje_error": str(err),
            }

        # 9 & 10. Fusión RRF
        try:
            fused = rrf(vector_candidates_all, bm25_candidates_all, k=config.RRF_K)
        except Exception as err:
            logger.error("Error en fusión RRF: %s", err)
            return {
                "estado": "error",
                "resultados": [],
                "evidencias": [],
                "codigo_error": "servicio_no_disponible",
                "mensaje_error": f"Fallo en fusión RRF: {err}",
            }

        # CTR-002 §4: si los únicos resultados nulos se deben al filtro
        # documental, se permite UN reintento eliminando tipo_documento.
        # Versión y componente confirmados nunca se relajan.
        if not fused and merged_filters.get("tipo_documento"):
            filtros_ampliados = {k: v for k, v in merged_filters.items() if k != "tipo_documento"}
            try:
                req = split_ctr002_requests(filtros_ampliados)[0]
                retry_vec = parse_vector_response(self.backend_client.search_vector(
                    vector=vector, filtros=req, k=top_k,
                ))
                retry_lex = self.backend_client.search_lexical_candidates(
                    text=texto_busqueda, filtros=req, k=top_k,
                )
                retry_iv = retry_vec.indice
                retry_il = retry_lex.indice
                esperado = getattr(self.backend_client, "model_embeddings", config.EMBEDDINGS_MODEL)
                if (retry_iv.modelo_embeddings != esperado or
                        retry_il.modelo_embeddings != esperado):
                    return {"estado": "error", "resultados": [], "evidencias": [],
                            "codigo_error": "modelo_incompatible",
                            "mensaje_error": "Modelo de índice incompatible durante reintento documental."}
                if (retry_iv.version != retry_il.version or
                        (version_indice_global is not None and retry_iv.version != version_indice_global)):
                    return {"estado": "error", "resultados": [], "evidencias": [],
                            "codigo_error": "indice_no_disponible",
                            "mensaje_error": "Índices incompatibles durante reintento documental."}
                fused = rrf(to_fusion_candidates(retry_vec.resultados),
                            [c.to_rrf_dict() for c in retry_lex.resultados], k=config.RRF_K)
                merged_filters = filtros_ampliados
                metricas["tipo_documento_ampliado"] = True
            except requests.Timeout:
                return {"estado": "error", "resultados": [], "evidencias": [],
                        "codigo_error": "tiempo_agotado",
                        "mensaje_error": "Tiempo agotado durante reintento documental."}
            except BackendRequestError as err:
                return {"estado": "error", "resultados": [], "evidencias": [],
                        "codigo_error": err.codigo_error,
                        "mensaje_error": str(err)}
            except Exception as err:
                logger.error("Error de recuperación en reintento documental: %s", err)
                return {"estado": "error", "resultados": [], "evidencias": [],
                        "codigo_error": "servicio_no_disponible",
                        "mensaje_error": "Error durante reintento documental."}

        if not fused:
            return {
                "estado": "sin_evidencia",
                "resultados": [],
                "evidencias": [],
                "mensaje_error": None,
            }

        # 11 & 12. Filtrado duro
        candidatos_filtrados = filter_chunks(fused, merged_filters)
        if not candidatos_filtrados:
            return {
                "estado": "sin_evidencia",
                "resultados": [],
                "evidencias": [],
                "mensaje_error": None,
            }

        # 13 & 14. Reranking y umbral (F02)
        modelo_reranker = self.reranker_model
        if modelo_reranker is None and self.require_reranker:
            try:
                from ..clients.reranker_loader import get_reranker
                modelo_reranker = get_reranker()
            except Exception as err:
                logger.error("Reranker obligatorio no disponible: %s", err)
                return {
                    "estado": "error",
                    "resultados": [],
                    "evidencias": [],
                    "codigo_error": "servicio_no_disponible",
                    "mensaje_error": f"Reranker no disponible: {err}",
                }

        if modelo_reranker is not None:
            metricas["modo_recuperacion"] = "reranker"
            try:
                candidatos_umbral, metricas_rerank = rerank_with_threshold(
                    query=texto_busqueda,
                    results=candidatos_filtrados,
                    model=modelo_reranker,
                    threshold=self.threshold,
                    return_metrics=True,
                )
                metricas.update(metricas_rerank)
            except Exception as err:
                logger.error("Fallo durante la inferencia del reranker: %s", err)
                return {
                    "estado": "error",
                    "resultados": [],
                    "evidencias": [],
                    "codigo_error": "servicio_no_disponible",
                    "mensaje_error": f"Fallo durante reranking: {err}",
                }
        else:
            metricas["modo_recuperacion"] = "rrf_sin_reranker"
            # Modo sin reranker autorizado solo mediante Agent2Pipeline(...,
            # require_reranker=False). El punto de entrada público sí lo exige.
            # Modo sin reranker (ej. pruebas directas RRF):
            # NO se asigna rrf_score al campo rerank_score (F02: no utilizar rrf_score como si fuera rerank_score).
            # Se asigna score_final trazable directamente desde RRF.
            for cand in candidatos_filtrados:
                cand["score_final"] = float(cand.get("rrf_score", 0.0))
            candidatos_umbral = candidatos_filtrados

        if not candidatos_umbral:
            return {
                "estado": "insuficiente",
                "resultados": [],
                "evidencias": [],
                "mensaje_error": None,
            }

        # 15, 16, 17. Estados, vigencia y vecinos
        try:
            fetch_fn = getattr(self.backend_client, "get_neighbors", None)
            resultado_vigencia = resolve_retrieval(
                candidatos_umbral,
                filters=merged_filters,
                fetch_neighbors=fetch_fn,
            )
        except BackendRequestError as err:
            return {
                "estado": "error",
                "resultados": [],
                "evidencias": [],
                "codigo_error": err.codigo_error,
                "mensaje_error": str(err),
            }
        except Exception as err:
            logger.error("Error resolviendo vigencia o vecinos: %s", err)
            return {
                "estado": "error",
                "resultados": [],
                "evidencias": [],
                "codigo_error": "servicio_no_disponible",
                "mensaje_error": str(err),
            }

        if resultado_vigencia.estado == "error":
            return {
                "estado": "error",
                "resultados": [],
                "evidencias": [],
                "codigo_error": resultado_vigencia.codigo_error or "servicio_no_disponible",
                "mensaje_error": resultado_vigencia.mensaje_error or "Fallo en resolución de evidencias.",
            }

        if resultado_vigencia.estado == "insuficiente":
            return {
                "estado": "insuficiente",
                "resultados": [],
                "evidencias": [],
                "mensaje_error": None,
            }

        # 18 & 19. Construcción contractual de evidencias (CTR-004 §5, F06, F09)
        candidatos_finales = []
        for candidate in resultado_vigencia.candidatos:
            # Un vecino no evaluado por el reranker no puede heredarse como
            # evidencia con la puntuación del padre ni superar artificialmente
            # el umbral del modelo cruzado.
            if candidate.get("es_vecino") and "rerank_score" not in candidate:
                continue
            cand = dict(candidate)
            score = cand.get("rerank_score", cand.get("score_final"))
            if score is None:
                continue
            cand["score_final"] = float(score)
            candidatos_finales.append(cand)
        try:
            evidencias_ctr004 = build_evidence_response(candidatos_finales)["resultados"]
        except Exception as err:
            logger.error("No se pueden construir evidencias CTR-004 válidas: %s", err)
            return {
                "estado": "error", "resultados": [], "evidencias": [],
                "codigo_error": "error_verificacion",
                "mensaje_error": "El Backend ha devuelto evidencias sin metadatos contractuales válidos.",
            }

        # Construcción normalizada para Agente 1 (manteniendo compatibilidad total)
        evidencias_normalizadas = []
        document_state_by_id = {
            cand["chunk_id"]: cand.get("estado_documento", "vigente")
            for cand in candidatos_finales
        }
        for ev in evidencias_ctr004:
            cid = ev["chunk_id"]
            meta = dict(ev["metadatos"])
            sc = ev["score_final"]
            estado_doc = document_state_by_id.get(cid, "vigente")
            evidencias_normalizadas.append({
                "chunk_id": cid,
                "texto": ev["texto"],
                "metadata": meta,
                "metadatos": meta,
                "score": sc,
                "score_final": sc,
                "rerank_score": sc,
                "estado_documento": estado_doc,
            })

        # Mapeo de estado final
        estado_out = resultado_vigencia.estado
        if not evidencias_ctr004 and estado_out in {"suficiente", "solo_obsoleto"}:
            estado_out = "sin_evidencia"

        metricas["tiempo_total_ms"] = int((time.monotonic() - t_inicio) * 1000)

        # Salida que cumple tanto CTR-004 (campo obligatorio 'resultados')
        # como la interfaz del Agente 1 ('evidencias', 'estado', 'campo_ambiguo', etc.)
        return {
            "estado": estado_out,
            "resultados": evidencias_ctr004,
            "evidencias": evidencias_normalizadas,
            "campo_ambiguo": resultado_vigencia.campo_ambiguo,
            "codigo_error": resultado_vigencia.codigo_error,
            "mensaje_error": None,
            "metricas": metricas,
        }


def recuperar_evidencias(query_json: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Punto de entrada público directo para invocar el pipeline del Agente 2."""
    # Las llamadas públicas requieren el reranker por defecto. Los tests de
    # RRF puro pueden optar explícitamente por require_reranker=False al crear
    # Agent2Pipeline, pero producción no debe degradarse sin autorización.
    kwargs.setdefault("require_reranker", True)
    pipeline = Agent2Pipeline(**kwargs)
    return pipeline.procesar_consulta(query_json)


__all__ = ["Agent2Pipeline", "recuperar_evidencias"]
