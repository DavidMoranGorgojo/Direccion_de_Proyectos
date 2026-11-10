# Direccion_de_Proyectos
Repositorio para organizar todo el codigo del proyecto.

## Para conectar con Backend y Agentes

Lista de aspectos técnicos a confirmar con las **personas 1 (Agentes)** y **2 (Backend)** para la integración definitiva entre Frontend, Backend y Agentes:

1. **Rutas (Endpoints HTTP)**:
   - **Consulta al asistente (CTR-001)**: Confirmar la ruta final expuesta por el Backend hacia el Frontend para procesar las consultas técnicas (definida provisionalmente como `CONSULTA_PATH = "/agentes/consulta"`).
   - **Historial de conversaciones (CTR-006)**: Confirmar la ruta definitiva de consulta del historial (definida provisionalmente como `HISTORIAL_PATH = "/chats"`), así como la disponibilidad de operaciones adicionales (borrado de conversaciones, edición de títulos).
   - **Autenticación (CTR-005)**: Confirmar la ruta final del servicio de login (actualmente `POST /auth/login`), y si se implementarán rutas adicionales (cierre de sesión, comprobación de estado de autenticación o refresco de token).

2. **Identificador de la conversación (`conversacion_id`)**:
   - **Origen y generación**: Confirmar quién es responsable de generar el `conversacion_id` para una conversación nueva: si el Frontend genera un identificador único (UUID v4) y lo envía en el cuerpo de la primera consulta, o si el Backend/Agentes lo asigna en la primera respuesta o mediante un endpoint específico de creación de conversación (`POST /chats`).
   - **Persistencia y contexto multiturno**: Confirmar cómo gestionan Agentes y Backend la memoria contextual de la conversación a través del `conversacion_id` a lo largo de turnos sucesivos y su vinculación con el usuario activo.

3. **Mecanismo de sesión**:
   - **Mecanismo de autenticación**: Confirmar el método de autenticación acordado (Bearer token en cabecera `Authorization: Bearer <token>`, cookies de sesión HTTP-only, etc.).
   - **Gestión de caducidad**: Confirmar la expiración del token/sesión, el formato de respuesta ante sesión caducada o permisos insuficientes (códigos HTTP 401 / 403) y el procedimiento de reautenticación o refresco de credenciales.
