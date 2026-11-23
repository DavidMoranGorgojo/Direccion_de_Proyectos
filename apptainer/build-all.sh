#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
IMAGES="$(printenv ARSOFT_IMAGES_DIR || true)"
[[ -n "$IMAGES" ]] || IMAGES="$HOME/arsoft-images"
APPTAINER_TMPDIR="$(printenv APPTAINER_TMPDIR || true)"
[[ -n "$APPTAINER_TMPDIR" ]] || APPTAINER_TMPDIR="$HOME/.cache/arsoft/apptainer-tmp"
mkdir -p "$IMAGES" "$APPTAINER_TMPDIR"
if (( $# == 0 )); then
  set -- postgres backend ingesta frontend agentes
fi
TEMP_IMAGE=""
cleanup_temp() {
  if [[ -n "$TEMP_IMAGE" && -e "$TEMP_IMAGE" ]]; then rm -f -- "$TEMP_IMAGE"; fi
}
trap cleanup_temp EXIT
for name in "$@"; do
  case "$name" in
    postgres|backend|ingesta) def="Backend/apptainer/$name.def" ;;
    frontend) def=Frontend/apptainer/frontend.def ;;
    agentes) def=Agents/apptainer/agentes.def ;;
    *) echo "Servicio desconocido: $name" >&2; exit 2 ;;
  esac
  case "$name" in
    backend) context=Backend/api/app ;;
    ingesta) context=Backend/ingesta ;;
    frontend) context=Frontend ;;
    agentes) context=Agents ;;
    postgres) context=Backend/db/init ;;
  esac
  secret="$(find "$context" -type f \( -name '.env' -o -name '*.pem' -o -name '*.key' -o -name 'id_ed25519' \) -print -quit)"
  if [[ -n "$secret" ]]; then
    echo "Posible secreto en el contexto de construcción: $secret" >&2
    exit 2
  fi
  TEMP_IMAGE="$IMAGES/.$name.building.$$.sif"
  rm -f -- "$TEMP_IMAGE"
  sudo env \
    APPTAINER_TMPDIR="$APPTAINER_TMPDIR" \
    TMPDIR="$APPTAINER_TMPDIR" \
    apptainer build "$TEMP_IMAGE" "$def"
  sudo chown "$(id -u):$(id -g)" "$TEMP_IMAGE"
  mv -f -- "$TEMP_IMAGE" "$IMAGES/$name.sif"
  TEMP_IMAGE=""
done