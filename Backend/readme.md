# Backend — Asistente conversacional RAG (ThermoDrive HTM-240)

Estructura según el diseño «Arquitectura del backend» (§7.3). PostgreSQL + pgvector se ejecutan con Apptainer; la lógica RAG vive en Agentes (opción B).

| Carpeta | Contenido | Estado |
|---|---|---|
| `ingesta/` | Ingesta a demanda: PDF → fragmentos JSONL con metadatos y embeddings bge-m3 → pgvector. Ver [`ingesta/README.md`](ingesta/README.md). | Implementada |
| `db/init/` | `01_conocimiento.sql`: esquema único e idempotente para `conocimiento` y `aplicacion`, con embeddings `vector(1024)`. Apptainer lo aplica al iniciar una base nueva y `start-local.sh` lo reaplica en bases existentes. | Consolidado |
| `api/` | FastAPI: pasarela hacia Agentes, búsquedas, login, historial y registro. | Implementada |

El Backend sirve también una interfaz web adaptable a móvil en `http://127.0.0.1:8000/`. Permite iniciar sesión, consultar el asistente, ver las citas documentales y abrir conversaciones del historial. La interfaz PySide6 sigue disponible como cliente de escritorio. La página web se incluye en la imagen Backend desde `api/app/web_client.html`.

Los PDF de ARSOFT (`data/manuales`), las credenciales (`.env`) y las salidas de la ingesta no se versionan.

## Login, historial y registro de consultas (CTR-005, CTR-006 y CTR-003)

Código en `api/app/sesiones.py`, `api/app/historial.py` y `api/app/registro.py`; tablas en `db/init/01_conocimiento.sql` (esquema `aplicacion`, sin `fragmentos_rag`). `postgres.def` copia el script para que se cree al arrancar una base nueva.

> **Migración en bases ya creadas.** PostgreSQL solo ejecuta `db/init/` la primera vez que inicia un directorio de datos vacío. En una base que ya exista hay que crear el esquema a mano, una vez: `psql "$DATABASE_URL" -f Backend/db/init/01_conocimiento.sql` (es idempotente).

**Usuarios de prueba.**

> ⚠️ **Nunca en producción.** Las contraseñas de abajo son públicas y `admin` puede leer todo el registro de consultas. El script se niega a ejecutarse sin `--desarrollo`. En producción los usuarios se crean con contraseñas propias.

```bash
apptainer exec instance://arsoft-api python -m app.usuarios_prueba --desarrollo
```

| Usuario  | Contraseña | Rol     | Nota                          |
|----------|------------|---------|-------------------------------|
| admin    | admin123   | admin   | puede ver todo el registro    |
| usuario1 | usuario123 | usuario |                               |
| usuario2 | usuario123 | usuario | para probar el aislamiento    |
| inactivo | usuario123 | usuario | desactivado, el login falla   |

**Sesión.** `POST /auth/login` devuelve un `token` (JWT) que Frontend ya envía como `Authorization: Bearer`. Se firma con `ARSOFT_JWT_SECRET` o, si está vacío, con una clave derivada de `ARSOFT_SERVICE_TOKEN`. Se exigen `exp` y `sub`. Dura `ARSOFT_SESSION_MINUTES` (480 por defecto; un valor no numérico o menor que 1 usa el valor por defecto).

- **Una sesión no se puede revocar antes de que caduque**: no hay lista de sesiones ni cierre de sesión en el servidor. Desactivar el usuario (`activo = false`) sí la corta, porque se comprueba en cada petición. Cambiar `ARSOFT_JWT_SECRET` cierra las sesiones de todos.
- **Límite de intentos de login** (en memoria): 5 fallos en 5 minutos por usuario e IP, y 20 por IP con cualquier usuario. Guarda como mucho 10.000 claves y purga las caducadas. La IP es la que ve uvicorn. Si hay un proxy delante, uvicorn usa `X-Forwarded-For` solo cuando el proxy está en `FORWARDED_ALLOW_IPS` (por defecto `127.0.0.1`, donde escucha el backend). Con un proxy en otra máquina hay que añadir su IP ahí; si no, todos los clientes contarían como la misma IP. Con varias réplicas el límite habría que llevarlo a la base.

**Endpoints.** Los errores siguen el formato de la API: `{"codigo_error", "mensaje"}`.

- **CTR-005** `POST /auth/login` `{"usuario", "contrasena"}`
  - 200 `{"estado": "autenticado", "mensaje", "usuario": {"id", "nombre_usuario", "nombre", "rol"}, "token", "token_type", "expires_in"}`
  - 401 `credenciales_invalidas` · 422 `datos_incompletos` · 429 `demasiados_intentos` (5 fallos en 5 min por usuario e IP) · 503 `servicio_no_disponible`. Llevan además `"estado": "no_autenticado"`, como espera Frontend.
  - `GET /auth/me`: usuario de la sesión.
