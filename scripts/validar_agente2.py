"""Prueba A2 con el A1 versionado, sin incorporarlo al diff hacia agent_2.

La rama agent_2 no contiene A1. Este runner compone una copia nueva con el
contraparte versionado y aplica únicamente el parche CTR-004 heredado de #36.
No modifica ninguna rama ni reutiliza data/ o archivos privados locales.
"""

import argparse
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
A2_PATHS = ["Agents/Agent_2", "Test/test_Models", "Test/test_Performance", "Test/fixtures/agent2", "scripts/calibrar_reranker.py", "scripts/evaluar_agente2.py"]
PEER_PATHS = ["Agents/__init__.py", "Agents/agente1", "Agents/service.py", "Agents/apptainer/agentes.def", "shared",
              "Test/__init__.py", "Test/test_Agents", "Test/test_Models/evaluar_benchmark.py",
              "Test/test_Models/benchmark_completo_CJ02_40_preguntas.json",
              "Test/test_Models/respuestas_reales_cj02.json", "Frontend/models"]


def extract(ref, paths, destination):
    available = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", ref, "--", *paths], cwd=ROOT).decode().splitlines()
    data = subprocess.check_output(["git", "archive", "--format=zip", ref, "--", *available], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(destination)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Referencia A2 versionada")
    parser.add_argument("--peer-ref", default="origin/main", help="Referencia del A1 a verificar")
    parser.add_argument("--working-tree", action="store_true", help="Desarrollo: incluye cambios A2 sin commit")
    args = parser.parse_args(argv)
    # Conservar esta copia facilita revisar fallos sin borrar trabajo del usuario.
    temp_root = ROOT / ".tmp"
    temp_root.mkdir(exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix="validacion-a2-", dir=temp_root))
    print(f"Copia de validación: {target}", flush=True)
    extract(args.peer_ref, PEER_PATHS, target)
    extract(args.ref, A2_PATHS, target)
    if args.working_tree:
        import shutil
        names = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *A2_PATHS], cwd=ROOT).decode().split("\0")
        for name in names:
            source = ROOT / name
            if name and source.is_file() and "/data/" not in name:
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
    # No descubrir el .git del worktree padre: el parche se aplica SOLO a la
    # copia nueva, como parche sin repositorio, nunca al checkout del usuario.
    patch_env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(target.parent))
    for filename in ("agente1-ctr004.patch", "servicio-a2.patch", "apptainer-a2.patch"):
        patch = target / "Agents/Agent_2/integration" / filename
        subprocess.run(["git", "apply", "--unidiff-zero", "--check", str(patch)], cwd=target, env=patch_env, check=True)
        subprocess.run(["git", "apply", "--unidiff-zero", str(patch)], cwd=target, env=patch_env, check=True)
    env = dict(os.environ, ARSOFT_ENV="test", PYTHONPATH=os.pathsep.join([str(target), str(target / "shared")]))
    return subprocess.call([sys.executable, "-m", "pytest", "Test/test_Models", "Test/test_Agents",
                            "Test/test_Performance", "-q", "-rs", "--tb=short"], cwd=target, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
