# Enlaces HTTP y notas para los contratos de ARSOFT

La referencia es CTR-001 1.2 y CTR-005/006 1.1 del 21 de octubre de 2026. Para CTR-002 se tomó el contenido del adjunto, cuya cabecera y pie muestran ediciones distintas. Conviene corregir esa discrepancia al publicar la siguiente versión.

## Enlaces implementados

| Tramo | Qué conecta |
| --- | --- |
| PySide6 → Backend | Usa `POST /consulta`. La primera pregunta lleva `conversacion_id` vacío. El cliente reutiliza el ID que devuelve Backend y conserva el texto exacto. |
| Backend → Agentes | La pasarela CTR-001 reenvía el ID y la pregunta a `POST /agentes/consulta`. Valida la forma de la respuesta, añade el ID de conversación y convierte una caída o un timeout de Agentes en HTTP 200 con `servicio_no_disponible`. |
| API de Agentes → Agente 1 | El adaptador reutiliza `consultar_asistente` y el simulador de Agente 2 ya existente. Expone consulta, comprobación del modelo configurado y cierre explícito de la memoria del chat. |
| Backend → PostgreSQL | `/ready` comprueba la conexión a PostgreSQL y al servicio de Agentes. La parte disponible de CTR-002 expone la ficha del índice activo, los fragmentos y vecinos y los catálogos ya almacenados. Las lecturas están protegidas con credenciales de servicio. |

## Añadidos y aclaraciones para el contrato

- **CTR-001, 002 y 003. Autenticación interna.** Especificar un Bearer de servicio para ambas direcciones. Los scripts aceptan `ARSOFT_SERVICE_TOKEN` fuera de Git. El enlace debe circular por loopback, un túnel autorizado o TLS. Para producción conviene acordar credenciales separadas y rotación.
- **CTR-001. Fallos locales.** Cuando Agentes no emite respuesta, la pasarela genera el `trace_id` del error. Conviene explicitarlo. El generador actual de Agente 1 usa un sufijo corto para sus propios IDs. Antes de persistir registros, conviene sustituirlo por un identificador con suficiente entropía.
- **CTR-001 y CTR-005. Autorización previa a consultar.** La ruta queda protegida. Sin credencial devuelve 401; mientras el repositorio carezca de un verificador de sesiones, una petición con Bearer recibe 503. Antes de habilitarla hay que validar sesión y propiedad de la conversación, y conectar la generación del ID con el historial. Aclarar que los fallos de autenticación y los errores de formato HTTP quedan fuera de la respuesta 200 de la consulta válida.
- **CTR-001. Salud y cierre de sesión de Agentes.** `/agentes/salud` comprueba el modelo configurado y declara `recuperacion: mock`. El DELETE es idempotente para conversaciones sin turno en curso. El adaptador descarta memorias inactivas al recibir tráfico. Sigue pendiente que Backend programe el cierre de acuerdo con el historial.
- **CTR-002. Respuestas de lectura.** La ficha incluye versión, modelo, tokenizador, dimensiones y número de fragmentos. El detalle devuelve `{indice, chunk, vecinos}`; el catálogo devuelve `{nombre, version, contenido}`. Una versión activa ausente devuelve 503; un fragmento o catálogo ausente dentro de la versión activa devuelve 404. Conviene fijar esos cuerpos en el contrato.

## Implementaciones que aún no tienen un enlace activo

Login y verificación de sesiones de CTR-005, historial de CTR-006, valoración y registro de CTR-003, y búsqueda vectorial, BM25 y recuperación real CTR-002/004. El adaptador conserva el simulador existente para Agente 2. La ingesta sigue cargando el índice por su flujo administrativo actual. Si se acuerda que Backend debe recibir los artefactos, hace falta definir el formato y el mecanismo de importación.
