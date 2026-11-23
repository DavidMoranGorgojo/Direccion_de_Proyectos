# Direccion_de_Proyectos
Repositorio para organizar todo el codigo del proyecto.

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