- **CTR-001** `POST /consulta` reenvía la pregunta a `POST {AGENTES_URL}/agentes/consulta` con el token de servicio y devuelve la respuesta de Agentes con el `conversacion_id`. Errores HTTP del propio Backend:
  - 401 `sesion_caducada`: sin token, token manipulado o caducado.
  - 403 `acceso_denegado`: la sesión es válida pero el usuario está desactivado.
  - 404 `conversacion_no_encontrada`: el chat es de otro usuario.
  - 429 `demasiadas_consultas`: más de `ARSOFT_CONSULTAS_POR_MINUTO` (20 por defecto) consultas en 60 s por usuario; lleva `Retry-After`.
  - 500 `error_interno`: fallo no controlado, sin detalles internos en la respuesta (va al log).
  - Los fallos de Agentes (caído, token rechazado o tiempo agotado) llegan como HTTP 200 con `estado: "error"` y `codigo_error` (`servicio_no_disponible`, `tiempo_agotado`). Las respuestas inválidas o las fuentes sin documento, sección y página positiva se convierten en `error_verificacion`, sin exponer texto no verificado.

  Si `conversacion_id` llega vacío, Backend lo genera. Antes de llamar a Agentes reserva el chat de forma atómica (`INSERT … ON CONFLICT … WHERE usuario_id`): si el ID es de otro usuario, aunque lo use a la vez, devuelve 404 `conversacion_no_encontrada` y no se reenvía a Agentes. Cada turno se guarda en el historial y en el registro; si la base falla al guardar, la respuesta se entrega igual. El acceso a PostgreSQL va en un hilo aparte (`run_in_threadpool`) para no bloquear el event loop.
- **CTR-001** `POST /valoracion` `{"trace_id", "util"}` guarda si una respuesta fue útil (`util` es `true` o `false`; no se admiten `1`, `"true"` ni `null`). Código en `api/app/valoracion.py`, tabla `aplicacion.valoracion` en `db/init/01_conocimiento.sql`. Exige sesión como `/consulta`.
  - 200 `{"trace_id", "util"}`. Una valoración por usuario y respuesta: valorar otra vez la misma actualiza `util` y `actualizado_en`, no crea otra fila.
  - Solo se valoran respuestas propias con estado `respuesta` que consten en el registro (CTR-003). Un `trace_id` inexistente, de otro usuario o de una respuesta que no es `respuesta` da el mismo 404 `respuesta_no_encontrada`, para no revelar si existe.
  - 401 `sesion_caducada` · 403 `acceso_denegado` (usuario desactivado) · 422 `entrada_invalida` · 429 `demasiadas_valoraciones` (más de `ARSOFT_VALORACIONES_POR_MINUTO`, 60 por defecto, en 60 s por usuario; lleva `Retry-After` y no gasta el cupo de consultas) · 500 `error_interno` · 503 `servicio_no_disponible` (PostgreSQL caído).
  - **Migración en bases ya creadas:** la tabla es nueva, así que hay que ejecutar una vez `psql "$DATABASE_URL" -f Backend/db/init/01_conocimiento.sql` (idempotente).
- **CTR-002** `POST /conocimiento/vectorial` queda montado en la app (`crear_router(connect, service_access)`), con el token de servicio como el resto de `/conocimiento`.
- **CTR-006** `GET /chats?limit&offset` → `{"chats": [{"conversacion_id", "titulo", "created_at", "updated_at", "mensajes": [{"message_id", "trace_id", "role", "contenido", "estado", "codigo_error", "timestamp", "fuentes"}]}], "total"}`, con la forma que lee Frontend. También `GET`, `PATCH {"titulo"}` y `DELETE /chats/{conversacion_id}` (al borrar se pide a Agentes que olvide la conversación). Cada usuario solo ve los suyos.
- **CTR-007** Historial con Agentes: Agentes lee una conversación con el token de servicio en `GET /chats/{conversacion_id}?limit=N` (los N últimos mensajes, en orden). Es lo que usa `Agents/agente1/cliente_backend.py` (`obtener_historial`) para recuperar la memoria de un chat cuando su sesión en Agentes ha caducado o se ha reiniciado. Con el token de servicio solo se lee un chat: no se listan, no se modifican ni se borran, y no sirve como sesión en `/consulta`. El historial lo escribe Backend en cada `/consulta`.
- **CTR-003** `GET /consultas/mias` y `GET /consultas` (solo admin; filtros `usuario_id`, `tipo`, `estado`, `desde`, `hasta`). Guarda el `trace_id`, la pregunta, el estado, el código de error, los `chunk_id` citados y la latencia. Las búsquedas pueden registrar con `registro.registrar(conn, tipo="vectorial" | "lexica", ...)`.

**Pruebas.**

- `Test/test_Backend/test_usuarios_historial_registro.py`: login, historial, CTR-007, registro y errores.
- `Test/test_Backend/test_valoracion.py`: `POST /valoracion` (éxito, sin sesión, `trace_id` inexistente o ajeno, `util` inválido, valoración repetida, 403, 429, 500 y 503).
- `Test/test_Backend/test_integracion_agentes.py`: de principio a fin. Levanta con uvicorn el Backend y el servicio real de Agentes (`Agents/service.py`, Agente 1 real) y usa el cliente real de Frontend (login, consulta e historial). Solo se sustituyen el LLM del Agente 1 y los modelos BGE-M3 y reranker por versiones deterministas. Si el Agente 2 real está en el repo (`Agents/Agent_2`), Agentes recupera con su pipeline real contra `/conocimiento` del Backend, y se comprueba la pregunta trampa (no se cita el documento sustituido). Si no está, usa el simulador y esa prueba se omite. Necesita PySide6.

Las de base de datos necesitan un PostgreSQL de pruebas vacío **con pgvector**. Las de `Backend/api/tests` se lanzan desde su carpeta, por el `pytest.ini` de la raíz:

```bash
ARSOFT_TEST_DATABASE_URL=postgresql://... PYTHONPATH=.:shared python -m pytest Test/test_Backend
cd Backend/api && PYTHONPATH=.:../../shared python -m pytest -c pyproject.toml
```
