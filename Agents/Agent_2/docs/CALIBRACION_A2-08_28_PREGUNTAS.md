# Calibración A2-08 con las 20 preguntas de control y las 8 trampa

Fecha: 24-11-2026 · Responsable: Álvaro Miguel · Rama: `alvaro-agent2-cierre` (sobre `agent_2`)

## Qué se mide

Para cada umbral de la rejilla 0,00–1,00 (paso 0,05), sobre el ranking del
reranker **sin umbral** de cada pregunta:

- **Recall@1/3/5 y MRR** en las preguntas de control: si el documento esperado
  queda entre los conservados y en qué posición.
- **Abstención correcta**: preguntas trampa en las que no se conserva nada.
- **Abstención falsa**: preguntas de control en las que no se conserva nada.

La batería oficial da el *documento* esperado, no los fragmentos, así que la
evaluación es **por documento**: cada documento puntúa con su mejor fragmento.

## Cómo se reproduce

```powershell
# Máquina con modelos y Backend real: el resultado que vale para fijar el umbral
python Agents/Agent_2/scripts/calibrar_umbrales_28.py --backend real --reranker real

# Sin modelos (esta ejecución): valida el flujo, no fija el umbral
python Agents/Agent_2/scripts/calibrar_umbrales_28.py --backend simulado --reranker solapamiento
```

Salida en `docs/resultados/calibracion_28_<backend>_<reranker>.json` (rankings,
trazas, métricas por umbral y por pregunta) y `.md` (tabla).

Piezas: batería en `fixtures/preguntas_control_trampa.json` (copiada del script
de Jaime, `agente1-jaime`), conversión a datos de calibración en
`src/evaluation/dataset_calibracion.py`, métricas en `src/evaluation/calibration.py`
y `metrics.py`, y el ranking sin umbral sale de la traza opcional del pipeline
(`trace_retrieval=True` → `metricas.rankings.reranker`).

## Resultado de esta ejecución (Backend simulado + reranker sustituto)

**No sirve para fijar el umbral**: el reranker es un sustituto por solapamiento
de palabras (el BGE reranker v2-m3 no está en esta máquina). Valida que el flujo
completo funciona y ya deja ver problemas que no dependen del reranker.

Tabla completa en `docs/resultados/calibracion_28_simulado_solapamiento.md`.
Extracto:

| Umbral | Recall@1 | Recall@3 | MRR | Abst. correcta (trampa) | Abst. falsa (control) |
|---:|---:|---:|---:|---:|---:|
| 0.00 | 0.588 | 0.647 | 0.623 | 1/8 | 0/17 |
| 0.45 (actual) | 0.588 | 0.647 | 0.608 | 3/8 | 2/17 |
| 0.50 | 0.588 | 0.647 | 0.608 | 4/8 | 3/17 |
| 0.70 | 0.353 | 0.353 | 0.353 | 7/8 | 10/17 |

## Hallazgos que no dependen del reranker

1. **Tres preguntas de control no pueden acertarse con el dataset actual.**
   CTRL-08 (`HTM240-PRC-001`), CTRL-11 (`HTM240-PRC-008`) y CTRL-12
   (`HTM240-PRC-009`) piden documentos que no están entre los 98 fragmentos.
   Se excluyen de la calibración. Es un problema del dataset (Alba y Marco), no del
   Agente 2.
2. **Cinco documentos esperados no llegan al reranker**: CTRL-03, CTRL-06,
   CTRL-13, CTRL-18 y CTRL-20 no tienen el documento esperado en el ranking ni
   con umbral 0. Ningún umbral lo arregla: el fallo está antes (búsqueda,
   filtros inferidos o fusión). Con el embedding simulado la parte vectorial no
   aporta, así que hay que repetirlo con el Backend real antes de sacar
   conclusiones.
3. **El benchmark de Jaime con las 28 no usó reranker** (`reranker_model=None`,
   `threshold=0.0` en `scripts/evaluar_28_preguntas_a1_a2.py`): sus resultados
   miden RRF, no el umbral.

## Pendiente

- Ejecutar el modo `--backend real --reranker real` en una máquina con modelos
  (Víctor o Jaime) y fijar el umbral final con esa tabla (A2-05).
- Revisar con Alba y Marco los tres documentos ausentes del dataset.
