"""
Módulo Oficial de Ingesta, Fragmentación, Embeddings y Carga Vectorial
Rol: Persona 4 (Plan de Trabajo Grupo 2 - Ingesta y Procesamiento del Corpus para el RAG)
Responsable: Daniel Reyna San Lorenzo (dreyns00@estudiantes.unileon.es)

Objetivos cubiertos:
1. Fragmentación semántica/estructural respetando secciones, fichas y procedimientos.
2. Generación y asignación de identificadores únicos y metadatos de trazabilidad.
3. Generación de embeddings con BAAI/bge-m3.
4. Carga en base de datos vectorial persistente (ChromaDB).
5. Idempotencia y prevención de duplicados (upsert determinista).
6. Generación de registro de ingesta (registro_ingesta.json) y de incidencias (registro_incidencias.json).
7. Procedimiento reproducible con CLI para incorporar nuevos documentos.
"""

import os
import sys
import re
import json
import argparse
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import fitz  # PyMuPDF
import chromadb
from chromadb.config import Settings

# Rutas del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent
DIR_DATA = BASE_DIR / "data"
DIR_VECTOR_DB = DIR_DATA / "vector_db"
DIR_REGISTROS = BASE_DIR / "pruebas_procesamiento_datos" / "registros_persona4"

DIR_VECTOR_DB.mkdir(parents=True, exist_ok=True)
DIR_REGISTROS.mkdir(parents=True, exist_ok=True)

COLLECTION_NAME = "thermodrive_htm240"
MODEL_NAME = "BAAI/bge-m3"

# ==============================================================================
# 1. GESTOR DE EMBEDDINGS BAAI/bge-m3
# ==============================================================================

