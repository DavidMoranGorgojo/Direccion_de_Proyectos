# Lista de Comprobación Manual (Manual QA Checklist)
## Asistente Técnico MR BOT — Aplicación Completa (Frontend)

Esta lista de verificación detalla el protocolo paso a paso para realizar pruebas funcionales y visuales de la aplicación completa, tanto en **Modo Simulado** como en **Modo Conectado (Backend + Agentes)**.

---

### Configuración de Entornos de Prueba

* **Modo Simulado (Desarrollo autónomo)**:
  ```powershell
  Remove-Item Env:\ARSOFT_API_URL -ErrorAction SilentlyContinue
  python Frontend/main.py
  ```
* **Modo Conectado (Backend real)**:
  ```powershell
  $env:ARSOFT_API_URL = "http://127.0.0.1:8000"
  python Frontend/main.py
  ```

---

## 1. Pantalla de Inicio de Sesión (`LoginWindow`)

| ID | Caso de Prueba | Pasos a Ejecutar | Comportamiento Esperado | Estado |
|---|---|---|---|:---:|
| **LG-01** | Renderizado inicial | Abrir la aplicación sin sesión activa. | Aparece centrada la ventana de Login con el logo de ARSOFT, campos de «Usuario» y «Contraseña», botón «Iniciar sesión» y foco en el campo de usuario. | [ ] |
| **LG-02** | Validación campos vacíos | Pulsar «Iniciar sesión» con campos vacíos. | Los campos se marcan con borde de advertencia/error y se muestra el mensaje: *"Faltan datos o el formato es incorrecto."*. No se envía petición de red. | [ ] |
| **LG-03** | Alternancia visibilidad contraseña | Escribir contraseña y hacer clic en el icono del ojo. | Los caracteres alternan entre modo oculto (puntos/asteriscos) y texto visible legible. El icono cambia de estado. | [ ] |
| **LG-04** | Limpieza dinámica de errores | Estando visible un mensaje de error, escribir una letra en cualquier campo. | El mensaje de error desaparece inmediatamente y los bordes recuperan su estilo neutral. | [ ] |
| **LG-05** | Credenciales incorrectas (HTTP 401) | Introducir usuario y contraseña inexistentes (ej. `usuario1` / `mala`). | Se muestra el mensaje: *"Usuario o contraseña incorrectos."*. El campo contraseña se vacía y mantiene el foco. | [ ] |
| **LG-06** | Límite de intentos (HTTP 429) | Fallar intencionadamente el login 5 veces seguidas. | El servidor responde con 429 y se muestra: *"Demasiados intentos. Espera un momento antes de reintentar."*. El acceso queda bloqueado temporalmente. | [ ] |
| **LG-07** | Servidor inalcanzable | Configurar una URL con puerto inactivo (ej. `http://127.0.0.1:9999`) e intentar login. | Muestra el error controlado: *"No se pudo conectar con el servidor."* sin congelar la ventana ni provocar cierre inesperado. | [ ] |
| **LG-08** | Login exitoso | Introducir credenciales válidas (ej. `usuario1` / `usuario123` en modo real o `demo` / `demo1234` en modo simulado). | El botón muestra estado de carga brevemente; la ventana de Login se cierra y se abre fluidamente la Ventana Principal (`MainWindow`). | [ ] |

---

## 2. Ventana Principal y Navegación (`MainWindow`)

| ID | Caso de Prueba | Pasos a Ejecutar | Comportamiento Esperado | Estado |
|---|---|---|---|:---:|
| **WN-01** | Renderizado de cabecera | Iniciar sesión y observar la cabecera superior. | Se visualiza el identificador del usuario activo, el logo de la aplicación y el botón «Cerrar sesión». | [ ] |
| **WN-02** | Indicador de modo de servicio | Observar la etiqueta informativa debajo de la cabecera. | En modo simulado muestra la advertencia en amarillo: *"⚠ Modo simulado: sin backend conectado"*. En modo conectado desaparece o muestra el estado de las conversaciones. | [ ] |
| **WN-03** | Historial vacío inicial | Iniciar sesión con un usuario nuevo sin chats previos. | En la lista lateral se informa que no hay conversaciones y el área central muestra el estado vacío: *"¿En qué puedo ayudarte?"* con icono de bienvenida. | [ ] |
| **WN-04** | Carga de historial existente | Iniciar sesión con un usuario con chats guardados. | Se listan las conversaciones previas ordenadas por fecha de actualización descendente con sus títulos respectivos. Se autoselecciona la más reciente. | [ ] |
| **WN-05** | Cambio de conversación | Hacer clic en otra conversación de la lista lateral. | El panel de chat se vacía y renderiza de inmediato el historial completo del chat seleccionado (preguntas, respuestas y fuentes asociadas). | [ ] |
| **WN-06** | Botón «Nuevo chat» | Pulsar el botón «+ Nuevo chat». | Si el chat actual ya tiene mensajes, crea una conversación vacía y la selecciona. Si el chat actual ya estaba vacío, lo reutiliza sin duplicar chats vacíos. | [ ] |

---

## 3. Envío y Flujo de Consultas (`CTR-001`)

