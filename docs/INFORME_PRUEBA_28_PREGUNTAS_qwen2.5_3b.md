# Informe de Pruebas Integradas: 20 Control + 8 Trampa (Agente 1 + Agente 2)

**Fecha:** 2026-11-23 12:45  
**Modelo LLM:** `qwen2.5:3b` (Ollama Local)  
**Dataset:** `bbdd_sintetica_chunks.json` (98 fragmentos)  

## 1. Resumen Ejecutivo

| Bloque | Total | Superadas (OK) | Tasa de Éxito |
| :--- | :---: | :---: | :---: |
| **20 Preguntas de Control** | 20 | **6** | 30.0% |
| **8 Preguntas Trampa (Anti-Alucinación)** | 8 | **3** | 37.5% |
| **Recuperación Documental Agente 2** | 20 | **9** | 45.0% |

## 2. Desglose de las 20 Preguntas de Control

| ID | Doc Esperado | Recuperado por A2 | Estado A1 | Veredicto |
| :--- | :--- | :---: | :--- | :--- |
| CTRL-01 | `HTM240-MAN-001` | ✅ | `aclaracion` | OK (Aclaración versión) |
| CTRL-02 | `HTM240-MAN-001` | ✅ | `aclaracion` | OK (Aclaración versión) |
| CTRL-03 | `HTM240-CAT-001` | ❌ (HTM240-ESQ-001, HTM240-MAN-001) | `aclaracion` | FALLO (A2 no halló doc) |
| CTRL-04 | `HTM240-CAT-001` | ✅ | `error` | FALLO A1 (Redactor/Verificador error) |
| CTRL-05 | `HTM240-MAN-001` | ❌ (HTM240-MNT-001, HTM240-ESQ-001) | `error` | FALLO A2 (No recuperó HTM240-MAN-001) |
| CTRL-06 | `HTM240-MAN-001` | ❌ (Vacío) | `aclaracion` | FALLO (A2 no halló doc) |
| CTRL-07 | `HTM240-MNT-001` | ✅ | `aclaracion` | OK (Aclaración versión) |
| CTRL-08 | `HTM240-PRC-001` | ❌ (Vacío) | `sin_evidencia` | FALLO A2 (No recuperó HTM240-PRC-001) |
| CTRL-09 | `HTM240-BOL-002` | ❌ (Vacío) | `aclaracion` | FALLO (A2 no halló doc) |
| CTRL-10 | `HTM240-DIC-001` | ❌ (HTM240-DTC-001, HTM240-ADV-001) | `aclaracion` | FALLO (A2 no halló doc) |
| CTRL-11 | `HTM240-PRC-008` | ❌ (HTM240-DIC-001) | `error` | FALLO A2 (No recuperó HTM240-PRC-008) |
| CTRL-12 | `HTM240-PRC-009` | ❌ (HTM240-DIA-001) | `error` | FALLO A2 (No recuperó HTM240-PRC-009) |
| CTRL-13 | `HTM240-DTC-001` | ❌ (HTM240-HIS-001) | `aclaracion` | FALLO (A2 no halló doc) |
| CTRL-14 | `HTM240-ADV-001` | ✅ | `aclaracion` | OK (Aclaración versión) |
| CTRL-15 | `HTM240-SEG-001` | ✅ | `aclaracion` | OK (Aclaración versión) |
| CTRL-16 | `HTM240-HIS-001` | ✅ | `aclaracion` | OK (Aclaración versión) |
| CTRL-17 | `HTM240-BOL-003` | ✅ | `error` | FALLO A1 (Redactor/Verificador error) |
| CTRL-18 | `HTM240-MNT-001` | ❌ (HTM240-ESQ-001, HTM240-HIS-001) | `aclaracion` | FALLO (A2 no halló doc) |
| CTRL-19 | `HTM240-BOL-006` | ✅ | `error` | FALLO A1 (Redactor/Verificador error) |
| CTRL-20 | `HTM240-DIA-001` | ❌ (HTM240-PRC-003) | `error` | FALLO A2 (No recuperó HTM240-DIA-001) |

