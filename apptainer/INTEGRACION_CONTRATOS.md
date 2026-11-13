# Enlaces HTTP y notas para los contratos de ARSOFT

La referencia es CTR-001 1.2 y CTR-005/006 1.1 del 21 de octubre de 2026. Para CTR-002 se tomó el contenido del adjunto, cuya cabecera y pie muestran ediciones distintas. Conviene corregir esa discrepancia al publicar la siguiente versión.

## Enlaces implementados

| Tramo | Qué conecta |
| --- | --- |
| PySide6 → Backend | Usa `POST /consulta`. La primera pregunta lleva `conversacion_id` vacío. El cliente reutiliza el ID que devuelve Backend y conserva el texto exacto. |
| Backend → Agentes | La pasarela CTR-001 reenvía el ID y la pregunta a `POST /agentes/consulta`. Valida la forma de la respuesta, añade el ID de conversación y convierte una caída o un timeout de Agentes en HTTP 200 con error estructurado. |
| API de Agentes → Agente 1 | El adaptador reutiliza `consultar_asistente` y el simulador de Agente 2 existente. Expone consulta, comprobación del modelo configurado y cierre explícito de la memoria del chat. |
| Backend → PostgreSQL | `/ready` comprueba la conexión a PostgreSQL y al servicio de Agentes. La parte disponible de CTR-002 expone la ficha del índice activo, los fragmentos y vecinos y los catálogos ya almacenados. Las lecturas están protegidas con credenciales de servicio. |

## Añadidos y aclaraciones para los contratos

- **CTR-001, 002 y 003. Autenticación interna.** Especificar un Bearer de servicio para ambas direcciones. Los scripts aceptan `ARSOFT_SERVICE_TOKEN` fuera de Git. El enlace debe circular por loopback, un túnel autorizado o TLS. Para producción conviene acordar credenciales separadas y rotación.
- **CTR-001. Fuentes incompletas.** La implementación acepta página 0 y campos de documento o sección vacíos para conservar la respuesta emitida por Agente 1. El contrato vigente exige página positiva y fuentes completas. Acordar si la respuesta debe conservarse con esos metadatos incompletos, marcarse sin fuentes o tratarse como error de verificación.
- **CTR-001. Timeout y contexto.** Backend usa un único cliente HTTP con timeout de 25 segundos. Si vence, solicita a Agentes el borrado de la memoria del chat. Si el turno sigue trabajando, Agentes marca la sesión para descartar su estado al terminar. Así una aclaración que el usuario no recibió no se aplica a la pregunta siguiente. Definir en el contrato esta cancelación lógica y la respuesta `tiempo_agotado`.
- **CTR-001 y CTR-005. Autorización.** Sin credencial devuelve 401; mientras el repositorio carezca de un verificador de sesiones, una petición con Bearer recibe 503. Antes de habilitar el flujo conectado hay que validar sesión y propiedad de la conversación, y conectar la generación del ID con el historial.
- **CTR-001. Identificadores y errores.** Backend genera el `trace_id` si Agentes no emite respuesta. Agente 1 conserva códigos de modelo no disponible, recuperación no disponible y verificación; errores de Agente 2 sin código explícito se clasifican como `error_verificacion`. Las rutas 404 y 405 usan el formato estructurado de error. Conviene fijar los códigos y los cuerpos de error en CTR-001.
- **Operación de Agentes.** La auditoría se escribe en `ARSOFT_AUDIT_PATH`, dentro del directorio persistente montado en `/models/state`. Las sesiones se purgan cada minuto tras 30 minutos de inactividad, con un máximo de 1024. Acordar retención y comportamiento al alcanzar el límite.
- **CTR-002. Respuestas de lectura.** La ficha incluye versión, modelo, tokenizador, dimensiones y número de fragmentos. El detalle devuelve `{indice, chunk, vecinos}`; el catálogo devuelve `{nombre, version, contenido}`. Una versión activa ausente devuelve 503; un fragmento o catálogo ausente dentro de la versión activa devuelve 404. Conviene fijar esos cuerpos en el contrato.

## Implementaciones que aún no tienen un enlace activo

Login y verificación de sesiones de CTR-005, historial de CTR-006, valoración y registro de CTR-003, y búsqueda vectorial, BM25 y recuperación real CTR-002/004. El adaptador conserva el simulador existente para Agente 2. La ingesta sigue cargando el índice por su flujo administrativo actual. Si se acuerda que Backend debe recibir los artefactos, hace falta definir el formato y el mecanismo de importación.
