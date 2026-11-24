# Ingesta de la documentación (backend-ingesta)

Convierte los PDF de ARSOFT (ThermoDrive HTM-240) en fragmentos con metadatos y embeddings y los carga en PostgreSQL + pgvector como una nueva versión del índice. Implementa el diseño «Ingesta de la documentación» (ARSOFT-DIS, 2026-10-16) y los metadatos de ARSOFT-CTR-002 ed. 0.4.

## Proceso

| Paso | Módulo | Qué hace |
|---|---|---|
| 5.1 Inventario | `inventario.py` | Lista los PDF, excluye el compilado y lee código, versión, fecha, vigencia y versiones de vehículo de la cabecera de cada uno. |
| 5.2–5.3 Extracción y limpieza | `extraccion.py` | Texto por página con PyMuPDF. Quita la cabecera repetida, el aviso de documentación sintética y los números de página. Une palabras partidas sin romper códigos (`HTM240-BOL-002`, `CMP-18`). Reconstruye las tablas fila a fila (`Intervalo: … \| Elemento: … \| Procedimiento: …`). |
| 5.4 Metadatos y relaciones | `metadatos.py`, `config.py` | `ids_referenciados`, `componente`, `afectado_por` (boletines), sustituciones y `vigente_para`. |
| 5.5 Troceado | `troceado.py` | Estructural por tipo, máximo 500 tokens del tokenizador de bge-m3. |
| 5.6 Embeddings | `embeddings.py` | `BAAI/bge-m3`, 1024 dimensiones, normalizados, con el prefijo `passage: ` (CTR-002 §5.2). |
| 5.7 Validación | `validacion.py` | Metadatos obligatorios, trazabilidad, tamaño, dimensión, duplicados y compilado ausente. |
| 5.8 Carga | `carga.py` | Nueva versión en `conocimiento.*`, validación de recuentos y activación. La anterior se conserva. |
| 6 Catálogos | `catalogos.py` | `codigos` (DTC-001), `terminos` (DIC-001), `componentes` (CAT-001) y `vehiculos`. |

Reglas de troceado:

| Tipo | Unidad |
|---|---|
| BOL y documentos sustituidos | Documento completo |
| PRC | Procedimiento completo si cabe; si no: preparación, pasos (cada grupo repite título, riesgos, EPI y condiciones previas) y cierre |
| DTC | Un código de avería |
| CAT | Una ficha de componente |
| HIS | Un caso de servicio |
| DIA | Una rama del árbol (4.1, 4.2…) |
| Resto (MAN, OPE, MNT, ADV, SEG, ESQ, DIC) | Una sección; si supera el máximo, por párrafos o filas repitiendo el encabezado |

## Ejecución local

```bash
cd Backend/ingesta
pip install -r requirements.txt

# Solo fragmentos y metadatos, sin vectores (muestra rápida para Agentes)
PYTHONPATH=src python -m ingesta --entrada /ruta/ThermoDrive_HTM240_Alumnos_PDF --salida salida_ingesta --sin-embeddings

# Completa, con carga en pgvector
export DATABASE_URL=postgresql://usuario:clave@localhost:5432/bd
PYTHONPATH=src python -m ingesta --entrada /ruta/ThermoDrive_HTM240_Alumnos_PDF --salida salida_ingesta --cargar --crear-esquema
```

`--crear-esquema` aplica `Backend/db/init/01_conocimiento.sql` (no hace falta si la base de datos ya lo ejecutó al arrancar). Otras opciones: `--indice-version v1.0`, `--no-activar`, `--incluir-sustituidos`. Por defecto los documentos sustituidos (`MNT-001 v1.0` y `PRC-003 v1.0`) no se indexan y aparecen en `excluidos` del informe. La versión activa nunca se recarga: para reindexar se usa una versión nueva.

## Ejecución con Apptainer

La [guía de Apptainer](../../apptainer/README.md) describe el arranque de PostgreSQL + pgvector y la ingesta. Para una carga puntual, usa ARSOFT_MANUALES_DIR con el script apptainer/run-ingesta.sh cuando la instancia arsoft-db esté en ejecución. Si lanzas la ingesta desde Python en el host, configura DATABASE_URL hacia una base PostgreSQL de pruebas con pgvector.

## Salidas

En la carpeta `--salida`:

- `chunks.jsonl`: un fragmento por línea con los campos de `conocimiento.chunk` y su `embedding`.
- `documentos.jsonl`: una fila por documento (`conocimiento.documento`).
- `catalogos/{codigos,terminos,vehiculos,componentes}.json`.
- `informe_ingesta.json`: documentos procesados, fragmentos por documento, excluidos y rechazados con su motivo, avisos, versión del índice y duración.

```json
{
  "chunk_id": "HTM240-PRC-003@2.0_pasos_01_3c87bc4a",
  "doc_id": "HTM240-PRC-003@2.0",
  "documento": "HTM240-PRC-003",
  "version_documento": "2.0",
  "fecha_revision": "2025-09-15",
  "obsoleto": false,
  "sustituido_por": null,
  "versiones": ["V1.1", "V2.0"],
  "vigente_para": [],
  "tipo_documento": "procedimiento",
  "componente": null,
  "seccion": "Pasos",
  "pagina": 1,
  "orden_en_seccion": 1,
  "afectado_por": ["BOL-002"],
  "ids_referenciados": ["BOL-002", "CMP-02", "CMP-18", "CMP-24", "CMP-25", "PRC-011"],
  "texto": "HTM240-PRC-003 — Verificación de la bomba eléctrica auxiliar A…",
  "embedding": [0.0123, -0.0345, "… 1024 valores"]
}
```

El `chunk_id` depende del documento, la sección, el orden y el contenido: si el texto no cambia, no cambia al reindexar.

## Valores provisionales (puntos abiertos de CTR-002)

Todos están en `config.py` o se cambian por variable de entorno, sin tocar el resto del código:

| Punto | Valor actual | Dónde |
|---|---|---|
| Prefijo de indexación | `passage: ` (CTR-002 §5.2; TEC-001 dice que bge-m3 no lo necesita) | `EMBEDDING_PREFIX` |
| `tipo_documento` de MAN, OPE, PRC, DIA, ADV, SEG, HIS, ESQ y DIC | `manual`, `operacion`, `procedimiento`, `diagnostico`, `testigos`, `seguridad`, `caso_servicio`, `esquema`, `diccionario` | `config.TIPO_DOCUMENTO` |
| `componente` | Código `CMP-xx` de la sección o, si el texto solo cita uno, ese; si no, `null` | `metadatos.componente` |
| `vigente_para` | `PRC-003 v1.0` sigue vigente para V1.0 | `config.VIGENTE_PARA` |
| Documentos sin versión o fecha (BOL, DIC, HIS, CAT, DTC) | Versión `1.0`; `fecha_revision` = `null`. Se anota en el informe | `inventario.py` |
| Tamaño máximo | 500 tokens | `MAX_TOKENS_CHUNK` |

## Pruebas

```bash
cd Backend/ingesta
python -m pytest                                   # unitarias
INGESTA_CORPUS=/ruta/ThermoDrive_HTM240_Alumnos_PDF python -m pytest   # y además sobre el corpus real
```

Las de corpus cubren la tabla 7 del diseño: compilado excluido, sustituidos marcados, metadatos completos, máximo de tokens, procedimientos con su seguridad, HTM-0142 como identificador, tablas fila a fila y reejecución estable. Los PDF no se versionan.
