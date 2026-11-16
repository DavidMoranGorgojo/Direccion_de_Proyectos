#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
IMAGES="${ARSOFT_IMAGES_DIR:-$HOME/arsoft-images}"
export APPTAINER_TMPDIR="${APPTAINER_TMPDIR:-$HOME/.cache/arsoft/apptainer-tmp}"
mkdir -p "$IMAGES" "$APPTAINER_TMPDIR"
if (( $# == 0 )); then
  set -- postgres backend ingesta frontend agentes
fi
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
  apptainer build --fakeroot "$IMAGES/$name.sif" "$def"
done