| ID | Caso de Prueba | Pasos a Ejecutar | Comportamiento Esperado | Estado |
|---|---|---|---|:---:|
| **CH-01** | Envío con tecla Enter | Escribir una consulta técnica y presionar la tecla Enter. | El mensaje se envía automáticamente al asistente y el campo de texto se vacía. | [ ] |
| **CH-02** | Salto de línea con Shift+Enter | Escribir texto y presionar Shift+Enter. | No se envía el mensaje; se añade un salto de línea en el campo de texto y este autoajusta su altura. | [ ] |
| **CH-03** | Ignorar envíos vacíos | Presionar Enter o el botón de enviar con el campo en blanco o solo espacios. | No ocurre ninguna acción ni se altera la conversación. | [ ] |
| **CH-04** | Generación automática de título | En un chat nuevo, enviar una primera pregunta (ej. *"¿Cuál es el par de apriete de los tornillos de culata?"*). | El título del chat en la barra lateral y en la cabecera se actualiza automáticamente con los primeros 40 caracteres seguidos de puntos suspensivos si procede. | [ ] |
| **CH-05** | Burbuja de usuario | Tras el envío, verificar el mensaje propio. | Aparece en el margen derecho, con estilo visual destacado y preservando exactamente el texto escrito (sin recortes involuntarios). | [ ] |
| **CH-06** | Indicador de escritura (Typing) | Observar la pantalla tras enviar la pregunta mientras el servidor procesa. | Se inserta una burbuja temporal en el margen izquierdo indicando que el asistente está redactando. El botón de envío y el campo se deshabilitan. | [ ] |
| **CH-07** | Recepción de respuesta y scroll | Esperar la llegada de la respuesta. | La burbuja de «escribiendo» se elimina limpiamente, se añade la respuesta del asistente, el scroll baja automáticamente hasta el final y el campo de texto recupera el foco. | [ ] |
| **CH-08** | Continuación de hilo (multiturno) | Enviar una segunda pregunta en el mismo chat (ej. *"¿Y qué herramienta necesito?"*). | La segunda pregunta se vincula al mismo `conversacion_id`, manteniendo la memoria conversacional tanto en Agentes como en el Backend. | [ ] |

---

## 4. Tipos de Respuesta y Tarjetas de Citas Documentales

| ID | Caso de Prueba | Consulta de Prueba | Comportamiento Visual Esperado | Estado |
|---|---|---|---|:---:|
| **RS-01** | Respuesta fundamentada (`respuesta`) | *"¿Cada cuánto se cambia el refrigerante?"* | Texto técnico explicativo acompañado de una o varias tarjetas de fuente (`SourceCard`) con documento, sección y página. | [ ] |
| **RS-02** | Repregunta (`aclaracion`) | *"fallo motor"* (consulta ambigua) | Burbuja de respuesta con badge destacado de aclaración solicitando versión o detalle adicional. No muestra tarjetas de fuente. | [ ] |
| **RS-03** | Falta de documentación (`sin_evidencia`) | Consulta técnica no cubierta en los manuales. | Mensaje educado indicando que no hay evidencia suficiente en la documentación. No muestra tarjetas de fuente. | [ ] |
| **RS-04** | Fuera de ámbito (`fuera_de_ambito`) | *"¿Qué tiempo hará mañana en Madrid?"* | Respuesta indicando que solo puede atender dudas sobre la documentación técnica del vehículo. | [ ] |
| **RS-05** | Documento obsoleto | Respuesta con cita a un boletín antiguo sustituido. | La tarjeta de fuente (`SourceCard`) muestra una etiqueta visible de aviso (ej. *"Obsoleto / Sustituido"*). | [ ] |
| **RS-06** | Error del asistente / servicio | Backend o Agentes no disponibles (500 o 503). | La burbuja muestra badge de error con el mensaje genérico: *"El asistente no está disponible, inténtalo de nuevo."*. | [ ] |

---

## 5. Gestión de Sesión y Salida de la Aplicación

| ID | Caso de Prueba | Pasos a Ejecutar | Comportamiento Esperado | Estado |
|---|---|---|---|:---:|
| **SS-01** | Cierre de sesión voluntario | Pulsar el botón «Cerrar sesión» en la cabecera. | Se solicita confirmación mediante diálogo. Al aceptar, se borran las credenciales de memoria (`session.clear()`), se cierra la ventana principal y vuelve a abrirse el Login limpio. | [ ] |
| **SS-02** | Bloqueo de logout con petición activa | Enviar una consulta y pulsar inmediatamente «Cerrar sesión» antes de recibir respuesta. | El botón se encuentra deshabilitado mientras haya hilos de trabajo (`_worker`) en ejecución, evitando estados corruptos. | [ ] |
| **SS-03** | Caducidad de sesión (HTTP 401) | Con la sesión abierta, invalidar el token o simular 401 en una llamada. | Se muestra un mensaje emergente: *"Tu sesión ha caducado. Cierra sesión y vuelve a entrar."* y la aplicación redirige automáticamente a la pantalla de Login. | [ ] |
| **SS-04** | Aislamiento entre usuarios | Iniciar sesión como `usuario1`, crear un chat, cerrar sesión y entrar como `usuario2`. | `usuario2` no ve ninguna conversación de `usuario1` en su historial. | [ ] |
