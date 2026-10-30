def test_crear_y_listar_chats(client, h_user1):
    r = client.post("/chats", json={"titulo": "Normativa de obras"}, headers=h_user1)
    assert r.status_code == 201
    chat_id = r.json()["id"]

    r = client.get("/chats", headers=h_user1)
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == [chat_id]


def test_mensajes_y_titulo_automatico(client, h_user1):
    chat_id = client.post("/chats", json={}, headers=h_user1).json()["id"]
    client.post(f"/chats/{chat_id}/mensajes", json={"rol": "usuario", "contenido": "¿Qué dice el PDF 3?"}, headers=h_user1)
    client.post(
        f"/chats/{chat_id}/mensajes",
        json={"rol": "asistente", "contenido": "Dice esto.", "fuentes": [{"doc": "pdf3", "fragmento": 12}]},
        headers=h_user1,
    )
    r = client.get(f"/chats/{chat_id}", headers=h_user1)
    assert r.status_code == 200
    body = r.json()
    assert body["titulo"] == "¿Qué dice el PDF 3?"
    assert [m["rol"] for m in body["mensajes"]] == ["usuario", "asistente"]
    assert body["mensajes"][1]["fuentes"] == [{"doc": "pdf3", "fragmento": 12}]


def test_rol_de_mensaje_invalido(client, h_user1):
    chat_id = client.post("/chats", json={}, headers=h_user1).json()["id"]
    r = client.post(f"/chats/{chat_id}/mensajes", json={"rol": "sistema", "contenido": "x"}, headers=h_user1)
    assert r.status_code == 422


def test_renombrar_y_borrar(client, h_user1):
    chat_id = client.post("/chats", json={}, headers=h_user1).json()["id"]
    r = client.patch(f"/chats/{chat_id}", json={"titulo": "Otro título"}, headers=h_user1)
    assert r.json()["titulo"] == "Otro título"
    assert client.delete(f"/chats/{chat_id}", headers=h_user1).status_code == 204
    assert client.get(f"/chats/{chat_id}", headers=h_user1).status_code == 404


def test_aislamiento_entre_usuarios(client, h_user1, h_user2):
    chat_id = client.post("/chats", json={"titulo": "privado"}, headers=h_user1).json()["id"]
    assert client.get("/chats", headers=h_user2).json() == []
    assert client.get(f"/chats/{chat_id}", headers=h_user2).status_code == 404
    assert client.patch(f"/chats/{chat_id}", json={"titulo": "x"}, headers=h_user2).status_code == 404
    assert client.delete(f"/chats/{chat_id}", headers=h_user2).status_code == 404
    r = client.post(f"/chats/{chat_id}/mensajes", json={"rol": "usuario", "contenido": "x"}, headers=h_user2)
    assert r.status_code == 404


def test_chats_requieren_login(client):
    assert client.get("/chats").status_code == 401
