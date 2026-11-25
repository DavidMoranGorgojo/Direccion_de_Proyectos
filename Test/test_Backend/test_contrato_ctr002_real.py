"""Contrato CTR-002 (edición 1.1) contra el Backend real: API arrancada, PostgreSQL y el índice cargado.

A diferencia de test_contrato_agente2_lexica.py (motor BM25 con una conexión simulada), estas pruebas
hablan por HTTP con el Backend que levanta ``apptainer/start-all.sh`` y consultan el índice que dejó
la ingesta de los PDF de ThermoDrive. Solo usan la biblioteca estándar, así que se ejecutan con
cualquier Python 3 sin instalar nada:

    python3 -m unittest Test.test_Backend.test_contrato_ctr002_real -v

Configuración:
  ARSOFT_API_URL         URL del Backend (por defecto http://127.0.0.1:8000).
  ARSOFT_SERVICE_TOKEN   Token de servicio. Si falta, se lee de ARSOFT_LOCAL_ENV o de
                         ~/.config/arsoft/local.env, que genera start-all.sh.

Si el Backend no responde, o no hay token o índice activo, todas las pruebas se omiten.
Las pruebas de similitud semántica (§6 «Simetría») necesitan vectores de consulta reales de bge-m3,
guardados en Test/fixtures/ctr002_consultas_bge_m3.json (ver generar_consultas_ctr002.py); sin ese
archivo se omiten.
"""

import json
import math
import os
import unittest
import urllib.request
from pathlib import Path

API = os.getenv("ARSOFT_API_URL", "http://127.0.0.1:8000").rstrip("/")
DIMENSIONES = 1024
MODELO = "BAAI/bge-m3"
VERSIONES = {"V1.0", "V1.1", "V2.0"}
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ctr002_consultas_bge_m3.json"

# §3: metadatos obligatorios de cada chunk devuelto y su tipo.
CAMPOS = {
    "chunk_id": str, "score": (int, float), "texto": str, "documento": str, "seccion": str,
    "pagina": int, "versiones": list, "componente": str, "tipo_documento": str, "obsoleto": bool,
    "sustituido_por": (str, type(None)), "vigente_para": list, "fecha_revision": (str, type(None)),
    "orden_en_seccion": int, "version_documento": str, "afectado_por": list, "ids_referenciados": list,
}


def _token() -> str:
    token = os.getenv("ARSOFT_SERVICE_TOKEN", "").strip()
    if token:
        return token
    archivo = Path(os.getenv("ARSOFT_LOCAL_ENV") or Path.home() / ".config" / "arsoft" / "local.env")
    try:
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            clave, _, valor = linea.strip().partition("=")
            if clave == "ARSOFT_SERVICE_TOKEN":
                return valor.strip().strip("'\"")
    except OSError:
        pass
    return ""


TOKEN = _token()


class _SinExcepcionesHTTP(urllib.request.HTTPErrorProcessor):
    """Devuelve también las respuestas 4xx/5xx en lugar de lanzar HTTPError, para leerlas y cerrarlas
    con normalidad (en Python 3.14 un HTTPError sin cerrar deja ResourceWarning)."""

    def http_response(self, request, response):
        return response

    https_response = http_response


_OPENER = urllib.request.build_opener(_SinExcepcionesHTTP)


