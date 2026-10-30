from app.routers.consultas import registrar_consulta


def _consulta(**kw):
    base = {"consulta": "plazos de licencia", "tipo_busqueda": "vectorial", "num_resultados": 3,
            "resultados": [11, 12, 13], "latencia_ms": 42.5}
    base.update(kw)
    return base


def test_registrar_y_ver_mias(client, h_user1):
    r = client.post("/consultas", json=_consulta(), headers=h_user1)
    assert r.status_code == 201
    assert r.json()["estado"] == "ok"
    mias = client.get("/consultas/mias", headers=h_user1).json()
    assert len(mias) == 1 and mias[0]["consulta"] == "plazos de licencia"


def test_registrar_error(client, h_user1):
    r = client.post("/consultas", json=_consulta(tipo_busqueda="bm25", estado="error", error="timeout",
                                                 num_resultados=0, resultados=None), headers=h_user1)
    assert r.status_code == 201
    assert r.json()["error"] == "timeout"


def test_tipo_busqueda_invalido(client, h_user1):
    assert client.post("/consultas", json=_consulta(tipo_busqueda="hibrida"), headers=h_user1).status_code == 422


def test_no_puede_registrar_en_chat_ajeno(client, h_user1, h_user2):
    chat_id = client.post("/chats", json={}, headers=h_user1).json()["id"]
    assert client.post("/consultas", json=_consulta(chat_id=chat_id), headers=h_user2).status_code == 404
    assert client.post("/consultas", json=_consulta(chat_id=chat_id), headers=h_user1).status_code == 201


def test_cada_usuario_ve_solo_las_suyas(client, h_user1, h_user2):
    client.post("/consultas", json=_consulta(), headers=h_user1)
    assert client.get("/consultas/mias", headers=h_user2).json() == []


def test_listado_completo_solo_admin(client, h_user1, h_user2, h_admin):
    client.post("/consultas", json=_consulta(), headers=h_user1)
    client.post("/consultas", json=_consulta(tipo_busqueda="bm25"), headers=h_user2)
    assert client.get("/consultas", headers=h_user1).status_code == 403
    todas = client.get("/consultas", headers=h_admin).json()
    assert len(todas) == 2
    solo_bm25 = client.get("/consultas", params={"tipo_busqueda": "bm25"}, headers=h_admin).json()
    assert len(solo_bm25) == 1


def test_funcion_registrar_consulta_directa(client, h_admin):
    # Simula la llamada desde el endpoint de búsqueda de Jaime
    from app.db import get_db
    from app.main import app
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    reg = registrar_consulta(db, consulta="desde búsqueda", tipo_busqueda="vectorial", num_resultados=5)
    assert reg.id is not None
    todas = client.get("/consultas", headers=h_admin).json()
    assert any(c["consulta"] == "desde búsqueda" for c in todas)
