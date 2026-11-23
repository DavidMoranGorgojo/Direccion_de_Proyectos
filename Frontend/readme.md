# Frontend — Asistente Técnico (MR BOT by ARSOFT)

Interfaz gráfica de escritorio para el asistente conversacional técnico sobre la documentación de ThermoDrive HTM-240, desarrollada con **Python** y **PySide6 (Qt)**.

---

## 1. Estructura del módulo

| Carpeta / Archivo | Descripción |
|---|---|
| `components/` | Componentes visuales reutilizables: burbujas de chat (`chat_message.py`), tarjetas de citas/fuentes (`source_card.py`), elementos de la lista de conversaciones (`conversation_item.py`). |
| `models/` | Modelos de datos del dominio: `Conversation`, `Message`, `Response` (CTR-001), `Source` (citas documentales) y formateo de fechas (`dates.py`). |
| `services/` | Servicios de comunicación: cliente HTTP y simulador (`api.py`), autenticación (`auth.py`) y estado de sesión en memoria (`session.py`). |
| `ui/` | Archivos XML de diseño de Qt Designer (`login_window.ui`, `main_window.ui`). |
| `views/` | Controladores de ventanas: pantalla de login (`login_window.py`) y pantalla principal de chat (`main_window.py`). |
| `assets/` | Estilos CSS/QSS (`style.qss`), iconos vectoriales SVG e imágenes corporativas. |
| `main.py` | Punto de entrada de la aplicación que gestiona el ciclo de vida login → chat → logout. |

---

## 2. Modos de funcionamiento

### 2.1. Modo simulado (Conexión falsa por defecto)
Cuando la variable de entorno `ARSOFT_API_URL` **no está definida**, el cliente `services/api.py` activa automáticamente el **modo simulado**:
- Permite desarrollar, probar e interactuar con la interfaz de forma completamente autónoma, sin necesidad de que el Backend o los modelos de IA estén ejecutándose.
- Simula las respuestas técnicas bajo los contratos del proyecto:
  - **CTR-001**: Respuestas estructuradas con texto, estado (`respuesta`, `aclaracion`, `fuera_de_ambito`, `sin_evidencia`, `error`), `trace_id`, `codigo_error` y fuentes documentales (`Source`). Las consultas que contienen `simular_error`, `error_simulado` o `timeout` reproducen un error 503 del motor de búsqueda.
  - **CTR-006**: Historial precargado de conversaciones (`GET /chats`), con soporte para simular historial vacío mediante `ARSOFT_MOCK_EMPTY_HISTORY=1`.
  - **CTR-005**: Inicio de sesión simulado (`usuario: demo`, `contraseña: demo1234`), además de simulación de errores 401 y 429 (`usuario: rate_limit`).

### 2.2. Modo conectado (Backend real)
Al definir la variable de entorno:
```bash
export ARSOFT_API_URL="https://backend-api.local"
```
El cliente realiza llamadas HTTP reales mediante `urllib.request`. Fuera de localhost se exige HTTPS (desactivable para pruebas locales con `ARSOFT_ALLOW_HTTP=1`).

---

## 3. Pruebas automatizadas

Las pruebas unitarias y de integración del Frontend se ubican en `Test/test_Frontend/`:
- **`Test/test_Frontend/test_conexion_simulada.py`**:
  - Lectura y validación de respuestas CTR-001 (estados `respuesta`, `aclaracion`, `fuera_de_ambito`, `sin_evidencia` y fuentes).
  - Lectura del historial CTR-006 y soporte de historial vacío.
  - Gestión de códigos de error HTTP: 401 (no autenticado / sesión caducada), 403 (prohibido), 429 (rate limit) y 500 (error interno del servidor).
  - Resiliencia ante JSON no válido, respuestas malformadas y estados desconocidos.
  - Envío de consultas y preservación de la pregunta exacta según CTR-001.
  - Bloqueo del envío durante la respuesta y representación de errores del simulador como mensajes del asistente.
