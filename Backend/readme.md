# Módulo Backend — Pipeline de Ingesta, Embeddings y Base Vectorial RAG

**Proyecto:** Asistente Conversacional RAG — *ThermoDrive HTM-240*  
**Organización:** ARSOFT / Universidad de León  
**Sub-equipo:** Grupo 2 — Ingesta y Procesamiento del Corpus  
**Responsable de Ingesta y Embeddings (Persona 4):** Daniel Reyna San Lorenzo (`dreyns00@estudiantes.unileon.es` / `Dani`)  

---

## 1. Descripción del Módulo

Este módulo gestiona la ingesta de la documentación técnica del vehículo híbrido genérico *ThermoDrive HTM-240*, su fragmentación semántica estructural (REQ-ING-01), la generación de embeddings multilingües densos con **`BAAI/bge-m3`** (1024 dimensiones) y el almacenamiento indexado en **ChromaDB**.

---

## 2. Esquema de Fragmentación y Metadatos de Trazabilidad

Cada fragmento almacenado en la colección `thermodrive_htm240` garantiza trazabilidad completa y no disocia pasos procedimentales de advertencias de seguridad:

| Campo Metadato | Tipo | Descripción | Ejemplo |
|---|---|---|---|
| `id_fragmento` | `str` | Identificador determinista (hash SHA-256) | `htm240-cat-001_p1_001` |
| `documento` | `str` | Código oficial del manual | `HTM240-CAT-001` |
| `tipo_doc` | `str` | Familia documental (`MAN`, `CAT`, `MNT`, `PRC`, `BOL`) | `CAT` |
| `version_documento` | `str` | Versión identificada | `1.0` |
| `seccion` | `str` | Título de la sección o componente | `Ficha CMP-02` |
| `pagina` | `int` | Número de página física | `1` |
| `estado` | `str` | Vigencia documental (`vigente` o `sustituido`) | `vigente` |
| `sustituido_por` | `str` | Documento que sustituye a este (si aplica) | `HTM240-MNT-001 v1.1` |
| `afectado_por` | `str` | Boletines de servicio que modifican esta pieza | `BOL-006` |
| `ids_referenciados`| `str` | Códigos de componentes/circuitos detectados | `CMP-02, CIR-02` |

---

## 3. Conexión y Consumo desde el Motor RAG

Para que el equipo de RAG (Roberto Cañón / Álvaro Datos) consuma los vectores en los agentes o cadenas LangChain / LlamaIndex:

```python
import chromadb

# 1. Conexión al cliente persistente
client = chromadb.PersistentClient(path="data/vector_db")
collection = client.get_collection("thermodrive_htm240")

# 2. Consulta con filtro de estado (excluyendo versiones sustituidas/obsoletas)
query_embedding = [...] # Embedding generado con BAAI/bge-m3 (1024 dims)
results = collection.query(
    query_embeddings=[query_embedding],
    n_results=5,
    where={"estado": "vigente"}  # CRÍTICO: evita responder con datos obsoletos
)

# 3. Acceso a resultados con trazabilidad
for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
    print(f"[{meta['documento']} | Pág {meta['pagina']} | {meta['seccion']}]:\n{doc}\n")
```

---

## 4. Comandos de Ejecución

- **Ingesta normal (idempotente con 0 duplicados):**
  ```bash
  python scripts/ingesta_persona4.py
  ```
- **Reinicio limpio e indexación desde cero:**
  ```bash
  python scripts/ingesta_persona4.py --reset
  ```
- **Búsqueda semántica de prueba (CLI):**
  ```bash
  python scripts/ingesta_persona4.py --query "¿Qué función tiene la bomba CMP-02?" --k 3
  ```

---

## 5. Auditoría y Control

Las ejecuciones generan automáticamente en `pruebas_procesamiento_datos/registros_persona4/`:
- `registro_ingesta.json`: Control de documentos indexados, cantidad de fragmentos y timestamps.
- `registro_incidencias.json`: Registro de versiones sustituidas y advertencias de metadatos.
