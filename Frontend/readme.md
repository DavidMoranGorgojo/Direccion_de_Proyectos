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
| `apptainer/` | Definición del contenedor del Frontend (`frontend.def`). |
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
   ARSOFT_CONSULTA_PATH=/agentes/consulta
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
| `ARSOFT_CONSULTA_PATH` | `/agentes/consulta` | Ruta de consulta al asistente (CTR-001). Pendiente de confirmar con Backend. |
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
  - Gestión de códigos de error HTTP: 401 (no autenticado / sesión caducada), 403 (prohibido), 429 (rate limit) y 500 (error interno del servidor).
  - Resiliencia ante JSON no válido, respuestas malformadas y estados desconocidos.
  - Envío de consultas y preservación de la pregunta exacta según CTR-001.
  - Bloqueo del envío durante la respuesta y representación de errores del simulador como mensajes del asistente.
- **`Test/test_Frontend/test_config.py`**:
  - Valores por defecto, lectura de `.env` y prioridad entre entorno, `Frontend/.env` y `.env` de la raíz.
  - Normalización de rutas, tiempo máximo, modo y opciones.
  - Comportamiento de los modos simulado, real y automático.

Ejecución de las pruebas (desde la raíz del repositorio):
```bash
pytest Test/test_Frontend/
```
> **Nota sobre `PYTHONPATH=shared`:** el Frontend no importa nada de `shared/`, así que sus
> pruebas no lo necesitan. Sí lo necesitan las de Agentes y Backend (`arsoft_http`). Para no
> tener que exportarlo a mano, el `pytest.ini` de la raíz ya añade `shared` a la ruta de
> importación (`pythonpath = shared`); basta con lanzar `pytest` desde la raíz. Si se ejecutan
> con otro ejecutor (p. ej. `unittest`) desde otra carpeta, hay que definirlo manualmente:
> `PYTHONPATH=shared` (Linux/macOS) o `$env:PYTHONPATH="shared"` (PowerShell).

o bien con el ejecutor estándar de Python:
```bash
python -m unittest discover -s Test/test_Frontend -p "test_*.py"
```

---

## 5. Para conectar con Backend y Agentes

Lista de aspectos pendientes a confirmar con las **personas 1 (Agentes)** y **2 (Backend)** para la integración final. Cuando se confirmen, basta con cambiar los valores en `.env` (o los valores por defecto de `config.py`).

1. **Rutas (Endpoints HTTP)**:
   - **CTR-001 (Consulta)**: El cliente usa provisionalmente `POST /agentes/consulta` (`ARSOFT_CONSULTA_PATH`). El Backend expone actualmente `POST /consulta`; queda pendiente de confirmar cuál será la ruta definitiva.
   - **CTR-006 (Historial)**: Confirmar la ruta de recuperación del historial (actualmente `ARSOFT_HISTORIAL_PATH=/chats`) y soporte para operaciones de borrado.
   - **CTR-005 (Login)**: Confirmar la ruta final de autenticación (`ARSOFT_LOGIN_PATH=/auth/login`) y endpoints complementarios (logout, validación de sesión).

2. **Identificador de la conversación (`conversacion_id`)**:
   - **Formato actual**: El Frontend genera un UUID opaco para un chat nuevo y lo envía en cada consulta como `conversacion_id`.
   - **Agentes**: `Agente1` conserva ese identificador y su memoria para los turnos sucesivos; la función CTR-001 devuelve `trace_id`, `estado`, `texto`, `fuentes` y `codigo_error`.
   - **Pendiente con Backend**: Confirmar si Backend acepta el UUID generado por Frontend o lo sustituye por uno propio, y cómo persiste la conversación.

3. **Mecanismo de sesión**:
   - **Tipo de token**: Confirmar el uso de Bearer token (`Authorization: Bearer <token>`) o cookie de sesión.
   - **Caducidad**: Formato de error y flujo de renovación ante expiración (HTTP 401 / 403).

   **Estado comprobado en el Frontend:** el `token` devuelto por login se conserva en memoria y,
   si existe, se envía en la cabecera `Authorization`. El esquema definitivo del token o cookie,
   su caducidad y la renovación siguen pendientes de confirmación con Backend; ante 401/403 se
   cierra la sesión.
