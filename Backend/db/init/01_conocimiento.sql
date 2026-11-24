-- Esquema único de la base de datos de Backend (PostgreSQL + pgvector, embeddings bge-m3 de 1024 dimensiones).
-- PostgreSQL ejecuta este script al crear el contenedor (docker-entrypoint-initdb.d).
-- Es idempotente: se puede volver a aplicar sobre una base ya creada (psql -f) sin perder datos.
--   1. Esquema «conocimiento»: índice versionado, documentos, chunks y catálogos
--      (diseño «Base de datos del backend», ARSOFT-DIS, 2026-10-16, §4; CTR-002).
--   2. Esquema «aplicacion»: usuarios (CTR-005), chats y mensajes (CTR-006) y registro de consultas (CTR-003).

-- =====================================================================================================
-- 1. Esquema «conocimiento»
-- =====================================================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS conocimiento;

CREATE TABLE IF NOT EXISTS conocimiento.indice_version (
    version            TEXT PRIMARY KEY,
    modelo_embeddings  TEXT NOT NULL,
    dimensiones        INTEGER NOT NULL,
    prefijo_passage    TEXT NOT NULL DEFAULT '',
    tokenizador        TEXT,
    n_chunks           INTEGER NOT NULL DEFAULT 0,
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now(),
    activo             BOOLEAN NOT NULL DEFAULT false
);
-- Solo una versión activa: la que atiende las búsquedas
CREATE UNIQUE INDEX IF NOT EXISTS indice_version_una_activa
    ON conocimiento.indice_version (activo) WHERE activo;

CREATE TABLE IF NOT EXISTS conocimiento.documento (
    doc_id              TEXT PRIMARY KEY,          -- HTM240-PRC-003@2.0
    codigo              TEXT NOT NULL,             -- HTM240-PRC-003
    tipo_documento      TEXT NOT NULL,
    titulo              TEXT NOT NULL,
    version_documento   TEXT NOT NULL,
    fecha_revision      DATE,
    obsoleto            BOOLEAN NOT NULL,
    sustituido_por      TEXT,
    versiones_vehiculo  TEXT[] NOT NULL,
    vigente_para        TEXT[] NOT NULL DEFAULT '{}'
);

-- La clave es (indice_version, chunk_id): el chunk_id es estable entre versiones del índice y
-- la versión anterior se conserva mientras se carga la nueva.
CREATE TABLE IF NOT EXISTS conocimiento.chunk (
    indice_version     TEXT NOT NULL REFERENCES conocimiento.indice_version (version) ON DELETE CASCADE,
    chunk_id           TEXT NOT NULL,
    doc_id             TEXT NOT NULL REFERENCES conocimiento.documento (doc_id),
    documento          TEXT NOT NULL,
    texto              TEXT NOT NULL,
    seccion            TEXT NOT NULL,
    pagina             INTEGER NOT NULL,
    orden_en_seccion   INTEGER NOT NULL,
    versiones          TEXT[] NOT NULL,
    componente         TEXT NOT NULL,
    tipo_documento     TEXT NOT NULL,
    obsoleto           BOOLEAN NOT NULL,
    sustituido_por     TEXT,
    vigente_para       TEXT[] NOT NULL DEFAULT '{}',
    fecha_revision     DATE,
    version_documento  TEXT NOT NULL,
    afectado_por       TEXT[] NOT NULL DEFAULT '{}',
    ids_referenciados  TEXT[] NOT NULL DEFAULT '{}',
    embedding          vector(1024) NOT NULL,
    PRIMARY KEY (indice_version, chunk_id)
);
-- Búsqueda vectorial exacta (sin índice aproximado) con el volumen previsto; ver §6.1 del diseño
CREATE INDEX IF NOT EXISTS chunk_vecinos ON conocimiento.chunk (indice_version, doc_id, seccion, orden_en_seccion);
CREATE INDEX IF NOT EXISTS chunk_versiones ON conocimiento.chunk USING gin (versiones);
CREATE INDEX IF NOT EXISTS chunk_ids_referenciados ON conocimiento.chunk USING gin (ids_referenciados);

CREATE TABLE IF NOT EXISTS conocimiento.catalogo (
    nombre     TEXT NOT NULL,                      -- codigos | terminos | vehiculos | componentes
    version    TEXT NOT NULL REFERENCES conocimiento.indice_version (version) ON DELETE CASCADE,
    contenido  JSONB NOT NULL,
    activo     BOOLEAN NOT NULL DEFAULT false,
    creado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (nombre, version)
);

-- =====================================================================================================
-- 2. Esquema «aplicacion»: no depende del esquema «conocimiento» ni de pgvector.
-- Los usuarios de prueba no se crean aquí: ver Backend/readme.md (python -m app.usuarios_prueba).
-- =====================================================================================================

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
-- CTR-001 · POST /valoracion busca la respuesta por usuario y trace_id.
CREATE INDEX IF NOT EXISTS registro_por_trace ON aplicacion.registro_consulta (usuario_id, trace_id);

-- CTR-001 · Valoración de la utilidad de una respuesta. Una por usuario y respuesta (trace_id): valorar
-- de nuevo la misma respuesta actualiza la fila. No hay clave foránea a registro_consulta porque su
-- trace_id no es único; la pertenencia se comprueba contra el registro al guardar.
CREATE TABLE IF NOT EXISTS aplicacion.valoracion (
    id              BIGSERIAL   PRIMARY KEY,
    trace_id        TEXT        NOT NULL CHECK (trace_id <> ''),
    usuario_id      BIGINT      NOT NULL REFERENCES aplicacion.usuario (id) ON DELETE CASCADE,
    util            BOOLEAN     NOT NULL,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (usuario_id, trace_id)
);
