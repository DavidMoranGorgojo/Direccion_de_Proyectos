-- Esquema «conocimiento» del diseño «Base de datos del backend» (ARSOFT-DIS, 2026-10-16, §4).
-- PostgreSQL ejecuta este script al inicializar por primera vez el directorio de datos.
-- El esquema «aplicacion» (usuarios, chats, mensajes y registros) va en otro script.

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
