#!/usr/bin/env bash
# Abre el Frontend PySide6 desde Ubuntu WSL2 (WSLg) o Linux con sesión gráfica.
# Imagen: ARSOFT_FRONTEND_IMAGE, o frontend.sif junto a este script (paquete final),
# o ${ARSOFT_IMAGES_DIR:-~/arsoft-images}/frontend.sif.
# Sin ARSOFT_API_URL arranca en modo simulado (demo). Para el modo real:
#   ARSOFT_API_URL=http://127.0.0.1:8000 bash apptainer/run-frontend.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${ARSOFT_FRONTEND_IMAGE:-}" ]]; then
  IMAGE="$ARSOFT_FRONTEND_IMAGE"
elif [[ -f "$HERE/frontend.sif" ]]; then
  IMAGE="$HERE/frontend.sif"
else
  IMAGE="${ARSOFT_IMAGES_DIR:-$HOME/arsoft-images}/frontend.sif"
fi
[[ -f "$IMAGE" ]] || { echo "Falta $IMAGE (constrúyela con: bash apptainer/build-all.sh frontend)" >&2; exit 2; }
: "${DISPLAY:?Ejecuta el frontend desde una sesión gráfica de Ubuntu WSL2 con WSLg}"

# Solo se pasan al contenedor las variables de configuración del Frontend (Frontend/config.py),
# nunca el resto del entorno (p. ej. ARSOFT_SERVICE_TOKEN).
export APPTAINERENV_DISPLAY="$DISPLAY"
for name in ARSOFT_MODO ARSOFT_API_URL ARSOFT_LOGIN_PATH ARSOFT_HISTORIAL_PATH \
            ARSOFT_CONSULTA_PATH ARSOFT_TIMEOUT_S ARSOFT_ALLOW_HTTP ARSOFT_MOCK_EMPTY_HISTORY; do
  if [[ -n "${!name:-}" ]]; then
    export "APPTAINERENV_$name=${!name}"
  fi
done

binds=()
[[ -d /tmp/.X11-unix ]] && binds=(--bind /tmp/.X11-unix:/tmp/.X11-unix)
exec apptainer run --cleanenv "${binds[@]}" "$IMAGE" "$@"