def llamar(metodo: str, ruta: str, cuerpo=None, token: str | None = TOKEN, timeout: float = 30):
    """(estado HTTP, JSON) de una petición al Backend real."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(API + ruta, data=datos, method=metodo)
    peticion.add_header("Content-Type", "application/json")
    if token:
        peticion.add_header("Authorization", f"Bearer {token}")
    with _OPENER.open(peticion, timeout=timeout) as r:
        estado, texto = r.status, r.read()
    try:
        return estado, json.loads(texto or b"null")
    except ValueError:
        return estado, texto.decode(errors="replace")


def vector_unitario(semilla: int = 1) -> list[float]:
    """Vector normalizado arbitrario y reproducible: sirve para probar formato, filtros y vigencia,
    que no dependen de la similitud. Las pruebas semánticas usan vectores reales de bge-m3."""
    valores = [math.sin(semilla * (i + 1) * 0.7) for i in range(DIMENSIONES)]
    norma = math.sqrt(sum(v * v for v in valores))
    return [v / norma for v in valores]


def _motivo_para_omitir() -> str | None:
    try:
        estado, _ = llamar("GET", "/health", token=None, timeout=5)
    except OSError as error:
        return f"Backend no disponible en {API} ({error.__class__.__name__}). Arráncalo con start-all.sh."
    if estado != 200:
        return f"/health devolvió {estado}"
    if not TOKEN:
        return "Falta ARSOFT_SERVICE_TOKEN (ni en el entorno ni en ~/.config/arsoft/local.env)"
    estado, cuerpo = llamar("GET", "/conocimiento/info")
    if estado != 200:
        return f"/conocimiento/info devolvió {estado} {cuerpo}: ¿hay índice activo? Ejecuta la ingesta."
    return None


MOTIVO = None


def setUpModule():
    global MOTIVO
    MOTIVO = _motivo_para_omitir()


class Base(unittest.TestCase):
    def setUp(self):
        if MOTIVO:
            self.skipTest(MOTIVO)

    # Ayudas
    def lexica(self, texto, filtros=None, k=30):
        cuerpo = {"texto": texto, "k": k}
        if filtros is not None:
            cuerpo["filtros"] = filtros
        return llamar("POST", "/conocimiento/lexica", cuerpo)

    def vectorial(self, vector=None, filtros=None, k=30, modelo=MODELO):
        cuerpo = {"vector": vector or vector_unitario(), "k": k}
        if modelo is not None:
            cuerpo["modelo_embeddings"] = modelo
        if filtros is not None:
            cuerpo["filtros"] = filtros
        return llamar("POST", "/conocimiento/vectorial", cuerpo)

    def comprobar_respuesta(self, estado, cuerpo):
        """§3: indice + resultados con todos los metadatos, texto sin prefijo y sin embedding."""
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(set(cuerpo), {"indice", "resultados"})
        self.assertEqual(cuerpo["indice"]["modelo_embeddings"], MODELO)
        self.assertTrue(cuerpo["indice"]["version"])
        puntuaciones = []
        for r in cuerpo["resultados"]:
            faltan = set(CAMPOS) - set(r)
            self.assertFalse(faltan, f"{r.get('chunk_id')}: faltan {faltan}")
            for campo, tipo in CAMPOS.items():
                self.assertIsInstance(r[campo], tipo, f"{r['chunk_id']}.{campo} = {r[campo]!r}")
            self.assertNotIn("embedding", r, "§3: el embedding no viaja en las respuestas")
            self.assertFalse(r["texto"].lower().startswith("passage:"), "§5.2: el texto va sin el prefijo")
            self.assertTrue(r["texto"].strip(), r["chunk_id"])
            self.assertTrue(r["documento"] and r["seccion"], f"§5.4: origen citable en {r['chunk_id']}")
            self.assertGreaterEqual(r["pagina"], 1, f"§5.4: página citable en {r['chunk_id']}")
            self.assertTrue(set(r["versiones"]) <= VERSIONES, r["versiones"])
            if r["obsoleto"]:
                self.assertTrue(r["sustituido_por"], f"§3: {r['chunk_id']} obsoleto sin sustituido_por")
            puntuaciones.append(r["score"])
        self.assertEqual(puntuaciones, sorted(puntuaciones, reverse=True), "§4: lista ordenada por puntuación")
        return cuerpo["resultados"]

    def aplica_a(self, r, version):
        """§5.4 / busqueda.py: vigente si la versión está en vigente_para, o no es obsoleto y está en versiones."""
        return version in r["vigente_para"] or (not r["obsoleto"] and version in r["versiones"])


class Seguridad(Base):
    def test_sin_token_o_con_token_incorrecto_401(self):
        rutas = [("GET", "/conocimiento/info", None),
                 ("POST", "/conocimiento/lexica", {"texto": "bomba", "k": 3}),
                 ("POST", "/conocimiento/vectorial", {"vector": vector_unitario(), "k": 3}),
                 ("GET", "/catalogos/codigos", None)]
        for metodo, ruta, cuerpo in rutas:
            for token in (None, "token-incorrecto"):
                estado, respuesta = llamar(metodo, ruta, cuerpo, token=token)
                self.assertEqual(estado, 401, f"{metodo} {ruta} token={token!r}: {respuesta}")
                self.assertEqual(respuesta.get("codigo"), "acceso_denegado", respuesta)


class FichaYCatalogos(Base):
    def test_ficha_del_indice(self):
        estado, info = llamar("GET", "/conocimiento/info")
        self.assertEqual(estado, 200, info)
        self.assertEqual(info["modelo_embeddings"], MODELO)
        self.assertEqual(info["dimensiones"], DIMENSIONES)
        self.assertGreater(info["n_chunks"], 0)
        self.assertTrue(info["version"] and info["tokenizador_lexico"], "§5.4: tokenizador publicado en la ficha")

    def test_catalogos_versionados_con_el_indice(self):
        _, info = llamar("GET", "/conocimiento/info")
        for nombre in ("codigos", "terminos", "vehiculos", "componentes"):
            estado, cat = llamar("GET", f"/catalogos/{nombre}")
            self.assertEqual(estado, 200, f"{nombre}: {cat}")
            self.assertEqual(cat["version"], info["version"], f"{nombre} no corresponde al índice activo")
            self.assertTrue(cat["contenido"], f"catálogo {nombre} vacío")

    def test_catalogo_inexistente(self):
        estado, _ = llamar("GET", "/catalogos/inventado")
        self.assertIn(estado, (404, 422))


class Lexica(Base):
    def test_codigo_exacto_HTM_0142_entre_los_5_primeros(self):
        """§6: la búsqueda léxica devuelve el chunk que contiene HTM-0142 entre los 5 primeros."""
        resultados = self.comprobar_respuesta(*self.lexica("HTM-0142", k=5))
        self.assertTrue(any("HTM-0142" in r["texto"] or "HTM-0142" in r["ids_referenciados"] for r in resultados),
                        [r["chunk_id"] for r in resultados])

    def test_codigo_en_minusculas_y_sin_acentos(self):
        """§5.4: el tokenizador conserva el código como un término y normaliza mayúsculas."""
        resultados = self.comprobar_respuesta(*self.lexica("htm-0142", k=5))
        self.assertTrue(any("HTM-0142" in r["texto"] for r in resultados))

    def test_sin_coincidencias_es_200_con_lista_vacia(self):
        """§4 y §6 «Pregunta sin respuesta»: HTTP 200 con lista vacía, no es un error."""
        estado, cuerpo = self.lexica("zzqxwv kkjjhh")
        self.assertEqual(self.comprobar_respuesta(estado, cuerpo), [])

    def test_k_limita_los_resultados(self):
        self.assertLessEqual(len(self.comprobar_respuesta(*self.lexica("bomba", k=2))), 2)

    def test_filtro_con_valor_inexistente_400_con_valores_validos(self):
        """§4: HTTP 400 con el campo y los valores válidos."""
        for campo in ("version", "componente", "tipo_documento"):
            estado, cuerpo = self.lexica("bomba", {campo: "valor-inventado"})
            self.assertEqual(estado, 400, cuerpo)
            self.assertEqual((cuerpo["codigo"], cuerpo["campo"]), ("filtro_invalido", campo), cuerpo)
            self.assertTrue(cuerpo["valores_validos"], cuerpo)

    def test_filtro_V11_solo_devuelve_lo_aplicable(self):
        """§6 «Filtro V1.1 y vigencia por versión»."""
        resultados = self.comprobar_respuesta(*self.lexica("bomba circuito refrigerante", {"version": "V1.1"}, k=50))
        self.assertTrue(resultados)
        for r in resultados:
            self.assertTrue(self.aplica_a(r, "V1.1"), f"{r['chunk_id']} no aplica a V1.1: {r['versiones']} "
                                                       f"obsoleto={r['obsoleto']} vigente_para={r['vigente_para']}")

    def test_filtros_de_componente_y_tipo_son_where_duro(self):
        """§5.3: los filtros descartan documentos completos antes de puntuar."""
        resultados = self.comprobar_respuesta(*self.lexica("bomba", {"tipo_documento": "procedimiento"}, k=50))
        self.assertTrue(resultados)
        self.assertEqual({r["tipo_documento"] for r in resultados}, {"procedimiento"})
        resultados = self.comprobar_respuesta(*self.lexica("bomba", {"componente": "bateria"}, k=50))
        self.assertEqual({r["componente"] for r in resultados}, {"bateria"})

    def test_pregunta_trampa_el_sustituido_llega_marcado(self):
        """§6 «Pregunta trampa»: el chunk de PRC-003 v1.0 llega como obsoleto, con sustituido_por.
        Con V1.1 no aparece; con V1.0 sí, porque sigue vigente para esa versión."""
        texto = "verificación de la bomba eléctrica auxiliar A circuito de batería"
        todos = self.comprobar_respuesta(*self.lexica(texto, k=50))
        viejos = [r for r in todos if r["documento"].startswith("HTM240-PRC-003") and r["obsoleto"]]
        self.assertTrue(viejos, "PRC-003 v1.0 no está en el índice: la ingesta debe indexar los sustituidos")
        self.assertTrue(all(r["sustituido_por"].startswith("HTM240-PRC-003") for r in viejos), viejos)
        con_v11 = self.comprobar_respuesta(*self.lexica(texto, {"version": "V1.1"}, k=50))
        self.assertFalse([r for r in con_v11 if r["obsoleto"]], "un sustituido no vigente para V1.1 no debe salir")
        con_v10 = self.comprobar_respuesta(*self.lexica(texto, {"version": "V1.0"}, k=50))
        self.assertTrue([r for r in con_v10 if r["obsoleto"] and "V1.0" in r["vigente_para"]],
                        "PRC-003 v1.0 sigue vigente para V1.0 y debe poder recuperarse")

    def test_texto_vacio_es_entrada_invalida(self):
        estado, _ = self.lexica("   ")
        self.assertIn(estado, (400, 422))


class Vectorial(Base):
    def test_respuesta_con_todos_los_metadatos(self):
        resultados = self.comprobar_respuesta(*self.vectorial(k=30))
        self.assertEqual(len(resultados), 30)
        for r in resultados:
            self.assertGreaterEqual(r["score"], -1.0001)
            self.assertLessEqual(r["score"], 1.0001, "§3: score es la similitud coseno cruda")

    def test_modelo_de_embeddings_distinto_409(self):
        """§4 y §6: HTTP 409 con código modelo_incompatible."""
        estado, cuerpo = self.vectorial(modelo="otro/modelo")
        self.assertEqual(estado, 409, cuerpo)
        self.assertEqual(cuerpo["codigo"], "modelo_incompatible")

    def test_vector_con_dimensiones_incorrectas_400(self):
        estado, cuerpo = self.vectorial(vector=vector_unitario()[:DIMENSIONES - 1])
        self.assertEqual(estado, 400, cuerpo)
        self.assertEqual(cuerpo["codigo"], "peticion_invalida", cuerpo)

    def test_k_fuera_de_rango_400(self):
        for k in (0, 10_000):
            estado, cuerpo = self.vectorial(k=k)
            self.assertEqual(estado, 400, f"k={k}: {cuerpo}")

    def test_filtro_con_valor_inexistente_400_con_valores_validos(self):
        estado, cuerpo = self.vectorial(filtros={"componente": "refrigeracion"})
        self.assertEqual(estado, 400, cuerpo)
        self.assertEqual(cuerpo["codigo"], "filtro_invalido", cuerpo)
        self.assertIn("valores_validos", cuerpo)

    def test_filtro_V11_y_tipo_documento(self):
        filtros = {"version": "V1.1", "tipo_documento": "procedimiento"}
        resultados = self.comprobar_respuesta(*self.vectorial(filtros=filtros, k=200))
        self.assertTrue(resultados)
        for r in resultados:
            self.assertEqual(r["tipo_documento"], "procedimiento")
            self.assertTrue(self.aplica_a(r, "V1.1"), r["chunk_id"])

    def test_sustituido_vigente_solo_para_su_version(self):
        """§5.4: PRC-003 v1.0 (sustituido, vigente_para V1.0) sale con V1.0 y no con V1.1 ni V2.0.
        Con k=200 se devuelven todos los procedimientos aplicables, sea cual sea el vector."""
        def obsoletos(version):
            filtros = {"version": version, "tipo_documento": "procedimiento"}
            return {r["documento"] for r in self.comprobar_respuesta(*self.vectorial(filtros=filtros, k=200))
                    if r["obsoleto"]}
        self.assertTrue(any(d.startswith("HTM240-PRC-003") for d in obsoletos("V1.0")),
                        "PRC-003 v1.0 debe estar indexado y vigente para V1.0")
        self.assertEqual(obsoletos("V1.1"), set())
        self.assertEqual(obsoletos("V2.0"), set())


class ChunkYVecinos(Base):
    def test_chunk_con_sus_vecinos_de_la_misma_seccion(self):
        resultados = self.comprobar_respuesta(*self.lexica("procedimiento pasos", {"tipo_documento": "procedimiento"},
                                                           k=50))
        candidato = next((r for r in resultados if r["orden_en_seccion"] >= 1), resultados[0])
        estado, cuerpo = llamar("GET", f"/conocimiento/chunks/{candidato['chunk_id']}?vecinos=1")
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(cuerpo["chunk"]["chunk_id"], candidato["chunk_id"])
        self.assertEqual(cuerpo["chunk"]["texto"], candidato["texto"], "§3: texto intacto")
        for vecino in cuerpo["vecinos"]:
            self.assertEqual((vecino["documento"], vecino["seccion"]), (candidato["documento"], candidato["seccion"]))
            self.assertLessEqual(abs(vecino["orden_en_seccion"] - candidato["orden_en_seccion"]), 1)

    def test_chunk_inexistente_404(self):
        estado, cuerpo = llamar("GET", "/conocimiento/chunks/no-existe")
        self.assertEqual(estado, 404, cuerpo)
        self.assertEqual(cuerpo.get("codigo"), "recurso_no_encontrado")


class Simetria(Base):
    """§6 «Simetría con frase literal» y «Simetría vectorial (prefijos correctos)»: una consulta con
    query: devuelve en primera posición el chunk indexado con passage: del que sale la frase."""

    def setUp(self):
        super().setUp()
        if not FIXTURE.is_file():
            self.skipTest(f"Faltan los vectores de consulta reales ({FIXTURE.name}): genera el archivo con "
                          "Test/fixtures/generar_consultas_ctr002.py")
        self.casos = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_frase_literal_devuelve_su_chunk_primero(self):
        for caso in self.casos:
            estado, cuerpo = self.vectorial(vector=caso["vector"], k=5)
            primero = self.comprobar_respuesta(estado, cuerpo)[0]
            self.assertEqual(primero["chunk_id"], caso["chunk_id"],
                             f"«{caso['consulta'][:60]}»: primero {primero['documento']} en vez de {caso['documento']}")
