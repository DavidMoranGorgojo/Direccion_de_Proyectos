# Backend · API (FastAPI)

## Pasarela hacia Agentes (Álvaro)

La consulta de Frontend (**CTR-001**) llega a Backend, se reenvía a Agentes **sin tocarla** y queda registrada con el registro de consultas (**CTR-003**).

**`POST /consulta`** (requiere `Authorization: Bearer <token>`)
- Cuerpo (provisional, a falta del CTR-001 definitivo): `{"pregunta": "...", "chat_id"?: 12, ...}`. También se acepta `consulta`, `mensaje` o `texto` en lugar de `pregunta`. El resto de campos se acepta y se reenvía.
- Backend solo comprueba que haya pregunta y que el `chat_id`, si viene, sea del usuario (si no, 404 y no se reenvía).
- A Agentes le llegan **los mismos bytes** que mandó Frontend, en `POST {AGENTES_URL}{AGENTES_RUTA}`, con las cabeceras `X-Trace-Id` y `X-Usuario-Id`. El token del usuario no se reenvía.
- A Frontend le llega la respuesta de Agentes **tal cual**, con las cabeceras `X-Trace-Id` y `X-Agentes-Modo` (`real` | `simulado`).
- Cada consulta se registra con `tipo_busqueda: "agentes"`: latencia, nº de fuentes, ids de los fragmentos citados, y `estado: error` con el motivo y el trace_id si falla.
- Errores: `{"estado": "error", "mensaje", "codigo_error", "trace_id"}`
  - 422 `datos_incompletos` · 404 `chat_no_encontrado` · 502 `agentes_no_disponible` · 502 `agentes_respuesta_invalida` · 504 `agentes_tiempo_agotado`

**`GET /consulta/estado`** → `{"modo": "real" | "simulado"}`

**Configuración**

| Variable | Por defecto | |
|---|---|---|
| `AGENTES_URL` | (vacía) | URL base de Agentes, p. ej. `http://localhost:8100` |
| `AGENTES_RUTA` | `/consulta` | ruta del endpoint de Agentes |
| `AGENTES_MODO` | `real` si hay `AGENTES_URL`, si no `simulado` | |
| `AGENTES_TIMEOUT_S` | `60` | |

**Modo simulado** (mientras Agentes no esté listo). Forma provisional a falta del contrato **ARSOFT-DIS-002 / Plantilla A (Contratos de Interfaz)**; las fuentes siguen **ARSOFT-MEM-003 §6** (`documento`, `seccion`, `pagina` y `estado` obligatorios):
```json
{"estado": "respondida", "trace_id": "t-…", "simulada": true,
 "respuesta": "El refrigerante se sustituye cada 60.000 km o 48 meses…",
 "fuentes": [{"id_fragmento": "HTM240-MNT-001_p2_refrigerante", "documento": "HTM240-MNT-001",
              "version_documento": "1.1", "seccion": "Plan de mantenimiento", "pagina": 2,
              "estado": "vigente", "extracto": "…"}]}
```
- Fuera de ámbito (receta, fútbol…) → `rechazo`. Menos de 3 palabras → `aclaracion`.
- Pregunta que depende de la versión del vehículo (HTM-0142, bomba auxiliar CMP-02, PTC, sensores…) sin indicar V1.0/V1.1/V2.0 → `aclaracion` pidiendo la versión (ARSOFT-MEM-003 §4).
- Respuestas de ejemplo con datos reales del corpus: refrigerante (60.000 km, nunca el valor obsoleto), HTM-0142 y corriente de CMP-02. El resto → respuesta genérica.

Código: `api/app/agentes.py` (cliente y respuestas simuladas) y `api/app/routers/pasarela.py`. Tests: `Test/test_Backend/test_pasarela.py`.

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
- **Pasarela:** revisar los campos de `ConsultaFrontendIn` (`schemas.py`) y la respuesta simulada (`agentes.py`) contra CTR-001 en ARSOFT-DIS-002 / Plantilla A. Confirmar con Agentes la ruta (`AGENTES_RUTA`) y si quieren el `X-Trace-Id`.
- **Esquema:** se añade `agentes` a los valores de `tipo_busqueda` (también en el CHECK de `db/schema_usuarios.sql`). Tenerlo en cuenta al unificar el esquema.
- **Semana que viene:** paso a Agentes reales (`AGENTES_MODO=real`) y conexión con Frontend.
