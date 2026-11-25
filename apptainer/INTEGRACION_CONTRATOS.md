# Integración de contratos ARSOFT

Este documento describe el comportamiento implementado en Backend y Agentes. La referencia consultada es CTR-001 1.2 y CTR-005/006 1.1, de 21 de octubre de 2026. El adjunto de CTR-002 tiene ediciones distintas en cabecera y pie; queda pendiente corregir la referencia editorial al publicar la siguiente versión.

## Recorrido de una consulta

| Tramo | Contrato implementado |
| --- | --- |
| Navegador o PySide6 → Backend | La interfaz web del reto se sirve en `/`; la interfaz de escritorio existente también sigue disponible. Ambas inician sesión en `POST /auth/login`, envían el JWT de usuario y consultan `POST /consulta`. |
| Backend → Agentes | Backend reenvía `conversacion_id` y `pregunta` a `POST /agentes/consulta` con el Bearer de servicio. Valida la respuesta, exige citas completas cuando `estado=respuesta`, añade el ID de conversación y transforma fallos y timeout a errores CTR-001. |
| Agentes → Agente 1 y Agente 2 | Agentes reutiliza el flujo de Agente 1. En el despliegue de `apptainer/start-all.sh` se fija `USE_REAL_AGENT2=1`; el simulador queda disponible para desarrollo local. Agentes expone consulta, salud y cierre de memoria. |
| Backend → PostgreSQL | Backend consulta el índice y los catálogos; `/ready` revisa PostgreSQL y Agentes. Las rutas de conocimiento y las comunicaciones internas requieren el Bearer de servicio. |

## Bearer y sesiones

- Las rutas de usuario (`/consulta`, `/valoracion`, `/chats` y `/auth/me`) requieren `Authorization: Bearer <JWT>`, obtenido en `POST /auth/login`. Un JWT de usuario no autoriza llamadas internas.
- Backend → Agentes, el acceso CTR-007 al historial desde Agentes y las rutas `/conocimiento` usan `Authorization: Bearer <ARSOFT_SERVICE_TOKEN>`. Backend y Agentes deben tener el mismo secreto no vacío. Se compara el valor completo mediante comparación constante; token incorrecto devuelve 401 y token no configurado devuelve 503. En `/conocimiento` los errores mantienen la forma CTR-002 `{"codigo", "mensaje"}`; en Agentes FastAPI envuelve el detalle en `{"detail": {"codigo", "mensaje"}}`.
- El secreto se configura fuera del repositorio en los ficheros de entorno de Apptainer. `start-all.sh` comprueba que coincida en Backend y Agentes. El token solo debe circular por loopback, túnel autorizado o TLS; producción debe acordar rotación y secretos separados.
- Un JWT ausente, manipulado o caducado devuelve 401 `sesion_caducada`. Una sesión válida de usuario desactivado devuelve 403 `acceso_denegado`. Backend reserva el chat para su usuario antes de reenviar la petición; un chat de otra persona devuelve 404 `conversacion_no_encontrada` sin llamar a Agentes.

## Fuentes, página 0 y respuestas verificadas

CTR-001 solo admite una respuesta (`estado: "respuesta"`) con texto no vacío y al menos una fuente con `chunk_id`, documento y sección no vacíos y página entera mayor o igual que 1. Se rechazan también `DOC_DESCONOCIDO` y `Documento sin nombre`. Página 0 significa que la paginación no consta y no es una referencia verificable.

Agentes rechaza evidencias incompletas antes de redactar. Si la respuesta de Agentes no cumple la forma o contiene fuentes incompletas, Backend no entrega el texto como respuesta: devuelve HTTP 200 con `estado: "error"`, `codigo_error: "error_verificacion"` y sin fuentes. El cliente de escritorio, el navegador y el lector del historial aplican la misma salvaguarda si reciben una respuesta positiva sin citas completas. Los estados `aclaracion`, `sin_evidencia`, `fuera_de_ambito` y `error` no llevan fuentes.

La interfaz muestra documento, sección, página, versiones y aviso de documento sustituido. Los mensajes se insertan como texto, no como HTML generado por el modelo.

## Timeout y memoria conversacional

Backend da hasta 25 segundos a la llamada HTTP de Agentes. Si vence, solicita `DELETE /agentes/conversaciones/{conversacion_id}` y responde HTTP 200 con `estado: "error"`, `codigo_error: "tiempo_agotado"`, texto genérico y fuentes vacías. Si el turno sigue ejecutándose, Agentes marca la sesión para descartar su estado al terminar; una aclaración que el usuario no recibió no contamina el siguiente turno.

