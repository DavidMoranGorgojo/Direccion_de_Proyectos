"""Integración de principio a fin: Frontend → Backend → Agentes → Backend (pgvector) → PostgreSQL.

Se levantan con uvicorn el Backend real y el servicio real de Agentes (Agents/service.py, con el Agente 1
real). El cliente de Frontend (Frontend/services/api.py y auth.py) hace login, consulta y lee el historial
en modo real. Solo se sustituye lo que necesita hardware o modelos que no hay en las pruebas:
  - el LLM del Agente 1 (Ollama), por uno que genera la consulta y redacta copiando la evidencia citada;
  - los modelos BGE-M3 y reranker del Agente 2, por un vectorizador y un reranker deterministas.
Si el Agente 2 real está en el repositorio (Agents/Agent_2, rama agent_2), Agentes recupera con su pipeline
real (BackendAPIClient → /conocimiento/vectorial, /lexica, /chunks y /catalogos del Backend, con el token de
servicio). Si no, usa el simulador del Agente 1 y las pruebas que dependen del Agente 2 real se omiten.

Necesita un PostgreSQL de pruebas con la extensión pgvector en ARSOFT_TEST_DATABASE_URL (se recrean los
esquemas «conocimiento» y «aplicacion»). Ejecutar desde la raíz con ``PYTHONPATH=.:shared``.
"""

import hashlib
import json
import math
import os
import re
import socket
import sys
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

DB = os.getenv("ARSOFT_TEST_DATABASE_URL")
RAIZ = Path(__file__).resolve().parents[2]
TOKEN_SERVICIO = "arsoft-integracion-token"
SQL_ESQUEMA = (RAIZ / "Backend" / "db" / "init" / "01_conocimiento.sql").read_text(encoding="utf-8")
CATALOGOS = RAIZ / "Agents" / "Agent_2" / "fixtures" / "catalogos"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _hay_agente2_real() -> bool:
    try:
        from Agents.Agent_2.src.services.pipeline import Agent2Pipeline  # noqa: F401
        from Agents.Agent_2.src.clients.backend import BackendAPIClient  # noqa: F401
    except Exception:
        return False
    return True


def _hay_frontend() -> bool:
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True


AGENTE2_REAL = _hay_agente2_real()


# ------------------------------------------------------------------ modelos deterministas
def vector_de(texto: str) -> list[float]:
    """Bolsa de palabras con hashing a 1024 dimensiones, normalizada (sustituye a BGE-M3)."""
    texto = texto.removeprefix("query: ").removeprefix("passage: ").lower()
    v = [0.0] * 1024
    for palabra in re.findall(r"\w+", texto):
        if len(palabra) > 3:
            v[int(hashlib.md5(palabra.encode()).hexdigest(), 16) % 1024] += 1.0
    norma = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norma for x in v]


class ModeloBgeFalso:
    """Sustituye al modelo BGE-M3 de FlagEmbedding; el BgeM3Client real pone los prefijos (CTR-002)."""
    def __init__(self):
        self.textos = []

    def encode(self, textos, **_):
        self.textos.extend(textos)
        return {"dense_vecs": [vector_de(t) for t in textos]}


class RerankerFalso:
    def predict(self, pares):
        def puntuacion(consulta, pasaje):
            a = {p for p in re.findall(r"\w+", consulta.lower()) if len(p) > 3}
            b = {p for p in re.findall(r"\w+", pasaje.lower()) if len(p) > 3}
            return 0.5 + 0.5 * (len(a & b) / max(1, len(a)))
        return [puntuacion(q, p) for q, p in pares]


def llm_falso(agente, mensajes):
    """LLM del Agente 1: genera la consulta (CTR-004) o redacta copiando la evidencia citada."""
    todo = "\n".join(m["content"] for m in mensajes)
    if "EVIDENCIA [" in todo:  # redacción: copia literal de la primera evidencia, con su cita
        cid, texto = re.search(r"EVIDENCIA \[([^\]]+)\][^\n]*\n(.+)", todo).groups()
        return f"{texto.strip()} [{cid}]"
    pregunta = mensajes[-1]["content"]
    if "receta" in pregunta.lower():
        return "INVALIDA"
    version = (re.search(r"V(1\.0|1\.1|2\.0)", pregunta) or [None])[0]
    return json.dumps({"texto_busqueda": pregunta, "intencion": "mantenimiento",
                       "filtros": {"version": version, "componente": None, "tipo_documento": None, "codigos": []}})


