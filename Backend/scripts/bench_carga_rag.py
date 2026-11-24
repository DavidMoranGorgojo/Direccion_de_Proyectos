"""Benchmark de carga (p50/p95/p99) y resiliencia sobre /conocimiento/lexica y /conocimiento/vectorial."""

import concurrent.futures
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def post_json(base_url: str, path: str, token: str | None, payload=None, raw_body: bytes | None = None,
              timeout: float = 10.0, allow_nan: bool = False):
    data = raw_body if raw_body is not None else json.dumps(payload, allow_nan=allow_nan).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            lat_ms = (time.perf_counter() - t0) * 1000
            return resp.status, lat_ms, body
    except urllib.error.HTTPError as e:
        lat_ms = (time.perf_counter() - t0) * 1000
        return e.code, lat_ms, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        lat_ms = (time.perf_counter() - t0) * 1000
        return type(e).__name__, lat_ms, str(e)


def percentil(datos: list[float], p: float) -> float:
    ordenados = sorted(datos)
    idx = min(len(ordenados) - 1, int(round((p / 100.0) * (len(ordenados) - 1))))
    return ordenados[idx]


def benchmark_endpoint(base_url: str, token: str, nombre: str, path: str, payloads: list[dict],
                       total_reqs: int = 200, workers: int = 10) -> bool:
    status_warm, _, body_warm = post_json(base_url, path, token, payload=payloads[0])
    if status_warm != 200:
        print(f"[ERROR] Warm-up fallido en {path}: status={status_warm} body={body_warm[:120]}", file=sys.stderr)
        return False

    latencias: list[float] = []
    errores: list[tuple] = []
    t_inicio = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futuros = [
            ex.submit(post_json, base_url, path, token, payload=payloads[i % len(payloads)])
            for i in range(total_reqs)
        ]
        for f in concurrent.futures.as_completed(futuros):
            status, lat_ms, body = f.result()
            if status == 200:
                latencias.append(lat_ms)
            else:
                errores.append((status, body[:120]))
    duracion_s = time.perf_counter() - t_inicio

    throughput_ok = len(latencias) / duracion_s if duracion_s > 0 else 0.0
    print(f"\n=== CARGA: {nombre} ({total_reqs} reqs, {workers} hilos) ===")
    print(f"  Éxitos: {len(latencias)}/{total_reqs} | Errores: {len(errores)} | Throughput (200 OK): {throughput_ok:.1f} req/s")
    if latencias:
        print(f"  Media:  {statistics.mean(latencias):.2f} ms")
        print(f"  p50:    {percentil(latencias, 50):.2f} ms")
        print(f"  p95:    {percentil(latencias, 95):.2f} ms")
        print(f"  p99:    {percentil(latencias, 99):.2f} ms")
        print(f"  Máx:    {max(latencias):.2f} ms")
    if errores:
        print("  Muestra errores:", errores[:3])
    return len(errores) == 0


def main() -> int:
    base_url = os.getenv("ARSOFT_API_URL", "http://127.0.0.1:8000")
    token = os.getenv("ARSOFT_SERVICE_TOKEN")
    if not token:
        print("Error: define ARSOFT_SERVICE_TOKEN antes de ejecutar el benchmark.", file=sys.stderr)
        return 2

    chunks_path = Path(os.getenv("ARSOFT_CHUNKS_PATH", Path.home() / "arsoft-state" / "ingesta" / "salida" / "chunks.jsonl"))
    if not chunks_path.is_file():
        print(f"Error: no se encuentra {chunks_path}", file=sys.stderr)
        return 2

    chunks = [json.loads(line) for line in chunks_path.open(encoding="utf-8") if line.strip()]
    vectores_reales = [c["embedding"] for c in chunks]
    consultas_lexicas = [
        "mantenimiento preventivo HTM-240",
        "purgado circuito termico motor",
        "bomba electrica auxiliar bateria",
        "sensores temperatura TCU CAN",
        "valvula distribuidora cuatro vias",
        "inspeccion fugas refrigerante",
        "codigo error DTC",
        "electroventilador prueba funcional",
        "sustitucion filtro circuito bateria",
        "comprobacion presion circuito motor",
        "protocolo seguridad alta tension",
        "diagnostico sobrecalentamiento inversor",
    ]

    payloads_lex = [{"texto": q, "k": 5} for q in consultas_lexicas]
    payloads_vec = [{"vector": v, "k": 5} for v in vectores_reales]

    ok_lex = benchmark_endpoint(base_url, token, "Búsqueda Léxica (/conocimiento/lexica)", "/conocimiento/lexica", payloads_lex)
    ok_vec = benchmark_endpoint(base_url, token, "Búsqueda Vectorial HNSW (/conocimiento/vectorial)", "/conocimiento/vectorial", payloads_vec)

    print("\n=== PRUEBAS DE FALLO Y RESILIENCIA ===")
    casos_fallo = [
        ("Sin token Bearer", "/conocimiento/lexica", {"texto": "HTM-240"}, None, None, 5.0, False, {401}),
        ("Token inválido", "/conocimiento/vectorial", {"vector": [0.0] * 1024}, None, "token-falso", 5.0, False, {401}),
        ("JSON malformado", "/conocimiento/lexica", None, b"{json_roto:", token, 5.0, False, {422}),
        ("Texto vacío en léxica", "/conocimiento/lexica", {"texto": "   "}, None, token, 5.0, False, {422}),
        ("Vector dimensión inválida (512 != 1024)", "/conocimiento/vectorial", {"vector": [0.1] * 512}, None, token, 5.0, False, {400, 422}),
        ("Vector con valores NaN", "/conocimiento/vectorial", {"vector": [float("nan")] * 1024}, None, token, 5.0, True, {400, 422}),
        ("Vector con tipo inválido (strings)", "/conocimiento/vectorial", {"vector": ["no_float"] * 1024}, None, token, 5.0, False, {400, 422}),
        ("Parámetro k fuera de rango (k=9999)", "/conocimiento/lexica", {"texto": "motor", "k": 9999}, None, token, 5.0, False, {422}),
        ("Filtro versión inexistente (V9.9)", "/conocimiento/vectorial", {"vector": [0.0] * 1024, "filtros": {"version": "V9.9"}}, None, token, 5.0, False, {400}),
        ("Timeout cliente agresivo (0.0002s)", "/conocimiento/vectorial", {"vector": vectores_reales[0], "k": 10}, None, token, 0.0002, False, {"TimeoutError", "URLError"}),
    ]

    fallos = 0
    for desc, path, payload, raw, tok, tout, allow_nan, esperados in casos_fallo:
        status, lat_ms, _ = post_json(base_url, path, tok, payload=payload, raw_body=raw, timeout=tout, allow_nan=allow_nan)
        ok = status in esperados
        if not ok:
            fallos += 1
        marca = "PASS" if ok else "FAIL"
        print(f"  [{marca}] {desc:42s} -> status={status} ({lat_ms:.1f} ms)")

    if not (ok_lex and ok_vec) or fallos > 0:
        print(f"\n[ERROR] Benchmark finalizado con fallos (carga_ok={ok_lex and ok_vec}, casos_fallo={fallos}).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
