# Frontend — Asistente Técnico (MR BOT by ARSOFT)

Interfaz gráfica de escritorio para el asistente conversacional técnico sobre la documentación de ThermoDrive HTM-240, desarrollada con **Python** y **PySide6 (Qt)**.

---

## 1. Estructura del módulo

| Carpeta / Archivo | Descripción |
|---|---|
| `config.py` | **Único sitio de configuración**: modo, URL del Backend, rutas, tiempo máximo y opciones de prueba (ver sección 3). |
| `components/` | Componentes visuales reutilizables: burbujas de chat (`chat_message.py`), tarjetas de citas/fuentes (`source_card.py`), elementos de la lista de conversaciones (`conversation_item.py`). |
| `models/` | Modelos de datos del dominio: `Conversation`, `Message`, `Response` (CTR-001), `Source` (citas documentales) y formateo de fechas (`dates.py`). |
| `services/` | Servicios de comunicación: cliente HTTP y simulador (`api.py`), autenticación (`auth.py`) y estado de sesión en memoria (`session.py`). |
| `ui/` | Archivos XML de diseño de Qt Designer (`login_window.ui`, `main_window.ui`). |
| `views/` | Controladores de ventanas: pantalla de login (`login_window.py`) y pantalla principal de chat (`main_window.py`). |
| `assets/` | Estilos CSS/QSS (`style.qss`), iconos vectoriales SVG e imágenes corporativas. |
| `apptainer/` | Definición del contenedor del Frontend (`frontend.def`). Empaquetado en la sección 7. |
| `main.py` | Punto de entrada de la aplicación que gestiona el ciclo de vida login → chat → logout. |

---

## 2. Ejecución

### 2.1. Requisitos (una sola vez)

Python 3.10 o superior. Desde la **raíz del repositorio**:

```bash
python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# Linux / macOS / WSL:   source .venv/bin/activate
pip install -r Frontend/requirements.txt
```

### 2.2. Modo simulado (sin Backend)

Es el modo por defecto: no hace falta ningún `.env` ni tener el Backend o los Agentes en marcha.
Las respuestas son **de ejemplo**, no las del asistente real; sirve para desarrollar y probar la interfaz.

1. Ejecuta la aplicación:
   ```bash
   python Frontend/main.py
   ```
2. Inicia sesión con **usuario `demo`** y **contraseña `demo1234`**.
3. Prueba los distintos casos del simulador:

   | Qué escribir | Resultado simulado |
   |---|---|
   | Una frase con `refrigerante` o `temperatura` (más de 2 palabras) | Respuesta correcta con fuentes (`respuesta`) |
   | 1 o 2 palabras (p. ej. `motor fallo`) | Repregunta (`aclaracion`) |
   | Una frase con `tiempo` o `receta` | Fuera de ámbito (`fuera_de_ambito`) |
   | Cualquier otra frase | Sin evidencia (`sin_evidencia`) |
   | Una frase con `simular_error`, `error_simulado` o `timeout` | Error 503 del motor de búsqueda (`error`) |
   | Una frase con `servidor_caido`, `backend_caido` o `agentes_caido` | Servicio no disponible (`error`) |
   | Usuario `rate_limit` en el login | Error 429 (demasiados intentos) |
   | Contraseña incorrecta | Error 401 (credenciales inválidas) |

4. Opcional: para arrancar con el historial vacío, pon `ARSOFT_MOCK_EMPTY_HISTORY=1` en tu `.env`.

La ventana muestra el aviso *"Modo simulado: sin backend conectado"* mientras se usa este modo.

### 2.3. Pasar a modo real (con Backend)

1. Copia la plantilla de configuración de la raíz:
   ```bash
   cp .env.example Frontend/.env          # Windows: Copy-Item .env.example Frontend\.env
   ```
   (También vale un `.env` en la raíz; el de `Frontend/` tiene prioridad.)
2. Edita `Frontend/.env` y cambia **como mínimo**:
   ```ini
   ARSOFT_MODO=real
   ARSOFT_API_URL=https://url-del-backend      # sin barra final
   ```
