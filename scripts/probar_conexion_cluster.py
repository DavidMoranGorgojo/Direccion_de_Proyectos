#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ARSOFT Reto Automoción — Diagnóstico y Comprobación del Clúster Legio
=============================================================================
Comprueba la conectividad de extremo a extremo con el servicio LLM del clúster
Legio (GVIS - Universidad de León) a través del túnel SSH local:

Precauciones operativas del clúster Legio:
  1. El nodo 'legio2' es de acceso y tiene cuota estricta (4 GiB RAM y 1 CPU por usuario).
     Queda terminantemente prohibido ejecutar procesos de inferencia pesados o
     entrenamiento directamente en 'legio2'.
  2. Las GPUs son compartidas: no lanzar miles de peticiones automáticas sin avisar.
  3. Parámetros controlados: temperature=0.0, max_tokens=512, stream=False.

Pasos que valida:
  1. Resolución segura de la API Key (LLM_KEY o ~/.config/llm-gvis/api_key).
  2. Estado del socket local http://localhost:4000 (túnel SSH activo).
  3. Llamada al endpoint OpenAI-compatible /v1/chat/completions con rol 'rapido'.
  4. Llamada al endpoint con rol 'potente' (razonamiento y citas técnicas).
  5. Verificación de latencia y cumplimiento de parámetros.

Uso:
  python scripts/probar_conexion_cluster.py
  python scripts/probar_conexion_cluster.py --solo-ping
  python scripts/probar_conexion_cluster.py --timeout 60
=============================================================================
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Añadir raíz del repositorio al PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from Agents.agente1.cliente_cluster import (
    ClienteClusterLegio,
    ROL_RAPIDO,
    ROL_POTENTE,
    TunelClusterError,
    AutenticacionClusterError,
    TimeoutClusterError,
    verificar_puerto_abierto,
    resolver_api_key,
)


