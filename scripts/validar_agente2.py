"""Ejecuta la validación local del Agente 2 integrado con el Agente 1."""

import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    python_paths = [str(root), str(root / "shared")]
    if os.environ.get("PYTHONPATH"):
        python_paths.append(os.environ["PYTHONPATH"])

    env = dict(
        os.environ,
        ARSOFT_ENV="test",
        PYTHONPATH=os.pathsep.join(python_paths),
        RUN_REAL_RERANKER_TEST="0",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    command = [
        sys.executable,
        "-B",
        "-m",
        "pytest",
        "Test/test_Models",
        "Test/test_Agents",
        "Agents/Agent_2/tests/unit",
        "Agents/Agent_2/tests/performance",
        "--import-mode=importlib",
        "-p",
        "no:cacheprovider",
        "-q",
        "-rs",
        "--tb=short",
    ]
    return subprocess.run(command, cwd=root, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