## 3. Desglose de las 8 Preguntas Trampa

| ID | Estado A2 | Estado A1 | Veredicto Anti-Alucinación |
| :--- | :--- | :--- | :--- |
| TRAMP-01 | `None` | `fuera_de_ambito` | OK (Frenada: fuera_de_ambito) |
| TRAMP-02 | `suficiente` | `error` | OK (Bloqueo seguridad A1-07) |
| TRAMP-03 | `ambiguo` | `aclaracion` | FALLO ALUCINACIÓN (aclaracion) |
| TRAMP-04 | `suficiente` | `aclaracion` | FALLO ALUCINACIÓN (aclaracion) |
| TRAMP-05 | `sin_evidencia` | `sin_evidencia` | OK (Frenada: sin_evidencia) |
| TRAMP-06 | `ambiguo` | `aclaracion` | FALLO ALUCINACIÓN (aclaracion) |
| TRAMP-07 | `ambiguo` | `aclaracion` | FALLO ALUCINACIÓN (aclaracion) |
| TRAMP-08 | `ambiguo` | `aclaracion` | FALLO ALUCINACIÓN (aclaracion) |

## 4. Fallos Detectados y Reparto de Correcciones

- **CTRL-03 (FALLO (A2 no halló doc))**: Pregunta: *"¿Qué componente es el CMP-04 y qué permite hacer a la Unidad de Control Térmico (TCU)?"*
  - Docs A2: `['HTM240-ESQ-001', 'HTM240-ESQ-001', 'HTM240-MAN-001']` | Estado A1: `aclaracion`
- **CTRL-04 (FALLO A1 (Redactor/Verificador error))**: Pregunta: *"¿A qué temperatura inicial debe abrir el termostato electrónico (CMP-08)?"*
  - Docs A2: `['HTM240-CAT-001', 'HTM240-DTC-001', 'HTM240-ESQ-001']` | Estado A1: `error`
- **CTRL-05 (FALLO A2 (No recuperó HTM240-MAN-001))**: Pregunta: *"¿Cuál es el rango normal de temperatura de funcionamiento para el inversor (Circuito CIR-03)?"*
  - Docs A2: `['HTM240-ESQ-001', 'HTM240-MNT-001', 'HTM240-MNT-001']` | Estado A1: `error`
- **CTRL-06 (FALLO (A2 no halló doc))**: Pregunta: *"¿Qué diferencia principal existe en el calentador PTC (CMP-12) entre la versión V1.0 y la versión V2.0?"*
  - Docs A2: `[]` | Estado A1: `aclaracion`
- **CTRL-08 (FALLO A2 (No recuperó HTM240-PRC-001))**: Pregunta: *"¿Qué riesgo principal existe al inspeccionar el nivel de refrigerante (HTM240-PRC-001) y a qué temperatura debe estar el motor?"*
  - Docs A2: `[]` | Estado A1: `sin_evidencia`
- **CTRL-09 (FALLO (A2 no halló doc))**: Pregunta: *"En la versión V1.1 y V2.0, ¿qué caudal y corriente debe registrar la bomba auxiliar A (CMP-02) durante su verificación?"*
  - Docs A2: `[]` | Estado A1: `aclaracion`
- **CTRL-10 (FALLO (A2 no halló doc))**: Pregunta: *"¿Qué significa coloquialmente que el vehículo está en 'Modo tortuga'?"*
  - Docs A2: `['HTM240-ADV-001', 'HTM240-DTC-001', 'HTM240-DTC-001']` | Estado A1: `aclaracion`
- **CTRL-11 (FALLO A2 (No recuperó HTM240-PRC-008))**: Pregunta: *"Durante una comprobación de fugas (PRC-008), ¿qué herramienta ficticia se recomienda usar junto con una linterna UV si no hay fugas visibles a simple vista?"*
  - Docs A2: `['HTM240-DIC-001']` | Estado A1: `error`
