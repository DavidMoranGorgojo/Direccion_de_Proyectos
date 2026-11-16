#!/usr/bin/env bash
set -euo pipefail
IMAGE="${ARSOFT_IMAGES_DIR:-$HOME/arsoft-images}/frontend.sif"
[[ -f "$IMAGE" ]] || { echo "Falta $IMAGE" >&2; exit 2; }
: "${DISPLAY:?Ejecuta el frontend desde una sesión gráfica de Ubuntu WSL2 con WSLg}"
APPTAINERENV_DISPLAY="$DISPLAY" \
APPTAINERENV_ARSOFT_API_URL="${ARSOFT_API_URL:-}" \
  apptainer run --cleanenv --bind /tmp/.X11-unix:/tmp/.X11-unix "$IMAGE" "$@"
