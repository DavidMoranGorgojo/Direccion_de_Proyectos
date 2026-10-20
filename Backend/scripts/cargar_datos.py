import json
import os
import psycopg2
from psycopg2.extras import execute_values

# Configuración de conexión (tomará las variables del entorno o valores por defecto del Docker)
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "thermodrive_rag")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")


def conectar_db():
    """Establece conexión con la base de datos PostgreSQL."""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def cargar_jsonl_a_postgres(ruta_jsonl):
    """Lee un archivo JSONL e inserta los fragmentos en la tabla fragmentos_rag."""
    if not os.path.exists(ruta_jsonl):
        print(f"Error: El archivo {ruta_jsonl} no existe.")
        return

    conn = conectar_db()
    cursor = conn.cursor()

    query = """
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

            # Extraer campos con valores por defecto por seguridad
            doc_id = item.get("documento_id")
            num_pag = item.get("num_pagina", 1)
            seccion = item.get("seccion", "")
            contenido = item.get("contenido", "")
            embedding = item.get("embedding", [])  # Lista de 384 flotantes
            metadata = json.dumps(item.get("metadata", {}))
            ids_ref = item.get("ids_referenciados", [])

            registros.append(
                (doc_id, num_pag, seccion, contenido, embedding, metadata, ids_ref)
            )

    try:
        # Inserción en lote para mayor eficiencia
        for reg in registros:
            cursor.execute(query, reg)

        conn.commit()
        print(
            f"✅ Carga completada con éxito. Se insertaron {len(registros)} registros."
        )

    except Exception as e:
        conn.rollback()
        print(f"❌ Error durante la carga de datos: {e}")

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    # Archivo de prueba asignado por defecto
    archivo_entrada = "datos_ingesta.jsonl"
    print(f"Iniciando proceso de carga desde: {archivo_entrada}")
    cargar_jsonl_a_postgres(archivo_entrada)