- **`Test/test_Frontend/test_interfaz_usuario.py`**:
  - Formulario de Login (`LoginWindow`): validación de campos vacíos, limpieza de errores en `textChanged`, alternancia de visibilidad de contraseña (Password/Normal), estados de carga y bloqueo (`_set_busy`), emisión de `authenticated` y función `reset()`.
  - Ventana Principal (`MainWindow`): renderizado inicial de cabecera y usuario, estado vacío al iniciar chat, creación y reutilización de conversaciones vacías en `new_chat`, selección y renderizado del historial, ordenación cronológica, envío con generación automática de título (truncado a 40 caracteres con elipsis), filtro de teclado (Enter para enviar vs Shift+Enter para salto de línea), eliminación de burbuja de typing al responder y bloqueo de logout con peticiones en curso.
  - Componentes visuales (`ChatMessage`, `SourceCard`, `ConversationItem`): renderizado de burbujas de usuario y asistente, asignación de badges según estado (`aclaracion`, `sin_evidencia`, `fuera_de_ambito`, `error`), tarjetas de fuentes documentales con aviso de obsolescencia y formateo relativo de fechas (`Hoy HH:MM` vs `DD/MM/AAAA`).
  - Coordinador de aplicación (`App` en `main.py`): flujo completo de navegación y ciclo de vida login → chat → logout → login con almacenamiento y limpieza del estado de sesión.

- **`Test/test_Frontend/test_backend_real.py`**:
  - Servidor real Uvicorn en bucle local (`127.0.0.1`) levantando la aplicación FastAPI del Backend (`Backend/api/app/main.py`).
  - Autenticación real CTR-005: emisión de JWT, validación de credenciales con bcrypt, errores 401, 422 y límite de intentos 429.
  - Historial CTR-006: creación automática de chat en consulta, aislamiento por usuario, persistencia del `server_id` y errores 401/503.
  - Consulta CTR-001: comunicación completa cliente -> Backend -> Agentes, validación de todos los estados (`respuesta`, `aclaracion`, `fuera_de_ambito`, `sin_evidencia`, `error`), gestión de errores 401, 403, 429, 500 y 503.
  - Pruebas end-to-end de principio a fin activables con la variable `ARSOFT_E2E_URL`.

Además se dispone de:
* **Lista de comprobación manual**: [`CHECKLIST_MANUAL.md`](CHECKLIST_MANUAL.md) con el protocolo para verificación manual de toda la interfaz.

Ejecución de las pruebas:
```bash
pytest Test/test_Frontend/
```
o bien con el ejecutor estándar de Python:
```bash
python -m unittest discover -s Test/test_Frontend -p "test_*.py"
```

---

## 4. Para conectar con Backend y Agentes (Estado Confirmado)

Estado verificado de la integración tras la batería de pruebas contra el Backend real:

1. **Rutas (Endpoints HTTP)**:
   - **CTR-001 (Consulta)**: Ruta confirmada en el Backend como `POST /consulta` (en `Frontend/services/api.py` figura provisionalmente como `/agentes/consulta` a la espera de unificación de contrato).
   - **CTR-006 (Historial)**: Ruta confirmada como `GET /chats`. También existen en Backend `PATCH /chats/{id}` y `DELETE /chats/{id}`.
   - **CTR-005 (Login)**: Confirmado en `POST /auth/login`. Devuelve `token` (JWT), `usuario` y `expires_in`.

2. **Identificador de la conversación (`conversacion_id`)**:
   - Si el Frontend envía `conversacion_id` vacío o un ID local, el Backend lo respeta o genera uno nuevo, devolviéndolo en la respuesta.
   - Al continuar un chat recuperado del historial, el chat debe propagar su identificador para que los mensajes siguientes continúen el mismo hilo en Backend y Agentes.

3. **Mecanismo de sesión**:
   - **Tipo de token**: Bearer JWT en cabecera `Authorization: Bearer <token>`.
   - **Caducidad**: 480 minutos por defecto. HTTP 401 activa `session_expired` y redirige al Login.
   - **Seguridad**: Límite de 5 intentos fallidos antes de bloquear por HTTP 429 durante 5 minutos.

