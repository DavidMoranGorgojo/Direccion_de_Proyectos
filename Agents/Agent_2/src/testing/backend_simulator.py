"""Simulador del Backend para las pruebas de contrato de CTR-002 (CJ-01).

Permite probar el Agente 2 de extremo a extremo sin el Backend real ni
PostgreSQL. Reproduce la parte observable de CTR-002 ed. 1.1:

* ``POST /conocimiento/vectorial``
* ``POST /conocimiento/lexica``
* ``GET /conocimiento/chunks/{chunk_id}?vecinos=0|1``
* ``GET /conocimiento/info`` y ``GET /catalogos/{nombre}``

y los errores con cuerpo plano de §4: ``indice_no_disponible``,
``modelo_incompatible``, ``peticion_invalida``, ``filtro_invalido``,
``entrada_invalida`` y ``recurso_no_encontrado``.

Qué reproduce y qué no
----------------------
* Filtros duros (§5.3): solo ``version``, ``componente`` y ``tipo_documento``,
  con un único valor y validados contra el conjunto cerrado del índice. Los
  códigos de avería no son filtro (§5.1). Un filtro nulo o vacío no restringe.
* Vigencia por versión: un chunk aplica a ``V`` si ``V`` está en
  ``vigente_para`` o si no está obsoleto y ``V`` está en ``versiones``.
* Puntuaciones: la léxica es BM25 real sobre el texto de los chunks; la
  vectorial es la similitud coseno contra una proyección dispersa por hash
  (bolsa de palabras). Sin BGE-M3 no hay calidad semántica, pero el contrato,
  el orden descendente, el desempate por ``chunk_id`` y los rangos de
  ``score`` son los del Backend.
* El prefijo ``query:`` de §5.4 no viaja al Backend (va dentro del vector), así
  que se comprueba en :meth:`BackendSimulator.embed_query`.

Todo ocurre en memoria: no se crean índices locales ni se escribe en disco.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import unicodedata
from urllib.parse import unquote, urlsplit

import requests

from ..core.config import CATALOG_DIR

DIMENSIONES = 1024
K_MAXIMO = 200
K_POR_DEFECTO = 30
MODELO_EMBEDDINGS = "BAAI/bge-m3"
TOKENIZADOR = "bm25-simulado"
VERSION_INDICE = "v1.0-simulada"

PREFIJO_CONSULTA = "query: "
PREFIJO_PASAJE = "passage: "

CAMPOS_PETICION_VECTORIAL = frozenset(
    {"vector", "modelo_embeddings", "filtros", "k"}
)
CAMPOS_PETICION_LEXICA = frozenset({"texto", "filtros", "k"})
CAMPOS_FILTRO = ("version", "componente", "tipo_documento")

CAMPOS_METADATOS = (
    "chunk_id",
    "texto",
    "documento",
    "seccion",
    "pagina",
    "versiones",
    "componente",
    "tipo_documento",
    "obsoleto",
    "sustituido_por",
    "vigente_para",
    "fecha_revision",
    "orden_en_seccion",
    "version_documento",
    "afectado_por",
    "ids_referenciados",
)

CATALOGOS_VALIDOS = frozenset(
    {"codigos", "terminos", "vehiculos", "componentes"}
)

_TOKEN = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")

_PALABRAS_VACIAS = frozenset(
    {
        "a",
        "al",
        "como",
        "con",
        "cual",
        "de",
        "del",
        "el",
        "en",
        "es",
        "esta",
        "las",
        "lo",
        "los",
        "más",
        "no",
        "o",
        "para",
        "por",
        "que",
        "se",
        "sin",
        "su",
        "un",
        "una",
        "y",
    }
)


class ErrorContrato(Exception):
    """Error CTR-002 §4 con cuerpo plano ``{"codigo", "mensaje", ...}``."""

    def __init__(self, estado, codigo, mensaje, **extra):
        super().__init__(mensaje)
        self.estado = estado
        self.codigo = codigo
        self.mensaje = mensaje
        self.extra = extra

    def cuerpo(self):
        return {"codigo": self.codigo, "mensaje": self.mensaje, **self.extra}


def _peticion_invalida(errores):
    return ErrorContrato(
        400,
        "peticion_invalida",
        "La petición no cumple el contrato CTR-002.",
        errores=errores,
    )


def _normalizar(texto):
    sin_acentos = "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caracter) != "Mn"
    )
    return sin_acentos.casefold()


def tokenizar(texto):
    """Tokens en minúsculas, sin acentos y conservando códigos con guion."""

    return [
        token
        for token in _TOKEN.findall(_normalizar(texto))
        if token not in _PALABRAS_VACIAS
    ]


def _normalizar_l2(vector):
    norma = math.sqrt(sum(valor * valor for valor in vector))

    if norma == 0:
        return vector

    return [valor / norma for valor in vector]


def _vector_bolsa_palabras(texto, dimensiones):
    """Proyección dispersa por hash, determinista, de una bolsa de palabras."""

    vector = [0.0] * dimensiones

    for token in tokenizar(texto):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        valor = int.from_bytes(digest, "big")
        vector[valor % dimensiones] += 1.0 if (valor >> 63) & 1 else -1.0

    return _normalizar_l2(vector)


class BackendSimulator:
    """Backend CTR-002 en memoria sobre el dataset sintético."""

    def __init__(
        self,
        chunks,
        version=VERSION_INDICE,
        modelo_embeddings=MODELO_EMBEDDINGS,
        dimensiones=DIMENSIONES,
        k_maximo=K_MAXIMO,
        catalogo_dir=None,
    ):
        self.chunks = [copy.deepcopy(chunk) for chunk in chunks]
        self.version = version
        self.modelo_embeddings = modelo_embeddings
        self.dimensiones = dimensiones
        self.k_maximo = k_maximo
        self.catalogo_dir = catalogo_dir or CATALOG_DIR

        self.indice_activo = True
        self.peticiones = []

        self._errores_forzados = []
        self._vectores = {}
        self._tokens = {}
        self._frecuencia_documental = {}
        self._longitud_media = 1.0

        self._preparar_indice_lexico()

    # ------------------------------------------------------------------
    # Preparación
    # ------------------------------------------------------------------
    def _preparar_indice_lexico(self):
        for chunk in self.chunks:
            tokens = tokenizar(chunk["texto"])
            self._tokens[chunk["chunk_id"]] = tokens

            for token in set(tokens):
                self._frecuencia_documental[token] = (
                    self._frecuencia_documental.get(token, 0) + 1
                )

        total = sum(len(tokens) for tokens in self._tokens.values())
        self._longitud_media = total / len(self._tokens) if self._tokens else 1.0

    def _vector_de(self, chunk):
        chunk_id = chunk["chunk_id"]

        if chunk_id not in self._vectores:
            self._vectores[chunk_id] = _vector_bolsa_palabras(
                chunk["texto"],
                self.dimensiones,
            )

        return self._vectores[chunk_id]

    # ------------------------------------------------------------------
    # Vectorización de la consulta
    # ------------------------------------------------------------------
    def embed_query(self, texto):
        """Vectoriza una consulta exigiendo el prefijo ``query:`` (§5.4)."""

        if not isinstance(texto, str) or not texto.strip():
            raise ValueError("texto debe ser texto no vacío.")

        if not texto.startswith(PREFIJO_CONSULTA):
            raise ValueError(
                "La consulta debe empezar por «query: » (CTR-002 §5.4)."
            )

        return _vector_bolsa_palabras(
            texto[len(PREFIJO_CONSULTA):],
            self.dimensiones,
        )

    def embed_passage(self, texto):
        """Vectoriza un pasaje. El prefijo ``passage:`` de la ingesta se omite."""

        if not isinstance(texto, str):
            raise TypeError("texto debe ser texto.")

        return _vector_bolsa_palabras(texto, self.dimensiones)

    # ------------------------------------------------------------------
    # Control de fallos (para pruebas de resiliencia)
    # ------------------------------------------------------------------
    def forzar_error(self, estado, codigo, veces=1, **extra):
        """Hace que las siguientes ``veces`` peticiones fallen con ese error."""

        if type(veces) is not int or veces < 1:
            raise ValueError("veces debe ser un entero positivo.")

        for _ in range(veces):
            self._errores_forzados.append(
                ErrorContrato(
                    estado,
                    codigo,
                    "Error forzado por la prueba.",
                    **extra,
                )
            )

        return self

    def desactivar_indice(self):
        self.indice_activo = False
        return self

    def activar_indice(self):
        self.indice_activo = True
        return self

    # ------------------------------------------------------------------
    # Enrutado
    # ------------------------------------------------------------------
    def atender(self, metodo, ruta, cuerpo=None, parametros=None):
        """Atiende una petición y devuelve ``(estado, cuerpo)``."""

        parametros = dict(parametros or {})
        self.peticiones.append(
            {
                "metodo": metodo,
                "ruta": ruta,
                "cuerpo": copy.deepcopy(cuerpo),
                "parametros": parametros,
            }
        )

        try:
            if self._errores_forzados:
                raise self._errores_forzados.pop(0)

            return 200, self._atender(metodo, ruta, cuerpo, parametros)
        except ErrorContrato as error:
            return error.estado, error.cuerpo()

    def _atender(self, metodo, ruta, cuerpo, parametros):
        rutas = {
            "/conocimiento/vectorial": ("POST", self.post_vectorial),
            "/conocimiento/lexica": ("POST", self.post_lexica),
            "/conocimiento/info": ("GET", lambda _: self.get_info()),
        }

        if ruta in rutas:
            metodo_esperado, manejador = rutas[ruta]

            if metodo != metodo_esperado:
                raise ErrorContrato(
                    405,
                    "metodo_no_permitido",
                    "El método HTTP no está permitido.",
                )

            return manejador(cuerpo)

        if ruta.startswith("/conocimiento/chunks/"):
            if metodo != "GET":
                raise ErrorContrato(
                    405,
                    "metodo_no_permitido",
                    "El método HTTP no está permitido.",
                )

            return self.get_chunk(
                ruta[len("/conocimiento/chunks/"):],
                parametros.get("vecinos", 0),
            )

        if ruta.startswith("/catalogos/"):
            if metodo != "GET":
                raise ErrorContrato(
                    405,
                    "metodo_no_permitido",
                    "El método HTTP no está permitido.",
                )

            return self.get_catalogo(ruta[len("/catalogos/"):])

        raise ErrorContrato(
            404,
            "recurso_no_encontrado",
            "El recurso solicitado no existe.",
        )

    # ------------------------------------------------------------------
    # GET /conocimiento/info y /catalogos/{nombre}
    # ------------------------------------------------------------------
    def get_info(self):
        self._comprobar_indice()

        return {
            "version": self.version,
            "modelo_embeddings": self.modelo_embeddings,
            "tokenizador": TOKENIZADOR,
            "dimensiones": self.dimensiones,
            "n_chunks": len(self.chunks),
        }

    def get_catalogo(self, nombre):
        self._comprobar_indice()

        if nombre not in CATALOGOS_VALIDOS:
            raise ErrorContrato(
                404,
                "recurso_no_encontrado",
                f"No existe el catálogo {nombre}.",
            )

        ruta = self.catalogo_dir / f"{nombre}.json"

        if not ruta.is_file():
            raise ErrorContrato(
                404,
                "recurso_no_encontrado",
                f"No existe el catálogo {nombre}.",
            )

        return json.loads(ruta.read_text(encoding="utf-8-sig"))

    # ------------------------------------------------------------------
    # POST /conocimiento/vectorial
    # ------------------------------------------------------------------
    def post_vectorial(self, cuerpo):
        self._comprobar_indice()

        errores = []
        campos = self._campos_permitidos(
            cuerpo,
            CAMPOS_PETICION_VECTORIAL,
            errores,
        )

        vector = campos.get("vector")
        if not isinstance(vector, (list, tuple)):
            errores.append(
                {"campo": "vector", "motivo": "debe ser una lista de números"}
            )
        elif len(vector) != self.dimensiones:
            errores.append(
                {
                    "campo": "vector",
                    "motivo": f"debe contener {self.dimensiones} valores",
                }
            )
        elif not all(
            type(valor) in (int, float) and math.isfinite(valor)
            for valor in vector
        ):
            errores.append(
                {"campo": "vector", "motivo": "debe contener números finitos"}
            )

        modelo = campos.get("modelo_embeddings")
        if modelo is not None and not isinstance(modelo, str):
            errores.append(
                {
                    "campo": "modelo_embeddings",
                    "motivo": "debe ser texto o nulo",
                }
            )

        k = self._validar_k(campos, errores, obligatorio=True)
        filtros = self._validar_filtros(campos.get("filtros"), errores)

        if errores:
            raise _peticion_invalida(errores)

        if modelo is not None and modelo != self.modelo_embeddings:
            raise ErrorContrato(
                409,
                "modelo_incompatible",
                "El modelo o la dimensión del vector no coincide con el "
                "índice.",
                modelo_indice=self.modelo_embeddings,
                dimensiones_indice=self.dimensiones,
                modelo_recibido=modelo,
            )

        self._validar_valores_filtro(filtros)

        puntuados = [
            (chunk, self._coseno(vector, self._vector_de(chunk)))
            for chunk in self._filtrar(filtros)
        ]
        puntuados.sort(key=lambda par: (-par[1], par[0]["chunk_id"]))

        return {
            "indice": {
                "version": self.version,
                "modelo_embeddings": self.modelo_embeddings,
            },
            "resultados": [
                self._resultado(chunk, score)
                for chunk, score in puntuados[:k]
            ],
        }

    @staticmethod
    def _coseno(first, second):
        return float(sum(a * b for a, b in zip(first, second)))

    # ------------------------------------------------------------------
    # POST /conocimiento/lexica
    # ------------------------------------------------------------------
    def post_lexica(self, cuerpo):
        self._comprobar_indice()

        errores = []
        campos = self._campos_permitidos(cuerpo, CAMPOS_PETICION_LEXICA, errores)

        texto = campos.get("texto")
        if not isinstance(texto, str) or not texto.strip():
            errores.append(
                {"campo": "texto", "motivo": "debe ser texto no vacío"}
            )

        k = self._validar_k(campos, errores)
        filtros = self._validar_filtros(campos.get("filtros"), errores)

        if errores:
            # La pasarela del Backend convierte un esquema inválido en 422.
            raise ErrorContrato(
                422,
                "entrada_invalida",
                "Faltan datos o el formato es incorrecto.",
            )

        self._validar_valores_filtro(filtros)

        consulta = tokenizar(texto)
        puntuados = [
            (chunk, score)
            for chunk, score in (
                (chunk, self._bm25(consulta, chunk))
                for chunk in self._filtrar(filtros)
            )
            if score > 0
        ]
        puntuados.sort(key=lambda par: (-par[1], par[0]["chunk_id"]))

        return {
            "indice": {
                "version": self.version,
                "modelo_embeddings": self.modelo_embeddings,
            },
            "resultados": [
                self._resultado(chunk, score)
                for chunk, score in puntuados[:k]
            ],
        }

    def _bm25(self, consulta, chunk, k1=1.5, b=0.75):
        tokens = self._tokens[chunk["chunk_id"]]

        if not tokens or not consulta:
            return 0.0

        longitud = len(tokens)
        total = len(self.chunks)
        score = 0.0

        for termino in set(consulta):
            frecuencia = tokens.count(termino)

            if not frecuencia:
                continue

            documentos = self._frecuencia_documental.get(termino, 0)
            idf = math.log(1 + (total - documentos + 0.5) / (documentos + 0.5))
            score += idf * (
                frecuencia * (k1 + 1)
                / (
                    frecuencia
                    + k1
                    * (1 - b + b * longitud / self._longitud_media)
                )
            )

        return float(score)

    # ------------------------------------------------------------------
    # GET /conocimiento/chunks/{chunk_id}
    # ------------------------------------------------------------------
    def get_chunk(self, chunk_id, vecinos=0):
        self._comprobar_indice()

        if type(vecinos) is str:
            try:
                vecinos = int(vecinos)
            except ValueError:
                vecinos = -1

        if type(vecinos) is not int or vecinos not in (0, 1):
            raise ErrorContrato(
                422,
                "entrada_invalida",
                "El parámetro 'vecinos' debe ser 0 o 1.",
            )

        chunk = next(
            (
                candidato
                for candidato in self.chunks
                if candidato["chunk_id"] == chunk_id
            ),
            None,
        )

        if chunk is None:
            raise ErrorContrato(
                404,
                "recurso_no_encontrado",
                f"No existe el fragmento {chunk_id}.",
            )

        adyacentes = []

        if vecinos:
            orden = chunk["orden_en_seccion"]
            adyacentes = sorted(
                (
                    candidato
                    for candidato in self.chunks
                    if candidato["chunk_id"] != chunk_id
                    and candidato["documento"] == chunk["documento"]
                    and candidato["seccion"] == chunk["seccion"]
                    and abs(candidato["orden_en_seccion"] - orden) <= 1
                ),
                key=lambda candidato: (
                    candidato["orden_en_seccion"],
                    candidato["chunk_id"],
                ),
            )

        return {
            "indice": {"version": self.version},
            "chunk": self._metadatos(chunk),
            "vecinos": [self._metadatos(adyacente) for adyacente in adyacentes],
        }

    # ------------------------------------------------------------------
    # Validación CTR-002
    # ------------------------------------------------------------------
    def _comprobar_indice(self):
        if not self.indice_activo:
            raise ErrorContrato(
                503,
                "indice_no_disponible",
                "No hay una versión de índice activa.",
            )

    @staticmethod
    def _campos_permitidos(cuerpo, permitidos, errores):
        if not isinstance(cuerpo, dict):
            errores.append(
                {"campo": "cuerpo", "motivo": "debe ser un objeto"}
            )
            return {}

        for campo in sorted(set(cuerpo) - permitidos):
            errores.append(
                {"campo": campo, "motivo": "campo no permitido"}
            )

        return cuerpo

    def _validar_k(self, campos, errores, obligatorio=False):
        if "k" not in campos:
            if obligatorio:
                errores.append({"campo": "k", "motivo": "campo obligatorio"})
            return K_POR_DEFECTO

        k = campos.get("k")

        if type(k) is not int or not 1 <= k <= self.k_maximo:
            errores.append(
                {
                    "campo": "k",
                    "motivo": f"debe ser un entero entre 1 y {self.k_maximo}",
                }
            )
            return K_POR_DEFECTO

        return k

    def _validar_filtros(self, filtros, errores):
        if filtros is None:
            return {}

        if not isinstance(filtros, dict):
            errores.append(
                {"campo": "filtros", "motivo": "debe ser un objeto"}
            )
            return {}

        limpios = {}

        for campo in sorted(set(filtros) - set(CAMPOS_FILTRO)):
            errores.append({"campo": f"filtros.{campo}", "motivo": "campo no permitido"})

        for campo in CAMPOS_FILTRO:
            valor = filtros.get(campo)

            if valor is None:
                continue

            if not isinstance(valor, str):
                errores.append(
                    {
                        "campo": f"filtros.{campo}",
                        "motivo": "debe ser texto o nulo",
                    }
                )
                continue

            if valor.strip():
                limpios[campo] = valor

        return limpios

    def valores_validos(self):
        versiones = set()
        componentes = set()
        tipos = set()

        for chunk in self.chunks:
            versiones.update(chunk.get("versiones") or [])
            versiones.update(chunk.get("vigente_para") or [])
            componentes.add(chunk.get("componente"))
            tipos.add(chunk.get("tipo_documento"))

        return {
            "version": sorted(versiones),
            "componente": sorted(componentes),
            "tipo_documento": sorted(tipos),
        }

    def _validar_valores_filtro(self, filtros):
        if not filtros:
            return

        validos = self.valores_validos()

        for campo, valor in filtros.items():
            if valor not in validos[campo]:
                raise ErrorContrato(
                    400,
                    "filtro_invalido",
                    f"El valor «{valor}» no existe para el filtro {campo}.",
                    campo=campo,
                    valores_validos=validos[campo],
                )

    def _filtrar(self, filtros):
        return [
            chunk
            for chunk in self.chunks
            if self._aplica(chunk, filtros)
        ]

    @staticmethod
    def _aplica(chunk, filtros):
        version = filtros.get("version")

        if version is not None and not (
            version in (chunk.get("vigente_para") or [])
            or (
                not chunk.get("obsoleto")
                and version in (chunk.get("versiones") or [])
            )
        ):
            return False

        if filtros.get("componente") not in (
            None,
            chunk.get("componente"),
        ):
            return False

        if filtros.get("tipo_documento") not in (
            None,
            chunk.get("tipo_documento"),
        ):
            return False

        return True

    # ------------------------------------------------------------------
    # Formato de resultado
    # ------------------------------------------------------------------
    @staticmethod
    def _metadatos(chunk):
        return {campo: copy.deepcopy(chunk.get(campo)) for campo in CAMPOS_METADATOS}

    @classmethod
    def _resultado(cls, chunk, score):
        return {"score": score, **cls._metadatos(chunk)}


class SimulatedResponse:
    """Respuesta mínima compatible con ``requests.Response``."""

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return copy.deepcopy(self._payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code}",
                response=self,
            )

    @property
    def text(self):
        return json.dumps(self._payload, ensure_ascii=False)

    def __repr__(self):
        return f"SimulatedResponse(status_code={self.status_code})"


class SimulatedSession:
    """Sesión ``requests`` que atiende contra un :class:`BackendSimulator`."""

    def __init__(self, backend, timeout=False):
        self.backend = backend
        self.timeout = timeout
        self.calls = []

    def post(self, url, *, json=None, timeout=None, **kwargs):
        return self._atender("POST", url, cuerpo=json, parametros=None)

    def get(self, url, *, params=None, timeout=None, **kwargs):
        return self._atender("GET", url, cuerpo=None, parametros=params)

    def _atender(self, metodo, url, cuerpo=None, parametros=None):
        ruta = unquote(urlsplit(url).path)
        self.calls.append(
            {
                "metodo": metodo,
                "url": url,
                "ruta": ruta,
                "cuerpo": copy.deepcopy(cuerpo),
                "parametros": dict(parametros or {}),
            }
        )

        if self.timeout:
            raise requests.Timeout("Tiempo agotado simulado.")

        estado, payload = self.backend.atender(
            metodo,
            ruta,
            cuerpo=cuerpo,
            parametros=parametros,
        )
        return SimulatedResponse(estado, payload)


def build_app(backend):
    """Expone el simulador como API FastAPI real (opcional, para CJ-03)."""

    from fastapi import Body, FastAPI, Query
    from fastapi.responses import JSONResponse

    app = FastAPI(title="Backend simulado CTR-002", version="1.1")

    def responder(resultado):
        estado, cuerpo = resultado
        return JSONResponse(cuerpo, status_code=estado)

    @app.get("/conocimiento/info")
    def info():
        return responder(backend.atender("GET", "/conocimiento/info"))

    @app.post("/conocimiento/vectorial")
    def vectorial(cuerpo: dict = Body(...)):
        return responder(
            backend.atender("POST", "/conocimiento/vectorial", cuerpo=cuerpo)
        )

    @app.post("/conocimiento/lexica")
    def lexica(cuerpo: dict = Body(...)):
        return responder(
            backend.atender("POST", "/conocimiento/lexica", cuerpo=cuerpo)
        )

    @app.get("/conocimiento/chunks/{chunk_id}")
    def chunk(chunk_id: str, vecinos: int = Query(default=0, ge=0, le=1)):
        return responder(
            backend.atender(
                "GET",
                f"/conocimiento/chunks/{chunk_id}",
                parametros={"vecinos": vecinos},
            )
        )

    @app.get("/catalogos/{nombre}")
    def catalogo(nombre: str):
        return responder(
            backend.atender("GET", f"/catalogos/{nombre}")
        )

    return app


__all__ = [
    "BackendSimulator",
    "DIMENSIONES",
    "ErrorContrato",
    "K_MAXIMO",
    "K_POR_DEFECTO",
    "MODELO_EMBEDDINGS",
    "PREFIJO_CONSULTA",
    "SimulatedResponse",
    "SimulatedSession",
    "TOKENIZADOR",
    "VERSION_INDICE",
    "build_app",
    "tokenizar",
]