3. Ajusta, si el Backend usa otras, las rutas y el tiempo máximo:
   ```ini
   ARSOFT_LOGIN_PATH=/auth/login
   ARSOFT_HISTORIAL_PATH=/chats
   ARSOFT_CONSULTA_PATH=/consulta
   ARSOFT_VALORACION_PATH=/valoracion
   ARSOFT_TIMEOUT_S=60
   ```
4. Ejecuta igual que antes: `python Frontend/main.py`. El inicio de sesión ya lo valida el Backend.

Notas:
- **HTTPS obligatorio** fuera de `localhost`, `127.0.0.1` o dominios `*.local`. Solo para pruebas puede desactivarse con `ARSOFT_ALLOW_HTTP=1`.
- Con `ARSOFT_MODO=real` y sin `ARSOFT_API_URL` la aplicación **no** pasa al simulador: muestra el error *"Modo real sin servidor configurado"*.
- Con Apptainer (`apptainer/run-frontend.sh`) basta con exportar las variables antes de lanzar el script; las variables del sistema tienen prioridad sobre los `.env`.
- Los `.env` reales no se suben a git (están en `.gitignore`); solo se sube la plantilla `.env.example`.

---

## 3. Configuración

Toda la configuración se lee en `Frontend/config.py`. Cada valor se toma, por orden de prioridad, de:

1. Variables de entorno del sistema.
2. `Frontend/.env`
3. `.env` de la raíz del repositorio.
4. Valor por defecto.

| Variable | Por defecto | Descripción |
|---|---|---|
| `ARSOFT_MODO` | *(vacío = automático)* | `simulado` o `real`. Vacío: real si hay `ARSOFT_API_URL`, simulado si no. |
| `ARSOFT_API_URL` | *(vacío)* | URL base del Backend. Obligatoria en modo real. |
| `ARSOFT_LOGIN_PATH` | `/auth/login` | Ruta de inicio de sesión (CTR-005). |
| `ARSOFT_HISTORIAL_PATH` | `/chats` | Ruta del historial de conversaciones (CTR-006). |
| `ARSOFT_CONSULTA_PATH` | `/consulta` | Ruta de consulta al asistente (CTR-001). Confirmada con Backend. |
| `ARSOFT_VALORACION_PATH` | `/valoracion` | Ruta para valorar una respuesta con 👍 / 👎 (CTR-001). |
| `ARSOFT_TIMEOUT_S` | `60` | Tiempo máximo de cada petición, en segundos. Un valor no válido usa 60. |
| `ARSOFT_ALLOW_HTTP` | `0` | `1` permite `http://` hacia servidores no locales (solo pruebas). |
| `ARSOFT_MOCK_EMPTY_HISTORY` | `0` | `1` hace que el simulador devuelva el historial vacío. |

---

## 4. Pruebas automatizadas

Las pruebas unitarias y de integración del Frontend se ubican en `Test/test_Frontend/`:
- **`Test/test_Frontend/test_conexion_simulada.py`**:
  - Lectura y validación de respuestas CTR-001 (estados `respuesta`, `aclaracion`, `fuera_de_ambito`, `sin_evidencia` y fuentes).
  - Lectura del historial CTR-006 y soporte de historial vacío.
  - Lectura tolerante de chats (`Conversation.from_dict`): mensajes sin `message_id`, `fuentes` ausentes o nulas y fechas con sufijo `Z` (formato que emite el Backend).
  - Gestión de códigos de error HTTP en la consulta (CTR-001): 401/403 (sesión caducada), 404 (conversación no encontrada), 422 (entrada inválida), 429 (demasiadas consultas) y 500 (error interno, mensaje genérico). Cada uno devuelve un `Response` de error con su `codigo_error`.
  - Resiliencia ante JSON no válido, respuestas malformadas y estados desconocidos.
  - Envío de consultas y preservación de la pregunta exacta según CTR-001.
  - Bloqueo del envío durante la respuesta y representación de errores del simulador como mensajes del asistente.
- **`Test/test_Frontend/test_config.py`**:
  - Valores por defecto, lectura de `.env` y prioridad entre entorno, `Frontend/.env` y `.env` de la raíz.
  - Normalización de rutas, tiempo máximo, modo y opciones.
  - Comportamiento de los modos simulado, real y automático.
