-- Esquema «aplicacion»: usuarios (CTR-005), chats y mensajes (CTR-006) y registro de consultas (CTR-003).
-- PostgreSQL ejecuta este script al crear el contenedor (docker-entrypoint-initdb.d), después de
-- 01_conocimiento.sql. No depende del esquema «conocimiento» ni de pgvector.
-- Los usuarios de prueba no se crean aquí: ver Backend/readme.md (python -m app.usuarios_prueba).

CREATE SCHEMA IF NOT EXISTS aplicacion;

-- CTR-005 · Usuarios
CREATE TABLE IF NOT EXISTS aplicacion.usuario (
    id              BIGSERIAL PRIMARY KEY,
    nombre_usuario  TEXT        NOT NULL UNIQUE CHECK (nombre_usuario = lower(nombre_usuario) AND nombre_usuario <> ''),
    nombre          TEXT        NOT NULL,
    password_hash   TEXT        NOT NULL,              -- bcrypt; la contraseña nunca se guarda
    rol             TEXT        NOT NULL DEFAULT 'usuario' CHECK (rol IN ('usuario', 'admin')),
    activo          BOOLEAN     NOT NULL DEFAULT true,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultimo_login    TIMESTAMPTZ
);

-- CTR-006 · Chats. La clave es el conversacion_id de CTR-001, que genera Backend en la primera pregunta.
CREATE TABLE IF NOT EXISTS aplicacion.chat (
    conversacion_id TEXT        PRIMARY KEY CHECK (conversacion_id <> '' AND length(conversacion_id) <= 128),
    usuario_id      BIGINT      NOT NULL REFERENCES aplicacion.usuario (id) ON DELETE CASCADE,
    titulo          TEXT        NOT NULL DEFAULT 'Nuevo chat',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chat_usuario_reciente ON aplicacion.chat (usuario_id, updated_at DESC);

-- CTR-006 · Mensajes. Una pregunta y su respuesta comparten trace_id.
CREATE TABLE IF NOT EXISTS aplicacion.mensaje (
    orden           BIGSERIAL   PRIMARY KEY,           -- orden estable dentro del chat
    message_id      TEXT        NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    conversacion_id TEXT        NOT NULL REFERENCES aplicacion.chat (conversacion_id) ON DELETE CASCADE,
    trace_id        TEXT        NOT NULL DEFAULT '',
    role            TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
    contenido       TEXT        NOT NULL,
    estado          TEXT        NOT NULL DEFAULT '',   -- estado CTR-001 de la respuesta
    codigo_error    TEXT        NOT NULL DEFAULT '',
    fuentes         JSONB       NOT NULL DEFAULT '[]', -- [{chunk_id, documento, seccion, pagina, versiones, obsoleto}]
    "timestamp"     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mensaje_por_chat ON aplicacion.mensaje (conversacion_id, orden);

-- CTR-003 · Registro de consultas. Se conserva aunque se borre el chat o el usuario.
CREATE TABLE IF NOT EXISTS aplicacion.registro_consulta (
    id              BIGSERIAL   PRIMARY KEY,
    trace_id        TEXT        NOT NULL DEFAULT '',
    usuario_id      BIGINT      REFERENCES aplicacion.usuario (id) ON DELETE SET NULL,
    conversacion_id TEXT,
    tipo            TEXT        NOT NULL DEFAULT 'consulta' CHECK (tipo IN ('consulta', 'vectorial', 'lexica')),
    pregunta        TEXT        NOT NULL,
    estado          TEXT        NOT NULL,              -- estado CTR-001 (respuesta, aclaracion, error…)
    codigo_error    TEXT        NOT NULL DEFAULT '',
    num_fuentes     INTEGER     NOT NULL DEFAULT 0,
    chunk_ids       TEXT[]      NOT NULL DEFAULT '{}',
    latencia_ms     DOUBLE PRECISION,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS registro_por_fecha ON aplicacion.registro_consulta (creado_en DESC);
CREATE INDEX IF NOT EXISTS registro_por_usuario ON aplicacion.registro_consulta (usuario_id, creado_en DESC);

-- Valoración de utilidad de una respuesta (CTR-003 §5.3: la gestiona Backend y se une al registro por trace_id).
-- Una por turno y usuario: si el usuario vuelve a valorar, se sobrescribe. Se conserva aunque se borre el chat.
CREATE TABLE IF NOT EXISTS aplicacion.valoracion (
    trace_id        TEXT        NOT NULL CHECK (trace_id <> '' AND length(trace_id) <= 128),
    usuario_id      BIGINT      NOT NULL REFERENCES aplicacion.usuario (id) ON DELETE CASCADE,
    util            BOOLEAN     NOT NULL,
    comentario      TEXT        CHECK (length(comentario) <= 1000),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (trace_id, usuario_id)
);
CREATE INDEX IF NOT EXISTS valoracion_por_fecha ON aplicacion.valoracion (actualizado_en DESC);