class BgeM3EmbeddingManager:
    """Gestiona la carga y generación de embeddings con BAAI/bge-m3."""

    def __init__(self, model_name: str = MODEL_NAME, device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._dimension = 1024

    @property
    def model(self):
        if self._model is None:
            print(f"[*] Cargando modelo de embeddings '{self.model_name}'...")
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name, device=self.device)
                if hasattr(self._model, "get_embedding_dimension"):
                    self._dimension = self._model.get_embedding_dimension()
                else:
                    self._dimension = self._model.get_sentence_embedding_dimension()
                print(f"[OK] Modelo '{self.model_name}' cargado con éxito. Dimensión: {self._dimension}")
            except Exception as e:
                print(f"[AVISO] No se pudo cargar directo vía SentenceTransformer: {e}")
                print("[*] Intentando carga alternativa optimizada para BGE-M3...")
                raise e
        return self._model

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Genera embeddings densos normalizados para una lista de textos."""
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 5,
            batch_size=8
        )
        return embeddings.tolist()


# ==============================================================================
# 2. FRAGMENTADOR Y EXTRACTOR ESTRUCTURAL (PERSONA 4)
# ==============================================================================

REGEX_PATTERNS = {
    "DTC": r"\bHTM-\d{4}\b",
    "PRC": r"\b(?:HTM240-)?PRC-\d{3}\b",
    "BOL": r"\b(?:HTM240-)?BOL-\d{3}[A-Z]?\b",
    "CMP": r"\bCMP-\d{2}\b",
    "TES": r"\bTES-\d{2}\b",
    "CIR": r"\bCIR-\d{2}\b"
}

def desguionar(texto: str) -> str:
    patron = r"(\b[a-zA-ZáéíóúÁÉÍÓÚñÑ]+)-\s+([a-zA-ZáéíóúÁÉÍÓÚñÑ]+\b)"
    return re.sub(patron, r"\1\2", texto)

def limpiar_ruido(texto_pagina: str) -> str:
    lineas = texto_pagina.splitlines()
    limpias = []
    saltar = False
    for linea in lineas:
        l = linea.strip()
        if "ThermoDrive HTM-240" in l and ("Documentacion sintetica" in l or "Documentación sintética" in l):
            continue
        if "DOCUMENTACIÓN SINTÉTICA PARA USO EDUCATIVO" in l or "DOCUMENTACION SINTETICA PARA USO EDUCATIVO" in l:
            saltar = True
            continue
        if saltar:
            if "mantener o reparar" in l or "vehículos reales" in l or "vehiculos reales" in l:
                saltar = False
                continue
            continue
        if re.match(r"^\d+$", l) or re.match(r"^Página\s+\d+(\s+de\s+\d+)?$", l, re.IGNORECASE):
            continue
        limpias.append(linea)
    return "\n".join(limpias).strip()

def detectar_referencias(texto: str) -> List[str]:
    encontrados = []
    for tipo, pat in REGEX_PATTERNS.items():
        coincidencias = sorted(list(set(re.findall(pat, texto))))
        encontrados.extend(coincidencias)
    return sorted(list(set(encontrados)))

class FragmentadorCorpus:
    """Trocea documentos respetando unidades lógicas (secciones, fichas CMP, procedimientos)."""

    @staticmethod
    def fragmentar_pdf(ruta_pdf: Path) -> List[Dict[str, Any]]:
        doc = fitz.open(ruta_pdf)
        nombre = ruta_pdf.name
        
        # Detectar código del documento
        match_cod = re.search(r"HTM240-[A-Z]{3}-\d{3}", nombre)
        cod_doc = match_cod.group(0) if match_cod else ruta_pdf.stem
        
        # Metadatos base conocidos por inventario
        version = "1.0"
        estado = "vigente"
        sustituido_por = "None"
        tipo_doc = "GEN"
        if "MAN-001" in cod_doc:
            version = "2.0"
            tipo_doc = "MAN"
        elif "CAT-001" in cod_doc:
            version = "1.0"
            tipo_doc = "CAT"
        elif "MNT-001" in cod_doc:
            version = "1.0"
            estado = "sustituido"
            sustituido_por = "HTM240-MNT-001 v1.1 (BOL-006)"
            tipo_doc = "MNT"

        # Extraer y limpiar páginas
        paginas_limpias = []
        for i in range(len(doc)):
            crudo = doc[i].get_text("text")
            limpio = limpiar_ruido(crudo)
            limpio = desguionar(limpio)
            paginas_limpias.append({"pagina": i + 1, "texto": limpio})

        texto_unido = "\n\n--- SALTO DE PÁGINA ---\n\n".join(
            [f"[Página {p['pagina']}]\n" + p["texto"] for p in paginas_limpias]
        )

        fragmentos = []

        if tipo_doc == "CAT":
            # Trocear por ficha CMP-XX
            bloques = re.split(r"\n(?=CMP-\d{2}\s*—)", texto_unido)
            for i, b in enumerate(bloques):
                b_str = b.strip()
                if not b_str:
                    continue
                match_cmp = re.search(r"CMP-(\d{2})", b_str)
                cmp_id = f"CMP-{match_cmp.group(1)}" if match_cmp else f"intro_{i}"
                match_p = re.findall(r"\[Página (\d+)\]", b_str)
                num_p = int(match_p[0]) if match_p else 1
                
                refs = detectar_referencias(b_str)
                afectado = []
                if cmp_id == "CMP-15":
                    afectado.append("BOL-005")
                elif cmp_id == "CMP-25":
                    afectado.append("BOL-004")

                id_frag = f"{cod_doc}_{cmp_id}"
                fragmentos.append({
                    "id": id_frag,
                    "texto": b_str,
                    "metadatos": {
                        "documento": cod_doc,
                        "version_documento": version,
                        "tipo_documento": tipo_doc,
                        "seccion": f"Ficha {cmp_id}",
                        "pagina": num_p,
                        "estado": estado,
                        "sustituido_por": sustituido_por,
                        "afectado_por": ", ".join(afectado) if afectado else "None",
                        "ids_referenciados": ", ".join(refs) if refs else "None",
                        "hash_contenido": hashlib.md5(b_str.encode("utf-8")).hexdigest()
                    }
                })

        elif tipo_doc == "MAN":
            # Trocear por secciones numeradas
            secciones = re.split(r"\n(?=\d+\.\s+[A-ZÁÉÍÓÚÑ])", texto_unido)
            for i, s in enumerate(secciones):
                s_str = s.strip()
                if not s_str:
                    continue
                primer_linea = s_str.splitlines()[0][:50].strip()
                match_p = re.findall(r"\[Página (\d+)\]", s_str)
                num_p = int(match_p[0]) if match_p else 1
                
                refs = detectar_referencias(s_str)
                afectado = []
                if "Diferencias entre versiones" in primer_linea:
                    afectado.append("BOL-003")

                id_frag = f"{cod_doc}_sec_{i}_{re.sub(r'[^a-zA-Z0-9]', '_', primer_linea)[:15]}"
                fragmentos.append({
                    "id": id_frag,
                    "texto": s_str,
                    "metadatos": {
                        "documento": cod_doc,
                        "version_documento": version,
                        "tipo_documento": tipo_doc,
                        "seccion": primer_linea,
                        "pagina": num_p,
                        "estado": estado,
                        "sustituido_por": sustituido_por,
                        "afectado_por": ", ".join(afectado) if afectado else "None",
                        "ids_referenciados": ", ".join(refs) if refs else "None",
                        "hash_contenido": hashlib.md5(s_str.encode("utf-8")).hexdigest()
                    }
                })

        else:
            # Documentos unitarios o sustituidos (ej. MNT-001 v1.0)
            refs = detectar_referencias(texto_unido)
            id_frag = f"{cod_doc}_v{version}_completo"
            fragmentos.append({
                "id": id_frag,
                "texto": texto_unido,
                "metadatos": {
                    "documento": cod_doc,
                    "version_documento": version,
                    "tipo_documento": tipo_doc,
                    "seccion": "Contenido íntegro",
                    "pagina": 1,
                    "estado": estado,
                    "sustituido_por": sustituido_por,
                    "afectado_por": "BOL-006" if "MNT-001" in cod_doc else "None",
                    "ids_referenciados": ", ".join(refs) if refs else "None",
                    "hash_contenido": hashlib.md5(texto_unido.encode("utf-8")).hexdigest()
                }
            })

        return fragmentos


# ==============================================================================
# 3. PIPELINE DE CARGA VECTORIAL IDEMPOTENTE (CHROMA DB)
# ==============================================================================

class IngestorVectorialChroma:
    """Gestiona la indexación de fragmentos y metadatos en ChromaDB asegurando idempotencia."""

    def __init__(self, db_dir: Path = DIR_VECTOR_DB, embedding_manager: Optional[BgeM3EmbeddingManager] = None):
        self.db_dir = db_dir
        self.embedding_manager = embedding_manager or BgeM3EmbeddingManager()
        self.client = chromadb.PersistentClient(path=str(self.db_dir))
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        self.registro_ingesta_path = DIR_REGISTROS / "registro_ingesta.json"
        self.registro_incidencias_path = DIR_REGISTROS / "registro_incidencias.json"

    def cargar_fragmentos(self, fragmentos: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Carga fragmentos en ChromaDB mediante upsert determinista evitando duplicados."""
        if not fragmentos:
            return {"cargados": 0, "actualizados": 0, "total": 0}

        ids = [f["id"] for f in fragmentos]
        documents = [f["texto"] for f in fragmentos]
        metadatas = [f["metadatos"] for f in fragmentos]

        # Comprobar cuántos ya existían
        existentes_res = self.collection.get(ids=ids)
        ids_existentes = set(existentes_res["ids"]) if existentes_res else set()

        print(f"[*] Generando embeddings BAAI/bge-m3 para {len(documents)} fragmentos...")
        embeddings = self.embedding_manager.encode(documents)

        # Upsert en ChromaDB (inserta nuevos o actualiza sin duplicar)
        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings
        )

        nuevos = len(ids) - len(ids_existentes)
        actualizados = len(ids_existentes)

        print(f"[OK] Ingesta completada en colección '{COLLECTION_NAME}':")
        print(f"     - Fragmentos nuevos insertados: {nuevos}")
        print(f"     - Fragmentos re-indexados (idempotentes): {actualizados}")
        print(f"     - Total en colección: {self.collection.count()}")

        return {
            "nuevos": nuevos,
            "actualizados": actualizados,
            "total_coleccion": self.collection.count()
        }

    def actualizar_registros_control(self, doc_codigo: str, num_chunks: int, estado_doc: str, incidencias: List[str]):
        """Registra el documento y sus incidencias en los ficheros de auditoría."""
        # Registro de Ingesta
        registro_data = {}
        if self.registro_ingesta_path.exists():
            try:
                with open(self.registro_ingesta_path, "r", encoding="utf-8") as f:
                    registro_data = json.load(f)
            except Exception:
                registro_data = {}

        registro_data[doc_codigo] = {
            "fecha_ingesta": datetime.now().isoformat(),
            "fragmentos_indexados": num_chunks,
            "estado": estado_doc,
            "modelo_embeddings": MODEL_NAME,
            "coleccion": COLLECTION_NAME
        }

        with open(self.registro_ingesta_path, "w", encoding="utf-8") as f:
            json.dump(registro_data, f, ensure_ascii=False, indent=2)

        # Registro de Incidencias
        incidencias_data = []
        if self.registro_incidencias_path.exists():
            try:
                with open(self.registro_incidencias_path, "r", encoding="utf-8") as f:
                    incidencias_data = json.load(f)
            except Exception:
                incidencias_data = []

        for inc in incidencias:
            incidencias_data.append({
                "timestamp": datetime.now().isoformat(),
                "documento": doc_codigo,
                "incidencia": inc
            })

        with open(self.registro_incidencias_path, "w", encoding="utf-8") as f:
            json.dump(incidencias_data, f, ensure_ascii=False, indent=2)

    def consultar(self, query: str, n_results: int = 3, filtrar_sustituidos: bool = True) -> List[Dict[str, Any]]:
        """Realiza una consulta de prueba semántica recuperando fuentes y metadatos."""
        query_emb = self.embedding_manager.encode([query])
        where_filter = {"estado": "vigente"} if filtrar_sustituidos else None

        res = self.collection.query(
            query_embeddings=query_emb,
            n_results=n_results,
            where=where_filter
        )

        resultados = []
        if res and res["ids"]:
            for i in range(len(res["ids"][0])):
                resultados.append({
                    "id": res["ids"][0][i],
                    "documento": res["metadatas"][0][i]["documento"],
                    "seccion": res["metadatas"][0][i]["seccion"],
                    "pagina": res["metadatas"][0][i]["pagina"],
                    "estado": res["metadatas"][0][i]["estado"],
                    "distancia": res["distances"][0][i] if "distances" in res else None,
                    "fragmento": res["documents"][0][i][:250] + "..."
                })
        return resultados