- **`Test/test_Frontend/test_interfaz_usuario.py`**:
  - Formulario de Login (`LoginWindow`): validación de campos vacíos, limpieza de errores en `textChanged`, alternancia de visibilidad de contraseña (Password/Normal), estados de carga y bloqueo (`_set_busy`), emisión de `authenticated` y función `reset()`.
  - Ventana Principal (`MainWindow`): renderizado inicial de cabecera y usuario, estado vacío al iniciar chat, creación y reutilización de conversaciones vacías en `new_chat`, selección y renderizado del historial, ordenación cronológica, renombrado y borrado de chats persistidos, envío con generación automática de título (truncado a 40 caracteres con elipsis), filtro de teclado (Enter para enviar vs Shift+Enter para salto de línea), eliminación de burbuja de typing al responder y bloqueo de acciones durante peticiones en curso.
  - Componentes visuales (`ChatMessage`, `SourceCard`, `ConversationItem`): renderizado de burbujas de usuario y asistente, asignación de badges según estado (`aclaracion`, `sin_evidencia`, `fuera_de_ambito`, `error`), acciones de renombrado y borrado en los chats persistidos, tarjetas de fuentes documentales con aviso de obsolescencia y formateo relativo de fechas (`Hoy HH:MM` vs `DD/MM/AAAA`).
  - Coordinador de aplicación (`App` en `main.py`): flujo completo de navegación y ciclo de vida login → chat → logout → login con almacenamiento y limpieza del estado de sesión.

- **`Test/test_Frontend/test_backend_real.py`**:
  - Servidor real Uvicorn en bucle local (`127.0.0.1`) levantando la aplicación FastAPI del Backend (`Backend/api/app/main.py`).
  - Autenticación real CTR-005: emisión de JWT, validación de credenciales con bcrypt, errores 401, 422 y límite de intentos 429.
  - Historial CTR-006: creación automática de chat en consulta, aislamiento por usuario, persistencia del `server_id`, renombrado, borrado y errores 401/503.
  - Consulta CTR-001: comunicación completa cliente -> Backend -> Agentes, validación de todos los estados (`respuesta`, `aclaracion`, `fuera_de_ambito`, `sin_evidencia`, `error`), gestión de errores 401, 403, 429, 500 y 503.
  - Pruebas end-to-end de principio a fin activables con la variable `ARSOFT_E2E_URL`.

**Alcance pendiente:** no se ha validado en la interfaz gráfica una respuesta correcta generada por un LLM real. Las pruebas locales contra Backend sustituyen PostgreSQL y el transporte de Agentes; las pruebas end-to-end opcionales requieren un despliegue configurado con `ARSOFT_E2E_URL` y no equivalen a una validación visual de la GUI.

Además se dispone de:
* **Lista de comprobación manual**: [`CHECKLIST_MANUAL.md`](CHECKLIST_MANUAL.md) con el protocolo para verificación manual de toda la interfaz.

Ejecución de las pruebas (desde la raíz del repositorio):
```bash
pytest Test/test_Frontend/
```
> **Nota sobre `PYTHONPATH=shared`:** el Frontend no importa nada de `shared/`, así que sus
> pruebas no lo necesitan. Sí lo necesitan las de Agentes y Backend (`arsoft_http`). Para no
> tener que exportarlo a mano, el `pytest.ini` de la raíz ya añade `Frontend`, la raíz y `shared`
> a la ruta de importación (`pythonpath = Frontend . shared`); basta con lanzar `pytest` desde la raíz. Si se ejecutan
> con otro ejecutor (p. ej. `unittest`) desde otra carpeta, hay que definirlo manualmente:
> `PYTHONPATH=shared` (Linux/macOS) o `$env:PYTHONPATH="shared"` (PowerShell).

o bien con el ejecutor estándar de Python:
```bash
python -m unittest discover -s Test/test_Frontend -p "test_*.py"
```

---

## 5. Cierre de rutas y conformidad formal de Frontend

**Rutas definitivas acordadas con Backend:**

| Contrato | Ruta definitiva | Conformidad de Frontend |
|---|---|---|
| CTR-001 Consulta | `POST /consulta` | Conforme. El primer mensaje envía `conversacion_id` vacío; Backend genera y devuelve el ID oficial, que se reutiliza en los turnos siguientes y al continuar un chat del historial. |
| CTR-005 Login | `POST /auth/login` | Conforme. El cuerpo es `{"usuario", "contrasena"}`; el login devuelve el JWT y el Frontend lo envía como `Authorization: Bearer <token>`. |
| CTR-006 Historial | `GET /chats`, `PATCH /chats/{id}`, `DELETE /chats/{id}` | Conforme. Frontend lista, renombra y elimina chats persistidos del usuario autenticado; el borrado pide confirmación y el historial se actualiza al terminar. |