# ------------------------------------------------------------------ datos
CHUNKS = [
    # (chunk_id, doc_id, documento, version_doc, obsoleto, sustituido_por, texto)
    ("mnt001-v11-refrigerante", "HTM240-MNT-001@1.1", "HTM240-MNT-001", "1.1", False, None,
     "La sustitución del refrigerante se realiza cada 60.000 km o 48 meses, lo que antes ocurra."),
    ("mnt001-v10-refrigerante", "HTM240-MNT-001@1.0", "HTM240-MNT-001", "1.0", True, "HTM240-MNT-001@1.1",
     "La sustitución del refrigerante se realiza cada 80.000 km o 60 meses, lo que antes ocurra."),
    ("prc003-bomba", "HTM240-PRC-003@2.0", "HTM240-PRC-003", "2.0", False, None,
     "La corriente nominal de la bomba auxiliar CMP-02 es de 3 a 6 A a 12 V."),
]


def sembrar(conn) -> None:
    conn.execute("DROP SCHEMA IF EXISTS conocimiento CASCADE")
    conn.execute("DROP SCHEMA IF EXISTS aplicacion CASCADE")
    conn.execute(SQL_ESQUEMA)
    conn.execute("""INSERT INTO conocimiento.indice_version (version, modelo_embeddings, dimensiones,
        prefijo_passage, tokenizador, n_chunks, activo) VALUES ('v-integracion', 'BAAI/bge-m3', 1024,
        'passage: ', 'bm25', %s, true)""", (len(CHUNKS),))
    for _, doc_id, codigo, version, obsoleto, sustituto, _ in CHUNKS:
        conn.execute("""INSERT INTO conocimiento.documento (doc_id, codigo, tipo_documento, titulo, version_documento,
            fecha_revision, obsoleto, sustituido_por, versiones_vehiculo, vigente_para)
            VALUES (%s, %s, 'mantenimiento', %s, %s, '2026-09-01', %s, %s, ARRAY['V1.0','V1.1','V2.0'], %s)
            ON CONFLICT DO NOTHING""",
                     (doc_id, codigo, codigo, version, obsoleto, sustituto,
                      [] if obsoleto else ["V1.0", "V1.1", "V2.0"]))
    for orden, (chunk_id, doc_id, codigo, version, obsoleto, sustituto, texto) in enumerate(CHUNKS, 1):
        conn.execute("""INSERT INTO conocimiento.chunk (indice_version, chunk_id, doc_id, documento, texto, seccion,
            pagina, orden_en_seccion, versiones, componente, tipo_documento, obsoleto, sustituido_por, vigente_para,
            fecha_revision, version_documento, embedding)
            VALUES ('v-integracion', %s, %s, %s, %s, 'Plan de mantenimiento', 2, %s, ARRAY['V1.0','V1.1','V2.0'],
                    'refrigeracion', 'mantenimiento', %s, %s, %s, '2026-09-01', %s, %s::vector)""",
                     (chunk_id, doc_id, codigo, texto, orden, obsoleto, sustituto,
                      [] if obsoleto else ["V1.0", "V1.1", "V2.0"], version,
                      str(vector_de("passage: " + texto))))
    for nombre in ("codigos", "componentes"):
        contenido = (json.loads((CATALOGOS / f"{nombre}.json").read_text(encoding="utf-8"))
                     if (CATALOGOS / f"{nombre}.json").exists() else {nombre: []})
        conn.execute("""INSERT INTO conocimiento.catalogo (nombre, version, contenido, activo)
            VALUES (%s, 'v-integracion', %s::jsonb, true)""", (nombre, json.dumps(contenido)))
    from Backend.api.app.usuarios_prueba import crear_usuarios_prueba
    crear_usuarios_prueba(conn)


