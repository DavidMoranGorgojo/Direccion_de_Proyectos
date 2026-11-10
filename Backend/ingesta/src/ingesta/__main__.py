"""Ingesta a demanda: PDF → fragmentos JSONL con metadatos y embeddings → pgvector.

    python -m ingesta --entrada data/manuales --salida salida_ingesta [--cargar]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import catalogos, config, metadatos
from .embeddings import Embebedor
from .inventario import inventariar, leer_documento
from .troceado import Troceador
from .validacion import validar

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _chunks(doc, fragmentos) -> list:
    resultado = []
    for f in fragmentos:
        ids = metadatos.ids_referenciados(f.texto, doc.codigo)
        resultado.append({
            "chunk_id": metadatos.chunk_id(doc.doc_id, f.seccion, f.orden_en_seccion, f.texto),
            "doc_id": doc.doc_id,
            "documento": doc.codigo,
            "version_documento": doc.version_documento,
            "fecha_revision": doc.fecha_revision,
            "obsoleto": doc.obsoleto,
            "sustituido_por": doc.sustituido_por,
            "versiones": doc.versiones_vehiculo,
            "vigente_para": doc.vigente_para,
            "tipo_documento": doc.tipo_documento,
            "componente": metadatos.componente(f.seccion, f.texto),
            "seccion": f.seccion,
            "pagina": f.pagina,
            "orden_en_seccion": f.orden_en_seccion,
            "afectado_por": metadatos.afectado_por(doc.doc_id, doc.codigo, f.seccion, ids),
            "ids_referenciados": ids,
            "texto": f.texto,
        })
    return resultado


def _escribir_jsonl(ruta: Path, filas: list) -> None:
    with open(ruta, "w", encoding="utf-8") as fichero:
        for fila in filas:
            fichero.write(json.dumps(fila, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingesta", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entrada", type=Path, default=Path(os.getenv("INGESTA_ENTRADA", "data/manuales")),
                        help="Carpeta con los PDF (se recorre recursivamente).")
    parser.add_argument("--salida", type=Path, default=Path(os.getenv("INGESTA_SALIDA", "salida_ingesta")),
                        help="Carpeta donde se escriben chunks.jsonl, documentos.jsonl, catalogos/ e informe.")
    parser.add_argument("--indice-version", default=None,
                        help="Nombre de la versión del índice (por defecto, fecha y hora UTC).")
    parser.add_argument("--sin-embeddings", action="store_true",
                        help="Genera fragmentos y metadatos sin calcular vectores (muestra rápida para Agentes).")
    parser.add_argument("--cargar", action="store_true", help="Carga el resultado en PostgreSQL + pgvector.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="Por defecto, $DATABASE_URL.")
    parser.add_argument("--crear-esquema", action="store_true", help="Aplica db/init/01_conocimiento.sql antes de cargar.")
    parser.add_argument("--no-activar", action="store_true", help="Carga la versión sin activarla.")
    args = parser.parse_args(argv)

    if args.cargar and args.sin_embeddings:
        parser.error("--cargar necesita embeddings")
    if args.cargar and not args.database_url:
        parser.error("--cargar necesita --database-url o la variable DATABASE_URL")
    if not args.entrada.is_dir():
        parser.error(f"No existe la carpeta de entrada {args.entrada}")

    inicio = time.time()
    version = args.indice_version or datetime.now(timezone.utc).strftime("v%Y%m%d-%H%M%S")
    embebedor = Embebedor()
    troceador = Troceador(embebedor.contar_tokens)

    pdfs, excluidos = inventariar(args.entrada)
    print(f"[*] {len(pdfs)} documentos a procesar, {len(excluidos)} excluidos.")
    documentos, chunks, informe_docs, rechazados_doc = [], [], [], []
    for ruta in pdfs:
        try:
            doc = leer_documento(ruta)
            fragmentos = troceador.trocear(doc)
        except Exception as error:  # PDF ilegible: se anota y se sigue con los demás
            rechazados_doc.append({"archivo": ruta.name, "motivo": f"{type(error).__name__}: {error}"})
            print(f"[ERROR] {ruta.name}: {error}")
            continue
        documentos.append(doc)
        chunks_doc = _chunks(doc, fragmentos)
        chunks.extend(chunks_doc)
        informe_docs.append({"doc_id": doc.doc_id, "archivo": ruta.name, "obsoleto": doc.obsoleto,
                             "fragmentos": len(chunks_doc), "avisos": doc.avisos})
        print(f"[OK] {doc.doc_id:22} {len(chunks_doc):3d} fragmentos{'  (sustituido)' if doc.obsoleto else ''}")

    validos, rechazados, errores = validar(chunks, embebedor.contar_tokens)
    if errores:
        for error in errores:
            print(f"[ERROR] {error}")
        return 1

    if not args.sin_embeddings:
        print(f"[*] Calculando embeddings {config.MODELO_EMBEDDINGS} (prefijo {config.PREFIJO_PASSAGE!r}) "
              f"para {len(validos)} fragmentos...")
        try:
            vectores = embebedor.vectorizar([c["texto"] for c in validos])
        except Exception as error:
            print(f"[ERROR] Fallo al calcular embeddings, se aborta sin cargar: {error}")
            return 1
        for chunk, vector in zip(validos, vectores):
            chunk["embedding"] = vector

    cats = catalogos.generar(documentos, version)
    args.salida.mkdir(parents=True, exist_ok=True)
    (args.salida / "catalogos").mkdir(exist_ok=True)
    _escribir_jsonl(args.salida / "chunks.jsonl", validos)
    _escribir_jsonl(args.salida / "documentos.jsonl", [d.fila() for d in documentos])
    for nombre, cat in cats.items():
        (args.salida / "catalogos" / f"{nombre}.json").write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")

    carga = None
    if args.cargar:
        from .carga import cargar
        print(f"[*] Cargando la versión {version} en pgvector...")
        try:
            carga = cargar(args.database_url, version, [d.fila() for d in documentos], validos, cats,
                           tokenizador=config.MODELO_EMBEDDINGS, activar=not args.no_activar, esquema=args.crear_esquema)
        except Exception as error:  # BD no disponible o validación fallida: la versión activa no cambia
            print(f"[ERROR] Carga abortada, la versión activa del índice no cambia: {error}")
            return 1

    informe = {
        "indice_version": version,
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duracion_s": round(time.time() - inicio, 1),
        "modelo_embeddings": config.MODELO_EMBEDDINGS,
        "dimensiones": config.DIMENSIONES,
        "prefijo_passage": config.PREFIJO_PASSAGE,
        "max_tokens": config.MAX_TOKENS,
        "con_embeddings": not args.sin_embeddings,
        "documentos_procesados": len(documentos),
        "fragmentos": len(validos),
        "documentos": informe_docs,
        "excluidos": excluidos,
        "documentos_rechazados": rechazados_doc,
        "fragmentos_rechazados": rechazados,
        "catalogos": {nombre: len(cat["contenido"]) for nombre, cat in cats.items()},
        "carga": carga,
    }
    (args.salida / "informe_ingesta.json").write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {len(validos)} fragmentos de {len(documentos)} documentos en {args.salida} "
          f"({len(rechazados)} rechazados, {len(excluidos)} excluidos, {informe['duracion_s']} s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