def imprimir_encabezado():
    print("\n" + "=" * 78)
    print("  DIAGNÓSTICO DE CONEXIÓN AL CLÚSTER LEGIO (GVIS - UNIVERSIDAD DE LEÓN)")
    print("  Asistente RAG Automotriz ThermoDrive HTM-240")
    print("=" * 78)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Comprobador de conexión al servicio LLM del clúster Legio")
    parser.add_argument("--url", default="http://localhost:4000/v1", help="URL base del servicio (default: http://localhost:4000/v1)")
    parser.add_argument("--timeout", type=float, default=45.0, help="Timeout en segundos por llamada (default: 45s)")
    parser.add_argument("--solo-ping", action="store_true", help="Solo comprueba socket y credenciales sin llamar a la API")
    args = parser.parse_args()

    imprimir_encabezado()

    # Advertencia de recursos
    print("\n[AVISO DE POLÍTICA DE RECURSOS LEGIO]")
    print("  • Nodo legio2: Acceso restringido (4 GiB RAM, 1 CPU). Carga pesada NO permitida.")
    print("  • GPUs compartidas en el clúster: Concurrencia controlada, sin ráfagas masivas.")

    # 1. Comprobación de API Key
    print("\n[PASO 1/4] Verificando credenciales de acceso...")
    env_key = os.environ.get("LLM_KEY", "").strip()
    ruta_archivo = Path.home() / ".config" / "llm-gvis" / "api_key"
    userprofile = os.environ.get("USERPROFILE")
    ruta_win = Path(userprofile) / ".config" / "llm-gvis" / "api_key" if userprofile else None

    origen_clave = None
    if env_key:
        origen_clave = "variable de entorno LLM_KEY"
    elif ruta_archivo.is_file():
        origen_clave = f"archivo {ruta_archivo}"
    elif ruta_win and ruta_win.is_file():
        origen_clave = f"archivo {ruta_win}"

    if origen_clave:
        print(f"  [OK] API Key detectada desde: {origen_clave}")
    else:
        print("  [ERROR] No se ha detectado ninguna API Key.")
        print("  Para configurarla, elige una de las siguientes dos opciones:")
        print("    A) En PowerShell:")
        print("       $env:LLM_KEY = \"tu_clave_aqui\"")
        print("    B) Crear el archivo seguro de clave:")
        print(f"       {ruta_win or ruta_archivo}")
        print("       (Pega tu token dentro de ese archivo de texto sin espacios)")
        print("\n[ABORTADO] Imposible continuar sin credenciales.\n")
        sys.exit(1)

    # 2. Comprobación del Socket Local (Túnel SSH)
    print("\n[PASO 2/4] Verificando túnel SSH en localhost:4000...")
    puerto_abierto = verificar_puerto_abierto(host="127.0.0.1", puerto=4000, timeout_s=1.5)
    
    if puerto_abierto:
        print("  [OK] Puerto 4000 accesible en localhost (Túnel SSH detectado activo).")
    else:
        print("  [ERROR] El puerto 4000 en localhost no responde (Conexión rechazada).")
        print("\n  CÓMO ACTIVAR EL TÚNEL SSH HACIA LEGIO:")
        print("  1. Si estás fuera del campus, asegúrate de tener conectada la VPN de la ULE.")
        print("  2. Abre OTRA terminal en tu PC y ejecuta el siguiente comando:")
        print("     ssh -L 4000:localhost:4000 juan.pinos@193.146.98.97")
        print("  3. Deja esa terminal abierta en segundo plano mientras uses el Agente.\n")
        print("[ABORTADO] Abre el túnel SSH y vuelve a ejecutar este comprobador.\n")
        sys.exit(2)

    if args.solo_ping:
        print("\n[OK] Diagnóstico básico completado: Credenciales y socket operativo.\n")
        return

    # Inicializar cliente
    cliente = ClienteClusterLegio(base_url=args.url, timeout_s=args.timeout)

    # 3. Comprobación del Rol Rápido
    print(f"\n[PASO 3/4] Enviando consulta ligera de prueba con rol '{ROL_RAPIDO}'...")
    print(f"  Endpoint: {args.url}/chat/completions | Modelo/Rol: {cliente.modelo_rapido}")
    
    t0 = time.monotonic()
    try:
        mensajes_rapido = [
            {"role": "system", "content": "Eres un extractor de intención conciso."},
            {"role": "user", "content": "Responde exactamente la palabra: OPERATIVO"}
        ]
        resp_rapido = cliente.consultar(mensajes_rapido, rol=ROL_RAPIDO, temperature=0.0, max_tokens=20)
        lat_rapido = (time.monotonic() - t0) * 1000
        print(f"  [OK] Rol '{ROL_RAPIDO}' respondió en {lat_rapido:.1f} ms:")
        print(f"       «{resp_rapido}»")
    except TunelClusterError as err:
        print(f"  [ERROR TÚNEL] {err}")
        sys.exit(3)
    except AutenticacionClusterError as err:
        print(f"  [ERROR AUTENTICACIÓN] {err}")
        sys.exit(4)
    except TimeoutClusterError as err:
        print(f"  [ERROR TIMEOUT] {err}")
        sys.exit(5)
    except Exception as exc:
        print(f"  [ERROR INESPERADO] {type(exc).__name__}: {exc}")
        sys.exit(6)

    # 4. Comprobación del Rol Potente (Razonamiento y Citas)
    print(f"\n[PASO 4/4] Probando inferencia técnica y citas con rol '{ROL_POTENTE}'...")
    print(f"  Endpoint: {args.url}/chat/completions | Modelo/Rol: {cliente.modelo_potente}")

    t1 = time.monotonic()
    try:
        mensajes_potente = [
            {
                "role": "system",
                "content": (
                    "Eres el redactor técnico automotriz de ThermoDrive HTM-240. "
                    "Responde basándote estrictamente en las evidencias proporcionadas "
                    "y añade siempre la cita obligatoria del chunk entre corchetes, ej: [CHUNK_ID]."
                )
            },
            {
                "role": "user",
                "content": (
                    "EVIDENCIA [HTM240-MAN-001@1.1_p15_man_001_01]:\n"
                    "El par de apriete de la carcasa del actuador ACT-02 es de 25 Nm.\n\n"
                    "CONSULTA: ¿Cuál es el par de apriete del actuador ACT-02?"
                )
            }
        ]
        resp_potente = cliente.consultar(mensajes_potente, rol=ROL_POTENTE, temperature=0.0, max_tokens=150)
        lat_potente = (time.monotonic() - t1) * 1000
        print(f"  [OK] Rol '{ROL_POTENTE}' respondió en {lat_potente:.1f} ms:")
        print(f"       «{resp_potente}»")

        # Validar si incluye la cita entre corchetes
        if "[HTM240-MAN-001@1.1_p15_man_001_01]" in resp_potente:
            print("  [OK] Verificación de formato: La cita [HTM240-MAN-001@1.1_p15_man_001_01] está correctamente formateada.")
        else:
            print("  [AVISO] La respuesta no incluyó la cita exacta [HTM240-MAN-001@1.1_p15_man_001_01]; el verificador de Agente 1 aplicará el reintento extractivo.")
    except Exception as exc:
        print(f"  [ERROR ROL POTENTE] {type(exc).__name__}: {exc}")
        sys.exit(7)

    print("\n" + "=" * 78)
    print("  RESULTADO FINAL: CONEXIÓN CON EL CLÚSTER LEGIO 100% OPERATIVA")
    print(f"  • Túnel local:  Activo en {args.url}")
    print(f"  • Rol 'rapido': OK ({lat_rapido:.1f} ms)")
    print(f"  • Rol 'potente': OK ({lat_potente:.1f} ms)")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
