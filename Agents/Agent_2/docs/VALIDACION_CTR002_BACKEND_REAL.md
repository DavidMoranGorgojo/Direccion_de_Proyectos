# Validación del cliente CTR-002 con el Backend real (24-11-2026)

Responsable: Alba. Tareas del reparto del 20-11: validar el cliente de CTR-002 contra el
Backend real, ejecutar con PostgreSQL real el test ingesta → pgvector → Agente 2 con
BGE-M3 real y revisar el dataset de 98 fragmentos con Marco.

## Entorno

- PostgreSQL 16 + pgvector 0.7.4 (conda-forge), local, puerto 5433, base `thermodrive_test`.
- Ingesta real del Backend (`Backend/ingesta`) sobre los 24 PDF de ThermoDrive HTM-240:
  22 documentos indexados, 181 fragmentos, `passage: ` + `BAAI/bge-m3` (1024 dim), ~140 s en CPU.
- API real del Backend (`Backend/api`) servida con uvicorn y Bearer de servicio.
- Agente 2 con `BackendAPIClient` y BGE-M3 real (`FlagEmbedding`), sin reranker (umbral 0 sobre RRF).

## Resultado

`Test/test_Integracion/test_ingesta_bge_pgvector_a2.py`: **14 passed, 1 skipped** (125 s).
Las pruebas unitarias (`Test/test_Models`) siguen en verde: 843 passed, 1 skipped.

| Comprobación | Resultado |
|---|---|
| Ficha `/conocimiento/info` coincide con la ingesta (versión y modelo) | OK |
| `/conocimiento/vectorial` recupera cada fragmento por su texto (top 5, `query:`) | OK |
| `/conocimiento/lexica` + `/conocimiento/chunks/{id}` con vecinos | OK |
| Pipeline A2 → evidencias CTR-004 aceptadas por el Agente 1 | OK |
| Bearer de servicio: sin token o con token incorrecto → 401, error sin filtrar el token | OK |
| Timeout de conexión (Backend caído) → `servicio_no_disponible` rápido | Fallaba; corregido |
| Timeout de lectura → `tiempo_agotado` | OK |
| Prefijo `passage:` del Agente 2 reproduce el vector de la ingesta (coseno > 0,99) | OK |
| `query:` no se duplica y recupera el fragmento | OK |
| Filtros `version`, `componente`, `tipo_documento` en vectorial y léxica | OK |
| Filtro con valor inexistente (`V9.9`) → `entrada_invalida` | OK |
| Relajación §4: solo se quita `tipo_documento`, `componente` se mantiene | OK |
| Vigencia de sustituidos (`vigente_para`) en pgvector | No aplicable: no se indexan (ver abajo) |

Reproducir (PowerShell, entorno con `Backend/ingesta`, `Backend/api` y `Agents/Agent_2` instalados):

```powershell
$env:ARSOFT_TEST_DATABASE_URL="postgresql://postgres@localhost:5433/thermodrive_test"
$env:ARSOFT_TEST_MANUALES="<ruta>\ThermoDrive_HTM240_Alumnos_PDF"
$env:PYTHONPATH=".;shared;Backend/api;Backend/ingesta/src"
python -m pytest Test/test_Integracion -q -rs
```

## Hallazgos

1. **Corregido — timeout de conexión mal clasificado.** `requests.ConnectTimeout` hereda de
   `Timeout`, así que el cliente devolvía `tiempo_agotado` cuando el Backend no aceptaba la
   conexión (en Windows un puerto cerrado agota el timeout en vez de rechazarse). Ahora es
   `servicio_no_disponible` en las cuatro llamadas; `ReadTimeout` sigue siendo `tiempo_agotado`.
   Prueba unitaria en `test_backend_client_robustez.py`.
2. **Para Backend — los sustituidos no se indexan.** La ingesta excluye
   `HTM240-MNT-001 v1.0` y `HTM240-PRC-003 v1.0` («Documento sustituido…: no se indexa»).
   Por tanto `config.VIGENTE_PARA` (`PRC-003@1.0 → V1.0`) nunca llega a pgvector y el Agente 2
   nunca verá un `solo_obsoleto` real. Además `HTM240-PRC-003 v2.0`, al que apunta la sustitución,
   no está entre los PDF: para un vehículo V1.0 no hay ningún PRC-003 en el índice.
   Hay que decidir con Backend si se indexan los sustituidos marcados como obsoletos.
3. **Dataset sintético (98 fragmentos).** El versionado
   (`Agents/Agent_2/fixtures/bbdd_sintetica_chunks.json`) ya está bien: el segundo HTM-0142 es
   `HTM240-DTC-001@1.0_p1_htm0142_v20` y `vigente_para` sigue la regla de la ingesta
   (`["V1.0"]` solo en PRC-003 v1.0, `[]` en el resto). La copia antigua
   `Agents/Agent_2/data/bbdd_sintetica_chunks.jsonl` (ignorada por Git) conserva el ID duplicado
   y no tiene `vigente_para`: no debe usarse. `config.DEFAULT_DATASET_PATH` apuntaba a
   `data/bbdd_sintetica_chunks.json`, que no existe; ahora apunta al de `fixtures/`.
4. **Para Marco — benchmark CJ-02 con chunks esperados que no existen en el dataset.**

   | Pregunta | `chunks_esperados` | Situación |
   |---|---|---|
   | CJ02-006 | `HTM240-DTC-001@1.0_p1_htm0201` | No hay fragmento de HTM-0201 en el dataset |
   | CJ02-027 | `HTM240-DTC-001@1.0_p1_htm0405` | En el dataset es `HTM240-DTC-001@1.0_p4_htm0405` |
   | CJ02-033 | `HTM240-PRC-011@1.0_p1_pasos` | No hay PRC-011 ni en el dataset ni entre los PDF |

5. **Menor — formato de `sustituido_por`.** El dataset usa el código (`HTM240-MNT-001`) y la
   ingesta el `doc_id` (`HTM240-MNT-001@1.1`). El Agente 2 no depende del formato, pero conviene
   unificarlo con CTR-002.
