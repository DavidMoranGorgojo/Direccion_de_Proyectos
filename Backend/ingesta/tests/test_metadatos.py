from ingesta.extraccion import unir
from ingesta.metadatos import afectado_por, chunk_id, componente, ids_referenciados


def test_unir_quita_guion_de_palabra_partida():
    assert unir("procedimien-", "tos son ficticios", set()) == "procedimientos son ficticios"
    assert unir("Ther-", "moDrive HTM-240", set()) == "ThermoDrive HTM-240"


def test_unir_conserva_guion_en_codigos():
    assert unir("ver HTM240-", "BOL-002", set()) == "ver HTM240-BOL-002"
    assert unir("sensor CMP-", "18", set()) == "sensor CMP-18"


def test_unir_conserva_compuestos_vistos_en_el_documento():
    assert unir("intercambiador aceite-", "refrigerante", {"aceiterefrigerante"}) == "intercambiador aceite-refrigerante"


def test_ids_referenciados_formas_cortas_y_listas_abreviadas():
    texto = "Referencias: HTM240-PRC-001, 005, 008; HTM240-DTC-001 (HTM-0101); ver HTM240-DIA-001>4.3 y CMP-02, TES-01, CIR-02."
    assert ids_referenciados(texto, "HTM240-SEG-001") == [
        "CIR-02", "CMP-02", "DIA-001 > 4.3", "DTC-001", "HTM-0101", "PRC-001", "PRC-005", "PRC-008", "TES-01",
    ]


def test_ids_referenciados_excluye_el_propio_documento():
    assert ids_referenciados("HTM240-PRC-003 usa CMP-02", "HTM240-PRC-003") == ["CMP-02"]


def test_componente():
    assert componente("CMP-15 — Sensor de temperatura bateria", "texto con CMP-18") == "CMP-15"
    assert componente("Objetivo", "Comprobar la bomba CMP-02 del circuito CIR-02") == "CMP-02"
    assert componente("Pasos", "CMP-02 y CMP-18") is None


def test_afectado_por_segun_reglas_de_boletines():
    assert afectado_por("HTM240-DIA-001@1.1", "HTM240-DIA-001", "4.3 Temperatura baja persistente", []) == ["BOL-003"]
    assert afectado_por("HTM240-DIA-001@1.1", "HTM240-DIA-001", "4.1 Sobrecalentamiento del motor", []) == []
    assert afectado_por("HTM240-MNT-001@1.0", "HTM240-MNT-001", "Documento completo", []) == ["BOL-006"]
    assert afectado_por("HTM240-MNT-001@1.1", "HTM240-MNT-001", "2. Elementos consumibles", []) == []


def test_chunk_id_estable_y_dependiente_del_contenido():
    a = chunk_id("HTM240-PRC-003@2.0", "Pasos", 1, "texto")
    assert a == chunk_id("HTM240-PRC-003@2.0", "Pasos", 1, "texto")
    assert a != chunk_id("HTM240-PRC-003@2.0", "Pasos", 1, "texto cambiado")
    assert a.startswith("HTM240-PRC-003@2.0_pasos_01_")