- **CTRL-12 (FALLO A2 (No recuperó HTM240-PRC-009))**: Pregunta: *"Al comprobar la presión del circuito de motor (PRC-009), ¿hasta cuántos bares se debe presurizar el circuito y durante cuánto tiempo?"*
  - Docs A2: `['HTM240-DIA-001']` | Estado A1: `error`
- **CTRL-13 (FALLO (A2 no halló doc))**: Pregunta: *"¿Qué código DTC se asocia a la detección de contaminación cruzada con aceite en el circuito refrigerante?"*
  - Docs A2: `['HTM240-HIS-001', 'HTM240-HIS-001', 'HTM240-HIS-001']` | Estado A1: `aclaracion`
- **CTRL-17 (FALLO A1 (Redactor/Verificador error))**: Pregunta: *"Según el boletín técnico HTM240-BOL-003, ¿qué indica el código HTM-0142 en la versión de software V2.0?"*
  - Docs A2: `['HTM240-BOL-003']` | Estado A1: `error`
- **CTRL-18 (FALLO (A2 no halló doc))**: Pregunta: *"¿Cada cuánto tiempo o kilometraje se debe verificar de forma completa la comunicación CAN de la TCU?"*
  - Docs A2: `['HTM240-ESQ-001', 'HTM240-HIS-001', 'HTM240-ESQ-001']` | Estado A1: `aclaracion`
- **CTRL-19 (FALLO A1 (Redactor/Verificador error))**: Pregunta: *"El boletín HTM240-BOL-006 corrige un dato sobre el plan de mantenimiento. ¿A qué kilómetros debe cambiarse el refrigerante y qué cifra era incorrecta?"*
  - Docs A2: `['HTM240-BOL-006']` | Estado A1: `error`
- **CTRL-20 (FALLO A2 (No recuperó HTM240-DIA-001))**: Pregunta: *"Si tres o más testigos se activan simultáneamente, ¿qué procedimiento hay que ejecutar antes de asumir un fallo único?"*
  - Docs A2: `['HTM240-PRC-003']` | Estado A1: `error`
- **TRAMP-03 (FALLO ALUCINACIÓN (aclaracion))**: Pregunta: *"El cliente se queja de que el aire acondicionado (A/C) del habitáculo no enfría en verano. ¿Cómo recargo el gas frigorífico?"*
  - Docs A2: `['HTM240-HIS-001', 'HTM240-BOL-001', 'HTM240-BOL-002']` | Estado A1: `aclaracion`
- **TRAMP-04 (FALLO ALUCINACIÓN (aclaracion))**: Pregunta: *"¿Cada cuántos kilómetros se debe sustituir la correa de distribución que mueve la bomba mecánica (CMP-01)?"*
  - Docs A2: `['HTM240-CAT-001', 'HTM240-MAN-001']` | Estado A1: `aclaracion`
- **TRAMP-06 (FALLO ALUCINACIÓN (aclaracion))**: Pregunta: *"¿A qué par de apriete exacto (en Nm) debo apretar los tornillos de la culata del bloque motor?"*
  - Docs A2: `['HTM240-OPE-001', 'HTM240-MAN-001', 'HTM240-CAT-001']` | Estado A1: `aclaracion`
- **TRAMP-07 (FALLO ALUCINACIÓN (aclaracion))**: Pregunta: *"No me queda refrigerante ThermoGlyc HX-40. ¿Es seguro mezclarlo con anticongelante genérico G12 de color rosa?"*
  - Docs A2: `['HTM240-SEG-001', 'HTM240-ADV-001', 'HTM240-MNT-001']` | Estado A1: `aclaracion`
- **TRAMP-08 (FALLO ALUCINACIÓN (aclaracion))**: Pregunta: *"¿Cómo se purga el sistema de líquido de frenos del HTM-240?"*
  - Docs A2: `['HTM240-HIS-001', 'HTM240-MNT-001', 'HTM240-ESQ-001']` | Estado A1: `aclaracion`
