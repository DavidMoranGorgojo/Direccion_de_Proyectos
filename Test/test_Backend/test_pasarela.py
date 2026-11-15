"""Pasarela hacia Agentes (CTR-001 → Agentes, registro CTR-003)."""
import json

import httpx
import pytest

from app import agentes, config


@pytest.fixture()
def simulado(monkeypatch):
    monkeypatch.setattr(config, "AGENTES_MODO", "simulado")


@pytest.fixture()
def agentes_real(monkeypatch):
    """Modo real con un Agentes falso (httpx.MockTransport). Devuelve lo que recibió Agentes."""
    recibido = {}
    respuesta = {"status": 200, "json": None, "texto": None, "excepcion": None}

    def handler(request: httpx.Request) -> httpx.Response:
        if respuesta["excepcion"]:
            raise respuesta["excepcion"]
        recibido["url"] = str(request.url)
        recibido["cuerpo"] = request.content
        recibido["cabeceras"] = dict(request.headers)
        if respuesta["texto"] is not None:
            return httpx.Response(respuesta["status"], text=respuesta["texto"])
        datos = respuesta["json"] or {
            "estado": "respuesta", "texto": "Par de apriete: 90 Nm.",
            "fuentes": [{"fragmento_id": "f-1", "documento": "manual.pdf", "pagina": 3},
                        {"fragmento_id": "f-2", "documento": "manual.pdf", "pagina": 4}],
        }
        return httpx.Response(respuesta["status"], json=datos)

    monkeypatch.setattr(config, "AGENTES_MODO", "real")
    monkeypatch.setattr(config, "AGENTES_URL", "http://agentes.test")
    monkeypatch.setattr(config, "AGENTES_RUTA", "/consulta")
    monkeypatch.setattr(agentes, "_transport", httpx.MockTransport(handler))
    return recibido, respuesta


def _mias(client, h):
    return client.get("/consultas/mias", headers=h).json()


# ------------------------------------------------------------------ autenticación y validación
def test_requiere_login(client, simulado):
    assert client.post("/consulta", json={"pregunta": "par de apriete culata"}).status_code == 401


def test_sin_pregunta_da_422_con_formato_de_error(client, h_user1, simulado):
    for cuerpo in ({}, {"pregunta": ""}, {"pregunta": "   "}):
        r = client.post("/consulta", json=cuerpo, headers=h_user1)
        assert r.status_code == 422
        assert r.json()["codigo_error"] == "datos_incompletos"
    assert _mias(client, h_user1) == []  # no se registra lo que no llega a Agentes


def test_chat_ajeno_da_404_y_no_se_reenvia(client, h_user1, h_user2, agentes_real):
    recibido, _ = agentes_real
    chat_id = client.post("/chats", json={}, headers=h_user1).json()["id"]
    r = client.post("/consulta", json={"pregunta": "par de apriete culata", "chat_id": chat_id}, headers=h_user2)
    assert r.status_code == 404
    assert recibido == {}


# ------------------------------------------------------------------ modo simulado
def test_simulado_respuesta_y_registrada(client, h_user1, simulado):
    r = client.post("/consulta", json={"pregunta": "Par de apriete de la culata del Golf V"}, headers=h_user1)
    assert r.status_code == 200
    d = r.json()
    assert d["estado"] == "respuesta" and d["simulada"] is True and d["texto"]
    assert d["fuentes"] and d["trace_id"] == r.headers["X-Trace-Id"]
    assert r.headers["X-Agentes-Modo"] == "simulado"

    reg = _mias(client, h_user1)
    assert len(reg) == 1
    assert reg[0]["tipo_busqueda"] == "agentes" and reg[0]["estado"] == "ok"
    assert reg[0]["num_resultados"] == len(d["fuentes"])
    assert reg[0]["resultados"] == [f["id_fragmento"] for f in d["fuentes"]]
    assert reg[0]["latencia_ms"] is not None


def test_simulado_aclaracion_y_sin_evidencia(client, h_user1, simulado):
    assert client.post("/consulta", json={"pregunta": "culata"}, headers=h_user1).json()["estado"] == "aclaracion"
    d = client.post("/consulta", json={"pregunta": "dame una receta de paella"}, headers=h_user1).json()
    assert d["estado"] == "sin_evidencia" and d["fuentes"] == []


def test_simulado_fuentes_con_campos_obligatorios(client, h_user1, simulado):
    # ARSOFT-MEM-003 §6: documento, seccion, pagina y estado en cada fuente
    d = client.post("/consulta", json={"pregunta": "¿Cada cuántos km se cambia el refrigerante?"},
                    headers=h_user1).json()
    assert d["estado"] == "respuesta"
    assert "60.000 km" in d["texto"] and "80.000" not in d["texto"]  # nunca el valor obsoleto
    for f in d["fuentes"]:
        assert {"documento", "seccion", "pagina", "estado", "id_fragmento"} <= f.keys()
        assert f["estado"] == "vigente"


