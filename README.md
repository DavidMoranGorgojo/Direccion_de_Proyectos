# Direccion_de_Proyectos

Repositorio de ARSOFT: asistente técnico conversacional sobre la documentación de ThermoDrive HTM-240.

| Carpeta | Servicio |
|---|---|
| `Frontend/` | Aplicación de escritorio PySide6 (login, chat, historial). Ver [`Frontend/readme.md`](Frontend/readme.md). |
| `Backend/` | FastAPI (login, historial, consulta, registro), PostgreSQL con pgvector e ingesta. Ver [`Backend/readme.md`](Backend/readme.md). |
| `Agents/` | Agentes (RAG con Ollama) y su adaptador HTTP. |
| `apptainer/` | Imágenes, scripts de arranque y empaquetado. Ver [`apptainer/README.md`](apptainer/README.md). |

## Modos del Frontend

- **Simulado (demo):** sin `ARSOFT_API_URL`. Respuestas de ejemplo; no necesita Backend ni Agentes. Usuario `demo` / `demo1234`.
- **Real:** con `ARSOFT_API_URL` (o `ARSOFT_MODO=real`). Habla con el Backend, que reenvía a Agentes. Ver [`Frontend/readme.md`](Frontend/readme.md#23-pasar-a-modo-real-con-backend).

## Rutas confirmadas (Frontend → Backend)

| Contrato | Ruta | Notas |
|---|---|---|
| CTR-005 Login | `POST /auth/login` | Devuelve un JWT; el Frontend lo envía como `Authorization: Bearer <token>`. |
| CTR-001 Consulta | `POST /consulta` | `/agentes/consulta` es la ruta interna Backend → Agentes; el Frontend no la usa. |
| CTR-006 Historial | `GET /chats` | Cada usuario solo ve sus chats. |

- **`conversacion_id`:** la primera pregunta de un chat nuevo lo lleva vacío; el Backend lo genera y lo devuelve, y el Frontend lo reutiliza. Un chat del historial se continúa con su propio ID.
- **Sesión:** Bearer JWT (480 min por defecto, sin renovación ni revocación en el servidor). 401/403 → «Tu sesión ha caducado» y vuelta al login. Otros errores de la consulta: 404 conversación no disponible, 422 entrada inválida, 429 demasiadas consultas, 5xx error genérico.
- Detalle de errores y respuestas: [`Backend/readme.md`](Backend/readme.md) y [`apptainer/INTEGRACION_CONTRATOS.md`](apptainer/INTEGRACION_CONTRATOS.md).

## Arrancar todo junto (Ubuntu / WSL2)

Pasos completos en [`apptainer/README.md`](apptainer/README.md#arrancar-todo-junto). En resumen: construir las imágenes, `bash apptainer/start-local.sh` (PostgreSQL + Backend), arrancar Agentes con Ollama, crear los usuarios de prueba y abrir el Frontend con `ARSOFT_API_URL=http://127.0.0.1:8000 bash apptainer/run-frontend.sh`.

## Paquete del Frontend

`bash apptainer/package-frontend.sh` genera `dist/arsoft-frontend-<versión>.tar.gz` (imagen `.sif`, `run-frontend.sh`, `verificar.sh`, sumas SHA-256 y `LEEME.txt`). Ver [`apptainer/README.md`](apptainer/README.md#paquete-final-del-frontend).
