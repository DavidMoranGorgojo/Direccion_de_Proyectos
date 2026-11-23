# Direccion_de_Proyectos

## Para conectar con Backend y Agentes (Estado de Integración)

Estado y acuerdos técnicos confirmados con las **personas 1 (Agentes)** y **2 (Backend)** tras la validación de la suite de pruebas del Frontend:

1. **Rutas (Endpoints HTTP)**:
   - **Consulta al asistente (CTR-001)**: Ruta confirmada en el Backend como `POST /consulta` (en `Frontend/services/api.py` figura provisionalmente como `/agentes/consulta` a la espera de unificación de contrato).
   - **Historial de conversaciones (CTR-006)**: Ruta confirmada como `GET /chats`. El Backend también expone `PATCH /chats/{id}` (renombrar) y `DELETE /chats/{id}` (eliminar con aviso a Agentes).
   - **Autenticación (CTR-005)**: Ruta confirmada en `POST /auth/login`. Devuelve `token` (JWT), objeto `usuario` y tiempo de expiración `expires_in`.

2. **Identificador de la conversación (`conversacion_id`)**:
   - **Generación y preservación**: El cliente puede enviar un ID o dejarlo vacío; el Backend lo reserva y devuelve el identificador oficial.
   - **Continuidad multiturno**: Al continuar un chat recuperado del historial, el chat debe propagar su identificador para mantener la memoria contextual en Backend y Agentes sin crear chats duplicados.

3. **Mecanismo de sesión**:
   - **Método**: Cabecera HTTP `Authorization: Bearer <token>`.
   - **Control de expiración y errores**: Código HTTP 401 indica sesión caducada o credenciales inválidas (provoca redirección al login en Frontend). Código HTTP 403 indica permisos insuficientes (`acceso_denegado`). Límite de 5 intentos fallidos antes de bloqueo HTTP 429 durante 5 minutos.

### Documentación Adicional de Testing Frontend
* **Lista de comprobación manual**: [Frontend/CHECKLIST_MANUAL.md](Frontend/CHECKLIST_MANUAL.md)
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

Desde Ubuntu/WSL2 con Apptainer instalado y WSLg activo:

~~~bash
bash apptainer/start-all.sh
~~~

El primer arranque crea credenciales locales seguras, construye las imágenes que falten y levanta PostgreSQL con pgvector, Backend, Agentes y Frontend. Si hay PDF en data/manuales (o en ARSOFT_MANUALES_DIR), ejecuta la ingesta; si no, la omite y avisa. También prepara usuarios de desarrollo (usuario1 / usuario123) para probar login e historial. Cierra la ventana o pulsa Ctrl+C para detener las instancias que inició el comando.

Ollama y el modelo conversacional son necesarios para probar respuestas del asistente; los PDF son necesarios para probar recuperación RAG. La interfaz, el login y el historial se pueden comprobar sin ellos.

## Paquete del Frontend

`bash apptainer/package-frontend.sh` genera `dist/arsoft-frontend-<versión>.tar.gz` (imagen `.sif`, `run-frontend.sh`, `verificar.sh`, sumas SHA-256 y `LEEME.txt`). Ver [`apptainer/README.md`](apptainer/README.md#paquete-final-del-frontend).
