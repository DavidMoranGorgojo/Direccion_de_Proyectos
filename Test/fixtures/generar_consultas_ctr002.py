"""Genera Test/fixtures/ctr002_consultas_bge_m3.json para las pruebas de simetría de CTR-002 (§6).

Toma frases literales de varios chunks del índice real y calcula su vector de consulta con
BAAI/bge-m3 y el prefijo «query: », como hace el Agente 2. Se ejecuta con la imagen de la ingesta,
que ya trae el modelo, desde la raíz del repo y con el Backend arrancado:

    apptainer exec --cleanenv \\
        --bind "$HOME/arsoft-state/cache/huggingface:/cache/huggingface" \\
        --env HF_HOME=/cache/huggingface \\
        "$HOME/arsoft-images/ingesta.sif" python Test/fixtures/generar_consultas_ctr002.py

Hay que volver a generarlo si cambia el texto de esos chunks (nueva ingesta con otro dataset).
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from Test.test_Backend.test_contrato_ctr002_real import TOKEN, llamar  # noqa: E402

# Búsquedas léxicas de las que se toma el primer chunk; cubren documentos de tipos distintos.
BUSQUEDAS = ["HTM-0142", "purgado circuito térmico motor", "nivel de refrigerante vaso de expansión",
             "electroventilador PWM", "comunicación CAN TCU", "testigo temperatura"]
DESTINO = Path(__file__).resolve().parent / "ctr002_consultas_bge_m3.json"


def frase_literal(texto: str) -> str:
    """Fragmento literal largo del chunk (hasta 400 caracteres desde la primera línea con contenido).
    Una frase corta puede repetirse casi igual en otro documento (p. ej. DIA-001 y DTC-001) y entonces
    no tiene un único chunk correcto; un fragmento largo identifica al suyo."""
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    inicio = next((i for i, l in enumerate(lineas) if len(l) >= 40), 0)
    return " ".join(lineas[inicio:])[:400]


def main() -> int:
    if not TOKEN:
        print("Falta ARSOFT_SERVICE_TOKEN", file=sys.stderr)
        return 1
    from sentence_transformers import SentenceTransformer

    modelo = SentenceTransformer(os.getenv("MODELO_EMBEDDINGS", "BAAI/bge-m3"))
    casos, vistos = [], set()
    for busqueda in BUSQUEDAS:
        estado, cuerpo = llamar("POST", "/conocimiento/lexica", {"texto": busqueda, "k": 1})
        if estado != 200 or not cuerpo["resultados"]:
            print(f"[--] «{busqueda}»: sin resultado ({estado})")
            continue
        chunk = cuerpo["resultados"][0]
        if chunk["chunk_id"] in vistos:
            continue
        vistos.add(chunk["chunk_id"])
        consulta = frase_literal(chunk["texto"])
        vector = modelo.encode("query: " + consulta, normalize_embeddings=True).tolist()
        casos.append({"consulta": consulta, "chunk_id": chunk["chunk_id"], "documento": chunk["documento"],
                      "inicio_texto": chunk["texto"][:60], "vector": [round(v, 6) for v in vector]})
        print(f"[OK] {chunk['documento']:16} «{consulta[:60]}…»")
    DESTINO.write_text(json.dumps(casos, ensure_ascii=False), encoding="utf-8")
    print(f"{len(casos)} consultas en {DESTINO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
