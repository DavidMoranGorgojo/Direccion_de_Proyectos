# Backend · API (FastAPI)

## Login, historial de chats y registro de consultas (Álvaro)

**CTR-005** (login), **CTR-006** (historial de chats) y **CTR-003** (registro de consultas), con usuarios de prueba y tests.

### Arrancar

Desde la raíz del repo:

```bash
pip install -r Backend/requirements.txt
export DATABASE_URL=postgresql+psycopg://arsoft:arsoft@localhost:5432/arsoft
export JWT_SECRET=<cadena larga y aleatoria>
python Backend/scripts/crear_usuarios_prueba.py   # crea tablas + usuarios de prueba (idempotente)
cd Backend/api && uvicorn app.main:app --reload    # docs en http://localhost:8000/docs
```

Para probarlo desde el Frontend: `ARSOFT_API_URL=http://localhost:8000`.

Tests (SQLite en memoria, no necesitan Postgres): `pytest -q Test/test_Backend`

### Usuarios de prueba

| Usuario  | Contraseña | Rol     | Nota                           |
|----------|------------|---------|--------------------------------|
| admin    | admin123   | admin   | puede ver todas las consultas  |
| usuario1 | usuario123 | usuario |                                |
| usuario2 | usuario123 | usuario | para probar aislamiento        |
| inactivo | usuario123 | usuario | desactivado, el login falla    |

Solo para desarrollo y pruebas.

### Endpoints

Todos menos `/auth/login` requieren `Authorization: Bearer <token>`.

**CTR-005 · Login** (formato que consume `Frontend/services/auth.py`)
- `POST /auth/login` — `{"usuario", "contrasena"}`
  - 200 → `{"estado": "autenticado", "mensaje", "usuario": {"id", "nombre_usuario", "nombre", "rol"}, "token", "token_type", "expires_in"}`
  - 401 → `{"estado": "no_autenticado", "mensaje", "codigo_error": "credenciales_invalidas"}`
  - 422 → `codigo_error: "datos_incompletos"` · 429 → `codigo_error: "demasiados_intentos"` (5 fallos en 5 min por usuario e IP)
- `GET /auth/me` — usuario autenticado

El contrato aún no define el mecanismo de sesión; se devuelve `token` (JWT), que el Frontend ya envía si viene.

**CTR-006 · Historial de chats** (cada usuario solo ve los suyos; los ajenos dan 404)
- `GET /chats?limit&offset` · `POST /chats` `{titulo?}` · `GET /chats/{id}` (con mensajes) · `PATCH /chats/{id}` `{titulo}` · `DELETE /chats/{id}`
- `POST /chats/{id}/mensajes` — `{rol: usuario|asistente, contenido, fuentes?}`. El primer mensaje del usuario pasa a ser el título.

**CTR-003 · Registro de consultas**
- `POST /consultas` — `{consulta, tipo_busqueda: vectorial|bm25|otro, chat_id?, num_resultados, resultados?, latencia_ms?, estado, error?}`
- `GET /consultas/mias` · `GET /consultas` (solo admin; filtros `usuario_id`, `tipo_busqueda`, `estado`, `desde`, `hasta`)
- `registrar_consulta(db, ...)` en `api/app/routers/consultas.py` para llamarla desde los endpoints de búsqueda.

### Pendiente

- **Esquema:** `db/schema_usuarios.sql` es la propuesta de tablas para el esquema unificado (Roberto y Daniel). Al cerrarlo, alinear `api/app/models.py`.
- **Búsqueda (Jaime):** llamar a `registrar_consulta` desde los endpoints vectorial y BM25.
- **Contratos CTR-003 y CTR-006:** los campos son una propuesta; revisar contra los definitivos.
