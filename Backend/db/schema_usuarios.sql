-- Tablas de login, historial y registro de consultas (Álvaro).
-- PROPUESTA para incluir en el esquema unificado de Roberto y Daniel.
-- No tocan las tablas de documentos/fragmentos ni el vector(1024).

CREATE TABLE IF NOT EXISTS usuarios (
    id             SERIAL PRIMARY KEY,
    username       VARCHAR(64)  NOT NULL UNIQUE,
    nombre         VARCHAR(128) NOT NULL,
    password_hash  VARCHAR(128) NOT NULL,          -- bcrypt
    rol            VARCHAR(16)  NOT NULL DEFAULT 'usuario' CHECK (rol IN ('usuario', 'admin')),
    activo         BOOLEAN      NOT NULL DEFAULT TRUE,
    creado_en      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    ultimo_login   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS chats (
    id              SERIAL PRIMARY KEY,
    usuario_id      INTEGER      NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    titulo          VARCHAR(200) NOT NULL DEFAULT 'Nuevo chat',
    creado_en       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    actualizado_en  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_chats_usuario ON chats (usuario_id, actualizado_en DESC);

CREATE TABLE IF NOT EXISTS mensajes (
    id         SERIAL PRIMARY KEY,
    chat_id    INTEGER     NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    rol        VARCHAR(16) NOT NULL CHECK (rol IN ('usuario', 'asistente')),
    contenido  TEXT        NOT NULL,
    fuentes    JSONB,                       -- documentos/fragmentos citados en la respuesta
    creado_en  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_mensajes_chat ON mensajes (chat_id, id);

CREATE TABLE IF NOT EXISTS registro_consultas (
    id              SERIAL PRIMARY KEY,
    usuario_id      INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    chat_id         INTEGER REFERENCES chats(id)    ON DELETE SET NULL,
    consulta        TEXT        NOT NULL,
    tipo_busqueda   VARCHAR(16) NOT NULL CHECK (tipo_busqueda IN ('vectorial', 'bm25', 'agentes', 'otro')),
    num_resultados  INTEGER     NOT NULL DEFAULT 0,
    resultados      JSONB,                  -- ids de fragmentos devueltos
    latencia_ms     DOUBLE PRECISION,
    estado          VARCHAR(16) NOT NULL DEFAULT 'ok' CHECK (estado IN ('ok', 'error')),
    error           TEXT,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_consultas_usuario ON registro_consultas (usuario_id, creado_en DESC);
CREATE INDEX IF NOT EXISTS ix_consultas_fecha   ON registro_consultas (creado_en DESC);
