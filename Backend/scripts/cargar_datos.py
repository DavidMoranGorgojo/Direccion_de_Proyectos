import json
import os
import psycopg2
from psycopg2.extras import execute_values

# Configuración de conexión (ajusta según tus variables de entorno o credenciales)
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "rag_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")

def cargar_jsonl_a_db(ruta_jsonl):
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT
    )
    cursor = conn.cursor()

    sql = """
        INSERT INTO fragmentos_rag (
            documento_id, 
            num_pagina, 
            seccion, 
            contenido, 
            embedding, 
            metadata, 
            ids_referenciados
        ) VALUES (%s, %s, %s, %s, %s, %s, %s);
    """

    registros = []
    with open(ruta_jsonl, "r", encoding="utf-8") as f:
        for linea in f:
            if not linea.strip():
                continue
            item = json.loads(linea)

            # Mapeo compatible con el formato de Ingesta (doc_id, pagina, texto)
            # manteniendo fallback por seguridad
            doc_id = item.get("doc_id") or item.get("documento_id")
            pagina = item.get("pagina") if "pagina" in item else item.get("num_pagina", 0)
            seccion = item.get("seccion", "")
            texto = item.get("texto") or item.get("contenido", "")
            
            embedding = item.get("embedding")
            metadata = json.dumps(item.get("metadata", {}))
            ids_ref = item.get("ids_referenciados", [])

            registros.append((
                doc_id,
                pagina,
                seccion,
                texto,
                embedding,
                metadata,
                ids_ref
            ))

    cursor.executemany(sql, registros)
    conn.commit()

    print(f"Cargados con éxito {len(registros)} registros en fragmentos_rag.")
    cursor.close()
    conn.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cargar_jsonl_a_db(sys.argv[1])
    else:
        print("Uso: python cargar_datos.py <ruta_al_archivo.jsonl>")