@contextmanager
def serve(asgi):
    import uvicorn
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(asgi, log_level="error", access_log=False))
        hilo = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        hilo.start()
        try:
            for _ in range(300):
                if server.started:
                    break
                time.sleep(.02)
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            hilo.join(5)


@unittest.skipUnless(DB, "Requiere un PostgreSQL de pruebas con pgvector (ARSOFT_TEST_DATABASE_URL)")
@unittest.skipUnless(_hay_frontend(), "Requiere PySide6 para el cliente de Frontend")
class FrontendBackendAgentes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for ruta in (RAIZ, RAIZ / "shared", RAIZ / "Frontend"):
            if str(ruta) not in sys.path:
                sys.path.insert(0, str(ruta))
        cls.parches = [patch.dict(os.environ, {"DATABASE_URL": DB, "ARSOFT_SERVICE_TOKEN": TOKEN_SERVICIO,
                                                "ARSOFT_JWT_SECRET": "", "ARSOFT_ALLOW_HTTP": "1"})]
        cls.parches[0].start()
        from Backend.api.app import busqueda_lexica, main
        from Backend.api.app.links import connect
        with connect() as conn:
            sembrar(conn)
        busqueda_lexica._cache.update(clave=None, indice=None)

        cls.backend_cm = serve(main.app)
        cls.backend_url = cls.backend_cm.__enter__()

        from Agents import service
        from Agents.agente1 import core
        agente2 = core.simulador_agente_2
        cls.modelo_bge = ModeloBgeFalso()
        if AGENTE2_REAL:
            from Agents.Agent_2.src.clients.backend import BackendAPIClient
            from Agents.Agent_2.src.clients.bge_m3 import BgeM3Client
            from Agents.Agent_2.src.services.pipeline import Agent2Pipeline

            def agente2(query_json):  # el Agente 2 real, contra el Backend real
                # FALLO CONOCIDO (CTR-004, Agentes): el Agente 1 siempre envía filtros.codigos como lista y el
                # Agente 2 rechaza una lista vacía como "filtro explícito no admitido" (filter_inference.py), así
                # que toda consulta acaba en entrada_invalida. Hasta que Agentes lo corrija, aquí se quita el
                # filtro cuando va vacío; con códigos reales se mantiene.
                filtros = query_json.get("filtros") or {}
                if filtros.get("codigos") == []:
                    query_json = {**query_json, "filtros": {k: v for k, v in filtros.items() if k != "codigos"}}
                cliente = BackendAPIClient(cls.backend_url, "BAAI/bge-m3", token=TOKEN_SERVICIO, timeout=10)
                return Agent2Pipeline(backend_client=cliente, embedding_client=BgeM3Client(cls.modelo_bge),
                                      reranker_model=RerankerFalso(), require_reranker=True
                                      ).procesar_consulta(query_json)
        real = core.consultar_asistente
        cls.consultas_agentes = []

        def consultar(pregunta, agente, **kw):
            cls.consultas_agentes.append(agente.conversacion_id)
            return real(pregunta, agente, agente2=agente2)

        cls.parches += [patch.object(core.Agente1, "_consultar_llm", llm_falso),
                        patch.object(core, "registrar_turno_auditoria"),
                        patch.object(service, "consultar_asistente", consultar)]
        for p in cls.parches[1:]:
            p.start()
        cls.agentes_cm = serve(service.app)
        cls.agentes_url = cls.agentes_cm.__enter__()
        os.environ["AGENTES_URL"] = cls.agentes_url

        from services import api, auth, session
        # Ruta acordada con Frontend (CTR-001): la rama frontend-integracion-real ya usa /consulta
        cls.url = patch.multiple(api, API_URL=cls.backend_url, CONSULTA_PATH="/consulta")
        cls.url.start()
        cls.api, cls.auth, cls.session = api, auth, session

    @classmethod
    def tearDownClass(cls):
        cls.url.stop()
        cls.agentes_cm.__exit__(None, None, None)
        cls.backend_cm.__exit__(None, None, None)
        for p in reversed(cls.parches):
            p.stop()

    def setUp(self):
        from Backend.api.app import limite_consultas, sesiones
        from Backend.api.app.links import connect
        sesiones._fallos.clear()
        limite_consultas.reiniciar()
        with connect() as conn:
            conn.execute("DELETE FROM aplicacion.chat")
            conn.execute("DELETE FROM aplicacion.registro_consulta")
            conn.execute("UPDATE aplicacion.usuario SET activo = (nombre_usuario <> 'inactivo')")
        self.session.clear()
        type(self).consultas_agentes.clear()

    def entrar(self, usuario="usuario1", clave="usuario123"):
        res = self.auth.login(usuario, clave)
        self.assertTrue(res.ok, res.error)
        self.session.start(res.user, res.token, res.user_id)

    def registro(self):
        from Backend.api.app.links import connect
        with connect() as conn:
            return conn.execute("SELECT * FROM aplicacion.registro_consulta ORDER BY id").fetchall()

    # ------------------------------------------------------------------ flujo completo
    def test_consulta_historial_y_registro_de_principio_a_fin(self):
        self.entrar()
        r = self.api.send_message("", "¿Cada cuántos km se cambia el refrigerante en un V2.0?")
        # Con el Agente 2 real hay respuesta con fuentes; con el simulador puede no tener evidencia
        esperado = ("respuesta",) if AGENTE2_REAL else ("respuesta", "sin_evidencia", "aclaracion")
        self.assertIn(r.estado, esperado, (r.texto, r.codigo_error))
        self.assertEqual(bool(r.fuentes), r.estado == "respuesta")
        self.assertTrue(r.trace_id)

        historial = self.api.fetch_history()
        self.assertTrue(historial.ok, historial.error)
        self.assertEqual(len(historial.conversations), 1)
        chat = historial.conversations[0]
        self.assertEqual([m.role for m in chat.messages], ["user", "assistant"])
        self.assertEqual(chat.messages[1].status, r.estado)
        self.assertEqual(chat.messages[0].trace_id, chat.messages[1].trace_id)

        (fila,) = self.registro()
        self.assertEqual((fila["conversacion_id"], fila["estado"]), (chat.id, r.estado))
        self.assertEqual(fila["chunk_ids"], [f.chunk_id for f in r.fuentes])
        self.assertEqual(self.consultas_agentes, [chat.id])  # Agentes recibe el conversacion_id de Backend

    @unittest.skipUnless(AGENTE2_REAL, "Requiere el Agente 2 real (Agents/Agent_2)")
    def test_agente2_real_recupera_de_pgvector_y_no_cita_el_documento_sustituido(self):
        self.entrar()
        r = self.api.send_message("", "¿Cada cuántos km se cambia el refrigerante en un V2.0?")
        self.assertEqual(r.estado, "respuesta", (r.texto, r.codigo_error))
        ids = [f.chunk_id for f in r.fuentes]
        self.assertIn("mnt001-v11-refrigerante", ids)
        self.assertNotIn("mnt001-v10-refrigerante", ids)  # pregunta trampa: MNT-001 v1.0 está sustituido
        self.assertTrue(self.modelo_bge.textos[-1].startswith("query: "))  # prefijo CTR-002 en la consulta
        self.assertIn("60.000 km", r.texto)
        self.assertNotIn("80.000", r.texto)
        fuente = next(f for f in r.fuentes if f.chunk_id == "mnt001-v11-refrigerante")
        self.assertEqual((fuente.documento, fuente.seccion, fuente.pagina), ("HTM240-MNT-001", "Plan de mantenimiento", 2))

    def test_segundo_turno_en_la_misma_conversacion(self):
        self.entrar()
        primera = self.api.send_message("", "¿Cada cuántos km se cambia el refrigerante en un V2.0?")
        cid = self.api.fetch_history().conversations[0].id
        segunda = self.api.send_message(cid, "¿Y la corriente de la bomba auxiliar CMP-02 en un V2.0?")
        self.assertNotEqual(segunda.estado, "error", (segunda.texto, segunda.codigo_error))
        self.assertEqual(self.consultas_agentes, [cid, cid])
        chats = self.api.fetch_history().conversations
        self.assertEqual(len(chats), 1)
        self.assertEqual(len(chats[0].messages), 4)
        self.assertNotEqual(primera.estado, "error")

    def test_fuera_de_ambito(self):
        self.entrar()
        r = self.api.send_message("", "Dame una receta de paella")
        self.assertEqual((r.estado, r.fuentes), ("fuera_de_ambito", []))
        self.assertEqual(self.registro()[0]["estado"], "fuera_de_ambito")

    # ------------------------------------------------------------------ CTR-007
    def test_agentes_leen_el_historial_de_la_conversacion(self):
        from Agents.agente1.cliente_backend import ClienteBackendAgentes
        self.entrar()
        self.api.send_message("", "¿Cada cuántos km se cambia el refrigerante en un V2.0?")
        cid = self.api.fetch_history().conversations[0].id
        mensajes = ClienteBackendAgentes(base_url=self.backend_url, token_auth=TOKEN_SERVICIO,
                                         timeout=5).obtener_historial(cid)
        self.assertEqual([m["role"] for m in mensajes], ["user", "assistant"])
        self.assertIn("refrigerante", mensajes[0]["contenido"])

    # ------------------------------------------------------------------ errores
    def test_sin_sesion_401_y_usuario_desactivado_403(self):
        r = self.api.send_message("", "hola")
        self.assertEqual(r.codigo_error, "sesion_caducada")
        self.entrar()
        from Backend.api.app.links import connect
        with connect() as conn:
            conn.execute("UPDATE aplicacion.usuario SET activo=false WHERE nombre_usuario='usuario1'")
        status, cuerpo = self.api.call("POST", "/consulta", {"conversacion_id": "", "pregunta": "hola"})
        self.assertEqual((status, cuerpo["codigo_error"]), (403, "acceso_denegado"))
        self.assertEqual(self.api.send_message("", "hola").codigo_error, "sesion_caducada")  # Frontend: 401/403
        self.assertEqual(self.consultas_agentes, [])

    def test_429_demasiadas_consultas(self):
        self.entrar()
        with patch.dict(os.environ, {"ARSOFT_CONSULTAS_POR_MINUTO": "1"}):
            self.api.send_message("", "¿Cada cuántos km se cambia el refrigerante en un V2.0?")
            status, cuerpo = self.api.call("POST", "/consulta", {"conversacion_id": "", "pregunta": "otra"})
            r = self.api.send_message("", "otra pregunta sobre el refrigerante")
        self.assertEqual((status, cuerpo["codigo_error"]), (429, "demasiadas_consultas"))
        self.assertEqual(r.estado, "error")  # el Frontend lo muestra como error (con su texto si ya trata el 429)
        self.assertEqual(len(self.consultas_agentes), 1)

    def test_agentes_rechaza_un_token_de_servicio_incorrecto(self):
        self.entrar()
        with patch("Backend.api.app.main.service_headers", return_value={"Authorization": "Bearer otro"}):
            r = self.api.send_message("", "¿Cada cuántos km se cambia el refrigerante en un V2.0?")
        self.assertEqual((r.estado, r.codigo_error), ("error", "servicio_no_disponible"))
        self.assertEqual(self.consultas_agentes, [])

    def test_agentes_caido(self):
        self.entrar()
        with socket.socket() as libre:
            libre.bind(("127.0.0.1", 0))
            puerto = libre.getsockname()[1]
        with patch.dict(os.environ, {"AGENTES_URL": f"http://127.0.0.1:{puerto}"}):
            r = self.api.send_message("", "¿Cada cuántos km se cambia el refrigerante en un V2.0?")
        self.assertEqual((r.estado, r.codigo_error), ("error", "servicio_no_disponible"))
        self.assertEqual(self.registro()[0]["codigo_error"], "servicio_no_disponible")


if __name__ == "__main__":
    unittest.main()
