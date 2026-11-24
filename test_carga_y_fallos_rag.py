import concurrent.futures
import json
import os
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.getenv("ARSOFT_API_URL", "http://127.0.0.1:8000")
TOKEN = os.environ["ARSOFT_SERVICE_TOKEN"]
CHUNKS_PATH = Path.home() / "arsoft-state" / "ingesta" / "salida" / "chunks.jsonl"

chunks = [json.loads(line) for line in CHUNKS_PATH.open(encoding="utf-8") if line.strip()]
vectores_reales = [c["embedding"] for c in chunks[:20]]
consultas_lexicas = [
    "mantenimiento preventivo HTM-240",
    "purgado circuito termico motor",
    "bomba electrica auxiliar bateria",
    "sensores temperatura TCU CAN",
    "valvula distribuidora cuatro vias",
    "inspeccion fugas refrigerante",
    "codigo error DTC",
    "electroventilador prueba funcional",
]

def post_json(path, payload=None, raw_body=None, token=TOKEN, timeout=10.0):
    data = raw_body if raw_body is not None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method="POST")
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

def percentil(datos, p):
    ordenados = sorted(datos)
    idx = min(len(ordenados) - 1, int(round((p / 100.0) * (len(ordenados) - 1))))
    return ordenados[idx]

def benchmark_endpoint(nombre, path, payloads, total_reqs=200, workers=10):
    # Calentamiento
    post_json(path, payloads[0])
    latencias = []
    errores = []
    t_inicio = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futuros = [ex.submit(post_json, path, payloads[i % len(payloads)]) for i in range(total_reqs)]
        for f in concurrent.futures.as_completed(futuros):
            status, lat_ms, body = f.result()
            if status == 200:
                latencias.append(lat_ms)
            else:
                errores.append((status, body[:120]))
    duracion_s = time.perf_counter() - t_inicio
    print(f"\n=== CARGA: {nombre} ({total_reqs} reqs, {workers} hilos) ===")
    print(f"  Éxitos: {len(latencias)}/{total_reqs} | Errores: {len(errores)} | Throughput: {total_reqs/duracion_s:.1f} req/s")
    if latencias:
        print(f"  Media:  {statistics.mean(latencias):.2f} ms")
        print(f"  p50:    {percentil(latencias, 50):.2f} ms")
        print(f"  p95:    {percentil(latencias, 95):.2f} ms")
        print(f"  p99:    {percentil(latencias, 99):.2f} ms")
        print(f"  Máx:    {max(latencias):.2f} ms")
    if errores:
        print("  Muestra errores:", errores[:3])

# 1. Pruebas de carga
payloads_lex = [{"texto": q, "k": 5} for q in consultas_lexicas]
payloads_vec = [{"vector": v, "k": 5} for v in vectores_reales]

benchmark_endpoint("Búsqueda Léxica (/conocimiento/lexica)", "/conocimiento/lexica", payloads_lex)
benchmark_endpoint("Búsqueda Vectorial HNSW (/conocimiento/vectorial)", "/conocimiento/vectorial", payloads_vec)

# 2. Pruebas de fallo
print("\n=== PRUEBAS DE FALLO Y RESILIENCIA ===")
casos_fallo = [
    ("Sin token Bearer", "/conocimiento/lexica", {"texto": "HTM-240"}, None, None, 5.0, {401, 403}),
    ("Token inválido", "/conocimiento/vectorial", {"vector": [0.0]*1024}, None, "token-falso", 5.0, {401, 403}),
    ("JSON malformado", "/conocimiento/lexica", None, b"{json_roto:", TOKEN, 5.0, {400, 422}),
    ("Texto vacío en léxica", "/conocimiento/lexica", {"texto": "   "}, None, TOKEN, 5.0, {400, 422}),
    ("Vector dimensión inválida (512 != 1024)", "/conocimiento/vectorial", {"vector": [0.1]*512}, None, TOKEN, 5.0, {400, 422}),
    ("Vector con NaN / tipo inválido", "/conocimiento/vectorial", {"vector": ["no_float"]*1024}, None, TOKEN, 5.0, {400, 422}),
    ("Parámetro k fuera de rango (k=9999)", "/conocimiento/lexica", {"texto": "motor", "k": 9999}, None, TOKEN, 5.0, {400, 422}),
    ("Filtro versión inexistente (V9.9)", "/conocimiento/vectorial", {"vector": [0.0]*1024, "filtros": {"version": "V9.9"}}, None, TOKEN, 5.0, {400, 422}),
    ("Timeout cliente agresivo (0.0002s)", "/conocimiento/vectorial", {"vector": vectores_reales[0], "k": 10}, None, TOKEN, 0.0002, {"TimeoutError", "timeout", "URLError"}),
]

for desc, path, payload, raw, tok, tout, esperados in casos_fallo:
    status, lat_ms, body = post_json(path, payload=payload, raw_body=raw, token=tok, timeout=tout)
    ok = status in esperados or any(str(e) in str(status) for e in esperados)
    marca = "PASS" if ok else "FAIL"
    print(f"  [{marca}] {desc:42s} -> status={status} ({lat_ms:.1f} ms)")