El timeout no cancela necesariamente el trabajo de modelo que ya está ejecutándose; evita que su resultado tardío pase a ser memoria reutilizable. Si la conexión a Agentes falla por una razón distinta, Backend usa `servicio_no_disponible`.

## Respuesta y códigos de error CTR-001

`POST /consulta` recibe `{"conversacion_id": "", "pregunta": "..."}`. Una respuesta (incluidos errores internos de Agentes) tiene HTTP 200 y la forma:

```json
{
  "trace_id": "…",
  "estado": "respuesta | aclaracion | sin_evidencia | fuera_de_ambito | error",
  "texto": "…",
  "fuentes": [],
  "codigo_error": "",
  "conversacion_id": "…"
}
```

Los códigos internos admitidos en `codigo_error` son `entrada_invalida`, `modelo_no_disponible`, `modelo_incompatible`, `indice_no_disponible`, `tiempo_agotado`, `error_verificacion` y `servicio_no_disponible`. Los alias heredados `peticion_invalida` y `filtro_invalido` se normalizan a `entrada_invalida` en la frontera de Agentes. `codigo_error` solo se rellena con `estado: "error"`.

Los errores HTTP del propio Backend usan `{"codigo_error": "…", "mensaje": "…"}`. Para `/consulta`: 401 `sesion_caducada`, 403 `acceso_denegado`, 404 `conversacion_no_encontrada`, 422 `entrada_invalida`, 429 `demasiadas_consultas` (incluye `Retry-After`) y 500 `error_interno`. La indisponibilidad de PostgreSQL al reservar el chat se devuelve como HTTP 200 `servicio_no_disponible`, de acuerdo con el contrato de respuesta CTR-001.

## Conocimiento CTR-002

Las respuestas de lectura existentes son:

- `GET /conocimiento/info`: versión activa, modelo de embeddings, tokenizador, dimensión, número de chunks y tokenizador léxico.
- `GET /conocimiento/chunks/{chunk_id}?vecinos=0|1`: `{"indice": {"version"}, "chunk": {...}, "vecinos": [...]}`.
- `GET /catalogos/{nombre}`: `{"nombre", "version", "contenido"}` para `codigos`, `terminos`, `vehiculos` o `componentes`.
- `POST /conocimiento/vectorial`: búsqueda vectorial con filtros estrictos y orden por similitud; el vector y la dimensión deben corresponder al índice activo.

Los errores CTR-002 usan `{"codigo", "mensaje", ...}`: 400 `peticion_invalida` (puede incluir `errores`), 400 `filtro_invalido` (incluye campo y valores válidos), 401 `acceso_denegado`, 404 `recurso_no_encontrado`, 409 `modelo_incompatible` y 503 `indice_no_disponible` o `servicio_no_disponible`. Una búsqueda válida sin coincidencias responde 200 con `resultados: []`; no relaja los filtros.

## Operación de Agentes y límites conocidos

- La auditoría JSONL se escribe en `ARSOFT_AUDIT_PATH`; en Apptainer apunta al volumen persistente `/models/state/agente1_registros.jsonl`. No hay política de retención o rotación configurada: antes de una operación prolongada debe fijarla el responsable del despliegue.
- Las sesiones en memoria vencen tras 30 minutos sin actividad y se purgan cada minuto. El máximo es 1024: al llegar al límite se expulsa la sesión inactiva más antigua; si todas están ocupadas, Agentes devuelve 503 y Backend informa `servicio_no_disponible`.
- El valor por defecto del proceso Python (`USE_REAL_AGENT2=0`) habilita el simulador local. El arranque integrado con `apptainer/start-all.sh` fuerza `USE_REAL_AGENT2=1` y la comprobación `/ready` verifica el modo y la disponibilidad del pipeline real. No se debe presentar el modo simulado como prueba de recuperación real.

## Estado de rutas

Las rutas de login, consulta, chats e historial, valoración, registro y conocimiento están montadas. La interfaz web mínima se sirve desde el mismo Backend en `/`; el cliente PySide6 existente no se elimina.

La única discrepancia documental abierta es editorial: confirmar qué edición de CTR-002 es la normativa porque el adjunto presenta dos números de edición. Los requisitos funcionales aplicables se han implementado según el contenido disponible. La retención de auditoría también queda como decisión de operación, sin cambiarla hasta que exista una política acordada.