**Conformidad formal:** Frontend da su conformidad a los contratos CTR-001, CTR-005 y CTR-006 con las rutas y el comportamiento indicados. `/agentes/consulta` es exclusivamente la ruta interna Backend → Agentes; Frontend no la invoca.

**Sesión y alcance:** el token es Bearer JWT y dura 480 minutos por defecto. La sesión se cierra localmente en Frontend; no se añade logout de servidor ni renovación del token. Ante HTTP 401/403, Frontend trata la sesión como caducada y vuelve al Login. El límite de intentos de login es de 5 fallos en 5 minutos; Backend responde HTTP 429.

## 6. Contratos con Backend y Agentes (estado confirmado)

Valores por defecto de `config.py`; si cambian, basta con modificarlos en `.env`.

| Contrato | Ruta (variable) | Estado |
|---|---|---|
| CTR-005 Login | `POST /auth/login` (`ARSOFT_LOGIN_PATH`) | Confirmada. Cuerpo `{"usuario", "contrasena"}`; devuelve `token`. |
| CTR-001 Consulta | `POST /consulta` (`ARSOFT_CONSULTA_PATH`) | Confirmada. `/agentes/consulta` es la ruta interna Backend → Agentes; el Frontend no la usa. |
| CTR-006 Historial | `GET /chats` (`ARSOFT_HISTORIAL_PATH`), `PATCH /chats/{id}`, `DELETE /chats/{id}` | Confirmadas. Frontend lista, renombra y elimina chats propios. `GET /chats` va paginado (`limit` máximo 200 y `offset`): el Frontend pide páginas de 200 hasta cubrir `total` (número de chats del usuario). |
| CTR-001 Valoración | `POST /valoracion` (`ARSOFT_VALORACION_PATH`) | Confirmada en Backend. Cuerpo `{"trace_id", "util"}` (`util` es `true` o `false`); devuelve `{"trace_id", "util"}`. |

- **`conversacion_id`:** la primera pregunta de un chat nuevo lleva `conversacion_id` vacío; el Backend genera el ID y lo devuelve en la respuesta, y el Frontend lo reutiliza (`Conversation.server_id`). Un chat cargado del historial se continúa con su propio `conversacion_id`. El UUID local de `Conversation.id` solo identifica el chat en la interfaz.
- **Agentes:** `Agente1` conserva ese identificador y su memoria entre turnos. La respuesta de CTR-001 trae `trace_id`, `estado`, `texto`, `fuentes` y `codigo_error`; los fallos controlados de Agentes llegan como HTTP 200 con `estado: "error"`.
- **Persistencia:** Backend guarda el chat y sus mensajes con ese ID y cada usuario solo accede a los suyos.
- **Sesión:** token Bearer (JWT). El `token` del login se conserva en memoria y se envía en `Authorization: Bearer <token>`. Caduca a los 480 minutos por defecto; no hay renovación ni revocación en el servidor.
- **Errores de la consulta y el historial:**

  | HTTP | Qué muestra el Frontend |
  |---|---|
  | 401 / 403 | «Tu sesión ha caducado…» y vuelta al login. |
  | 404 | «Esta conversación ya no está disponible…» (chat ajeno o borrado). |
  | 422 | «La consulta no se ha podido enviar…». |
  | 429 | «Demasiadas consultas seguidas…». |
  | 5xx, JSON no válido, sin conexión, tiempo agotado | Mensaje de error genérico del asistente. |

  Comprobado contra el Backend real en `Test/test_Frontend/test_conexion_real.py` (requiere `ARSOFT_TEST_DATABASE_URL`).

