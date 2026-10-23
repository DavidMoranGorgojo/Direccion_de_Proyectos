-- 1. Habilitar la extensión de pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Tabla para almacenar los fragmentos del corpus RAG
CREATE TABLE IF NOT EXISTS fragmentos_rag (
    id SERIAL PRIMARY KEY,
    documento_id VARCHAR(50) NOT NULL,          -- Ej: HTM240-MNT-001
    num_pagina INT NOT NULL,                     -- Número de página
    seccion VARCHAR(255),                        -- Sección o título
    contenido TEXT NOT NULL,                     -- Texto limpio del fragmento
    embedding vector(1024),                     -- Embedding de 1024 dimensiones (BAAI/bge-m3)
    metadata JSONB,                              -- Metadatos adicionales en formato JSON
    ids_referenciados TEXT[]                     -- Array de IDs o referencias cruzadas
);