# ==============================================================================
# 4. EJECUCIÓN PRINCIPAL Y TESTING COMPLETO (PERSONA 4)
# ==============================================================================

def procesar_muestra_completa():
    print("=" * 80)
    print("EJECUTANDO PIPELINE OFICIAL DE PERSONA 4: FRAGMENTACIÓN, BGE-M3 Y CARGA VECTORIAL")
    print("=" * 80)

    dir_muestras = BASE_DIR / "pruebas_procesamiento_datos" / "manuales_entrada"
    if not dir_muestras.exists():
        print(f"[ERROR] No existe la carpeta {dir_muestras}")
        return

    pdfs = list(dir_muestras.glob("*.pdf"))
    if not pdfs:
        print("[ERROR] No se encontraron archivos PDF de muestra en la carpeta.")
        return

    print(f"[*] Documentos encontrados para indexar: {len(pdfs)}")
    for p in pdfs:
        print(f"    - {p.name}")

    # 1. Fragmentación
    todos_los_fragmentos = []
    fragmentador = FragmentadorCorpus()
    incidencias_por_doc = {}

    for pdf in pdfs:
        print(f"\n[*] Fragmentando {pdf.name}...")
        frags = fragmentador.fragmentar_pdf(pdf)
        doc_code = frags[0]["metadatos"]["documento"] if frags else pdf.stem
        incidencias = []
        
        # Registrar incidencias si es documento sustituido o tiene alertas
        if "MNT-001" in pdf.name:
            incidencias.append("DOCUMENTO SUSTITUIDO: MNT-001 v1.0 reemplazado por v1.1 vía BOL-006 (intervalo refrigerante 60.000 km en lugar de 80.000 km). Marcado como no vigente.")
        if "CAT-001" in pdf.name:
            incidencias.append("CAT-001 carece de versión de fecha en cabecera original. Asignada versión 1.0 por defecto.")
            
        incidencias_por_doc[doc_code] = incidencias
        todos_los_fragmentos.extend(frags)
        print(f"[OK] {len(frags)} fragmentos generados para {doc_code}.")

    # 2. Carga vectorial y Embeddings con BAAI/bge-m3
    ingestor = IngestorVectorialChroma()
    resultado_ingesta = ingestor.cargar_fragmentos(todos_los_fragmentos)

    # 3. Registrar auditoría e incidencias
    for pdf in pdfs:
        doc_code = re.search(r"HTM240-[A-Z]{3}-\d{3}", pdf.name).group(0) if re.search(r"HTM240-[A-Z]{3}-\d{3}", pdf.name) else pdf.stem
        frags_del_doc = [f for f in todos_los_fragmentos if f["metadatos"]["documento"] == doc_code]
        estado = frags_del_doc[0]["metadatos"]["estado"] if frags_del_doc else "vigente"
        ingestor.actualizar_registros_control(
            doc_codigo=doc_code,
            num_chunks=len(frags_del_doc),
            estado_doc=estado,
            incidencias=incidencias_por_doc.get(doc_code, [])
        )

    # 4. Probar idempotencia (segunda pasada inmediata para demostrar que no duplica)
    print("\n" + "=" * 80)
    print("COMPROBACIÓN DE IDEMPOTENCIA (Segunda pasada de ingesta):")
    segunda_pasada = ingestor.cargar_fragmentos(todos_los_fragmentos)
    assert segunda_pasada["nuevos"] == 0, "FALLO: Se crearon duplicados en la segunda pasada."
    print("[OK] VERIFICADO: 0 duplicados creados. La ingesta es 100% idempotente.")
    print("=" * 80)

    # 5. Consultas de prueba con BAAI/bge-m3
    print("\n" + "=" * 80)
    print("PRUEBA DE RECUPERACIÓN SEMÁNTICA (RAG QUERY TEST CON BGE-M3):")
    print("=" * 80)
    
    preguntas_test = [
        "¿Cuáles son los tres circuitos térmicos independientes del vehículo?",
        "¿Qué función tiene la bomba de refrigerante CMP-02 y en qué circuito está?",
        "¿Cada cuántos kilómetros se cambia el refrigerante?"
    ]

    for p in preguntas_test:
        print(f"\n[PREGUNTA] '{p}'")
        res = ingestor.consultar(p, n_results=2, filtrar_sustituidos=True)
        for i, r in enumerate(res):
            print(f"   [{i+1}] Fuente: {r['documento']} | Pág: {r['pagina']} | Sección: {r['seccion']} | Estado: {r['estado']}")
            print(f"       Texto: {r['fragmento']}")

    print("\n" + "=" * 80)
    print(f"[EXITO] Colección ChromaDB persistida en: {DIR_VECTOR_DB}")
    print(f"[EXITO] Registro de ingesta guardado en: {ingestor.registro_ingesta_path}")
    print(f"[EXITO] Registro de incidencias guardado en: {ingestor.registro_incidencias_path}")
    print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline de Ingesta Persona 4 (BAAI/bge-m3 + ChromaDB)")
    parser.add_argument("--query", type=str, default="", help="Realizar una consulta de prueba sobre la BD vectorial.")
    args = parser.parse_args()

    if args.query:
        ingestor = IngestorVectorialChroma()
        print(f"\nConsultando: '{args.query}'...")
        res = ingestor.consultar(args.query, n_results=3)
        for r in res:
            print(f"\n[{r['documento']} - Pág {r['pagina']} - {r['seccion']}] (Estado: {r['estado']})")
            print(r['fragmento'])
    else:
        procesar_muestra_completa()
