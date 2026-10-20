-- 1. Habilitar la extensión de pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Tabla para almacenar los fragmentos del corpus RAG
CREATE TABLE IF NOT EXISTS fragmentos_rag (
    id SERIAL PRIMARY KEY,
    documento_id VARCHAR(50) NOT NULL,          -- Ej: HTM240-MNT-001
    num_pagina INT NOT NULL,                     -- Número de página
    seccion VARCHAR(255),                        -- Sección o título
    contenido TEXT NOT NULL,                     -- Texto limpio del fragmento
    embedding vector(384),                      -- Embedding de 384 dimensiones
    metadata JSONB,                              -- Metadatos (versión, estado, aplicabilidad, prioridad)
    ids_referenciados TEXT[],                    -- Referencias cruzadas
    fecha_carga TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Índice para búsqueda semántica/vectorial usando HNSW
CREATE INDEX IF NOT EXISTS idx_fragmentos_embedding 
ON fragmentos_rag 
USING hnsw (embedding vector_cosine_ops);

-- 4. Índice JSONB para filtrado rápido por metadatos (ej. filtro por versión o documento)
CREATE INDEX IF NOT EXISTS idx_fragmentos_metadata 
ON fragmentos_rag USING gin (metadata);