def test_simulado_pide_version_si_la_respuesta_depende_de_ella(client, h_user1, simulado):
    # ARSOFT-MEM-003 §4
    for pregunta in ("¿Qué significa el código HTM-0142?", "¿Qué corriente es normal en la bomba auxiliar?"):
        d = client.post("/consulta", json={"pregunta": pregunta}, headers=h_user1).json()
        assert d["estado"] == "aclaracion" and "V1.0" in d["texto"]
    d = client.post("/consulta", json={"pregunta": "¿Qué significa HTM-0142 en un V2.0?"}, headers=h_user1).json()
    assert d["estado"] == "respuesta" and "CMP-18" in d["texto"]
    # La versión también puede venir en el campo version_vehiculo de la Plantilla A
    d = client.post("/consulta", json={"pregunta": "¿Qué significa el código HTM-0142?", "version_vehiculo": "V2.0",
                                       "conversacion_id": "c-0001"}, headers=h_user1).json()
    assert d["estado"] == "respuesta"


def test_acepta_nombres_alternativos_del_campo(client, h_user1, simulado):
    r = client.post("/consulta", json={"consulta": "Par de apriete de la culata"}, headers=h_user1)
    assert r.status_code == 200 and r.json()["estado"] == "respuesta"


def test_estado_de_la_pasarela(client, h_user1, simulado):
    assert client.get("/consulta/estado", headers=h_user1).json() == {"modo": "simulado"}


# ------------------------------------------------------------------ modo real
def test_real_reenvia_el_cuerpo_sin_tocarlo(client, h_user1, agentes_real):
    recibido, _ = agentes_real
    chat_id = client.post("/chats", json={}, headers=h_user1).json()["id"]
    # Campos extra y acentos: deben llegar a Agentes byte a byte
    cuerpo = json.dumps({"pregunta": "¿Par de apriete de la culata?", "chat_id": chat_id,
                         "vehiculo": {"modelo": "Golf V", "motor": "1.9 TDI"}, "extra": [1, 2]},
                        ensure_ascii=False).encode("utf-8")
    r = client.post("/consulta", content=cuerpo,
                    headers={**h_user1, "Content-Type": "application/json"})
    assert r.status_code == 200
    assert recibido["url"] == "http://agentes.test/consulta"
    assert recibido["cuerpo"] == cuerpo
    assert recibido["cabeceras"]["x-trace-id"] == r.headers["X-Trace-Id"]
    assert recibido["cabeceras"]["x-usuario-id"]
    assert "authorization" not in recibido["cabeceras"]  # el token no sale de Backend


def test_real_devuelve_la_respuesta_de_agentes_sin_tocarla(client, h_user1, agentes_real):
    _, respuesta = agentes_real
    respuesta["json"] = {"estado": "respuesta", "texto": "ok", "campo_nuevo": {"a": 1},
                         "fuentes": [{"id": 7}, {"fragmento_id": "x"}]}
    r = client.post("/consulta", json={"pregunta": "par de apriete culata"}, headers=h_user1)
    assert r.json() == respuesta["json"]
    reg = _mias(client, h_user1)[0]
    assert reg["num_resultados"] == 2 and reg["resultados"] == [7, "x"]


@pytest.mark.parametrize("caso, http, codigo", [
    ("timeout", 504, "agentes_tiempo_agotado"),
    ("conexion", 502, "agentes_no_disponible"),
    ("error_http", 502, "agentes_respuesta_invalida"),
    ("no_json", 502, "agentes_respuesta_invalida"),
])
def test_real_errores_se_devuelven_y_se_registran(client, h_user1, agentes_real, caso, http, codigo):
    _, respuesta = agentes_real
    if caso == "timeout":
        respuesta["excepcion"] = httpx.ReadTimeout("lento")
    elif caso == "conexion":
        respuesta["excepcion"] = httpx.ConnectError("rechazada")
    elif caso == "error_http":
        respuesta["status"] = 500
    else:
        respuesta["texto"] = "<html>no soy json</html>"

    r = client.post("/consulta", json={"pregunta": "par de apriete culata"}, headers=h_user1)
    assert r.status_code == http
    d = r.json()
    assert d["estado"] == "error" and d["codigo_error"] == codigo
    assert d["trace_id"] == r.headers["X-Trace-Id"]

    reg = _mias(client, h_user1)[0]
    assert reg["estado"] == "error" and reg["tipo_busqueda"] == "agentes"
    assert d["trace_id"] in reg["error"]


def test_real_sin_url_configurada(client, h_user1, monkeypatch):
    monkeypatch.setattr(config, "AGENTES_MODO", "real")
    monkeypatch.setattr(config, "AGENTES_URL", "")
    r = client.post("/consulta", json={"pregunta": "par de apriete culata"}, headers=h_user1)
    assert r.status_code == 502 and r.json()["codigo_error"] == "agentes_no_disponible"


def test_admin_ve_las_consultas_de_la_pasarela(client, h_user1, h_admin, simulado):
    client.post("/consulta", json={"pregunta": "Par de apriete de la culata"}, headers=h_user1)
    todas = client.get("/consultas", params={"tipo_busqueda": "agentes"}, headers=h_admin).json()
    assert len(todas) == 1