- **Valoración de respuestas:** cada respuesta del asistente con estado `respuesta` y `trace_id` muestra los botones 👍 y 👎 (el Backend rechaza con 404 cualquier otro estado, así que en el resto no aparecen). Se puede cambiar la valoración pulsando el otro botón. La valoración se guarda **solo en memoria** mientras la aplicación está abierta: `GET /chats` no la devuelve, así que al recargar el historial los botones salen sin marcar. Si el envío falla, el botón vuelve a su valor anterior y aparece un texto discreto bajo la respuesta; si la sesión ha caducado se muestra el aviso y se vuelve al login.

  | HTTP de `/valoracion` | Qué muestra el Frontend |
  |---|---|
  | 401 / 403 | «Tu sesión ha caducado…» y vuelta al login. |
  | 404 | «Esta respuesta ya no se puede valorar.» |
  | 429 | «Demasiadas valoraciones seguidas. Espera un momento.» |
  | 422, 5xx, JSON no válido, sin conexión, tiempo agotado | «No se pudo enviar tu valoración. Inténtalo de nuevo.» |

- **Errores de login e historial:**

  | Pantalla | HTTP | Qué muestra el Frontend |
  |---|---|---|
  | Login | 401 | Mensaje del servidor o «Usuario o contraseña incorrectos». |
  | Login | 403 | «No tienes permiso para entrar. Habla con el administrador.» |
  | Login | 429 | «Demasiados intentos. Espera un momento antes de reintentar.» |
  | Login | 5xx | «El servidor ha tenido un problema. Inténtalo más tarde.» |
  | Historial | 401 / 403 | «Tu sesión ha caducado…» y vuelta al login. |
  | Historial | 429 | «Demasiadas peticiones. Espera un momento y reintenta.» |
  | Historial | 5xx | «No se pudo cargar el historial. Inténtalo más tarde.» |

Quedan fuera de este cierre la renovación del token y los endpoints adicionales de sesión (`logout` y validación con `/auth/me`); el cierre de sesión de Frontend es local. El renombrado y borrado de chats se realizan sobre las rutas CTR-006 indicadas en la sección 5.

### 5.1 Cierre de versión estable — 24-11-2026

Queda congelado para CTR-001 el acuerdo de integración siguiente:

- Frontend → Backend: `POST /consulta`.
- Primer mensaje de un chat nuevo: `conversacion_id` vacío; Backend devuelve el identificador oficial.
- Mensajes posteriores o chats cargados: se reutiliza el mismo `conversacion_id` en Backend y Agentes.
- Sesión: `Authorization: Bearer <token>`; 401/403 se tratan como sesión caducada.
- Respuestas admitidas: `respuesta`, `aclaracion`, `sin_evidencia`, `fuera_de_ambito` y `error`.
- Timeout y servidor inaccesible se muestran como errores controlados y no bloquean la interfaz.

---

## 7. Empaquetado y arranque con Apptainer

La imagen se define en `Frontend/apptainer/frontend.def` (Python con PySide6 y las librerías de Qt/XCB). No incluye `__pycache__`, `.vscode` ni `.env`, y su fase `%test` falla la construcción si Qt o la configuración no cargan.

Desde la raíz del repositorio, en Ubuntu/WSL2 con Apptainer (guía: `apptainer/GUIA_INSTALACION_WINDOWS.md`):

```bash
bash apptainer/build-all.sh frontend            # construye ~/arsoft-images/frontend.sif
bash apptainer/run-frontend.sh                  # demo simulada
ARSOFT_API_URL=http://127.0.0.1:8000 bash apptainer/run-frontend.sh   # modo real
```

`run-frontend.sh` pasa al contenedor solo las variables de la sección 3 (`ARSOFT_MODO`, `ARSOFT_API_URL`, rutas, `ARSOFT_TIMEOUT_S`, `ARSOFT_ALLOW_HTTP`, `ARSOFT_MOCK_EMPTY_HISTORY`).

**Paquete final.** `bash apptainer/package-frontend.sh` crea `dist/arsoft-frontend-<versión>.tar.gz` con `frontend.sif`, `run-frontend.sh`, `verificar.sh`, `SHA256SUMS` y `LEEME.txt`. En la máquina de destino basta con Apptainer y sesión gráfica:

```bash
tar -xzf arsoft-frontend-*.tar.gz && cd arsoft-frontend-*/
bash verificar.sh && bash run-frontend.sh
```

Para arrancar Frontend junto con PostgreSQL, Backend y Agentes, ver `apptainer/README.md` (sección «Arrancar todo junto»).
