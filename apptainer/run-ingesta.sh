#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ARSOFT_LOCAL_ENV:-$HERE/.env.local}"
IMAGES="${ARSOFT_IMAGES_DIR:-$HOME/arsoft-images}"
STATE="${ARSOFT_STATE_DIR:-$HOME/arsoft-state}"
INPUT="${ARSOFT_MANUALES_DIR:-$HERE/../data/manuales}"
[[ -f "$IMAGES/ingesta.sif" ]] || { echo 'Falta ingesta.sif' >&2; exit 2; }
[[ -d "$INPUT" ]] || { echo "Falta $INPUT. Define ARSOFT_MANUALES_DIR." >&2; exit 2; }
if [[ -f "$ENV_FILE" ]]; then
  source "$ENV_FILE"
fi
mkdir -p "$STATE/ingesta/salida" "$STATE/cache/huggingface"
APPTAINERENV_DATABASE_URL="${DATABASE_URL:-}" \
  apptainer run --cleanenv \
    --bind "$INPUT:/data/manuales:ro" \
    --bind "$STATE/ingesta/salida:/data/salida" \
    --bind "$STATE/cache/huggingface:/cache/huggingface" \
    "$IMAGES/ingesta.sif" "$@"
