#!/usr/bin/env bash
#SBATCH --job-name=arsoft-agentes
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --gres=gpu:1
#SBATCH --output=arsoft-agentes-%j.log
# Rellena --account / --qos / --partition si lo exige tu clúster.
set -euo pipefail
: "${ARSOFT_AGENTS_IMAGE:?Define ruta absoluta de agentes.sif en el clúster}"
: "${ARSOFT_AGENTS_ENV:?Define ruta absoluta del archivo de entorno de Agentes}"
: "${ARSOFT_MODEL_CACHE:?Define directorio persistente para modelos en el clúster}"
[[ -r "$ARSOFT_AGENTS_ENV" ]] || { echo 'No se puede leer el archivo de entorno de Agentes' >&2; exit 2; }
if ! grep -Eq '^AGENTES_START_CMD=.+$' "$ARSOFT_AGENTS_ENV"; then
  echo 'Define AGENTES_START_CMD para ejecutar el servidor HTTP en Slurm' >&2
  exit 2
fi
mkdir -p "$ARSOFT_MODEL_CACHE/huggingface"
apptainer run --nv --cleanenv --env-file "$ARSOFT_AGENTS_ENV" \
  --bind "$ARSOFT_MODEL_CACHE:/models" \
  "$ARSOFT_AGENTS_IMAGE"
