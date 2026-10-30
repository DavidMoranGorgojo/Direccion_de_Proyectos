"""CTR-005 · formato que espera Frontend/services/auth.py."""
from app.routers.auth import MAX_FALLOS


def _login(client, usuario, contrasena):
    return client.post("/auth/login", json={"usuario": usuario, "contrasena": contrasena})


def test_login_ok(client):
    r = _login(client, "usuario1", "usuario123")
    assert r.status_code == 200
    body = r.json()
    assert body["estado"] == "autenticado"
    assert body["mensaje"]
    assert body["usuario"]["nombre_usuario"] == "usuario1"
    assert isinstance(body["usuario"]["id"], str)
    assert body["token"]
    assert "password_hash" not in body["usuario"]


def test_login_no_distingue_mayusculas_en_usuario(client):
    assert _login(client, "Usuario1", "usuario123").status_code == 200


def test_login_password_incorrecta(client):
    r = _login(client, "usuario1", "mal")
    assert r.status_code == 401
    assert r.json() == {"estado": "no_autenticado", "mensaje": "Usuario o contraseña incorrectos",
                        "codigo_error": "credenciales_invalidas"}


def test_login_usuario_inexistente_mismo_error(client):
    r1 = _login(client, "nadie", "x")
    r2 = _login(client, "usuario1", "x")
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()


def test_login_usuario_inactivo(client):
    assert _login(client, "inactivo", "usuario123").status_code == 401


def test_login_datos_incompletos_422(client):
    r = client.post("/auth/login", json={"usuario": "usuario1"})
    assert r.status_code == 422
    assert r.json()["codigo_error"] == "datos_incompletos"


def test_login_demasiados_intentos_429(client):
    for _ in range(MAX_FALLOS):
        assert _login(client, "usuario1", "mal").status_code == 401
    r = _login(client, "usuario1", "usuario123")  # bloqueado aunque la contraseña sea buena
    assert r.status_code == 429
    assert r.json()["codigo_error"] == "demasiados_intentos"
    # otro usuario no queda bloqueado
    assert _login(client, "usuario2", "usuario123").status_code == 200


def test_me_con_token(client, h_user1):
    r = client.get("/auth/me", headers=h_user1)
    assert r.status_code == 200
    assert r.json()["nombre_usuario"] == "usuario1"


def test_me_sin_token(client):
    assert client.get("/auth/me").status_code == 401


def test_me_token_falso(client):
    r = client.get("/auth/me", headers={"Authorization": "Bearer no-es-un-token"})
    assert r.status_code == 401
