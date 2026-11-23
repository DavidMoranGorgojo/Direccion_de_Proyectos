#!/usr/bin/env bash
# Genera el paquete final del Frontend: dist/arsoft-frontend-<versión>.tar.gz
# Contenido: frontend.sif, run-frontend.sh, verificar.sh, SHA256SUMS y LEEME.txt.
#
# Uso (desde la raíz del repositorio, en Ubuntu/WSL2):
#   bash apptainer/package-frontend.sh            # reutiliza ~/arsoft-images/frontend.sif si existe
#   bash apptainer/package-frontend.sh --rebuild  # reconstruye la imagen antes (pide sudo)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
IMAGES="${ARSOFT_IMAGES_DIR:-$HOME/arsoft-images}"
SIF="$IMAGES/frontend.sif"
VERSION="${ARSOFT_VERSION:-$(date +%Y%m%d)-$(git rev-parse --short HEAD 2>/dev/null || echo local)}"
if [[ -n "$(git status --porcelain Frontend apptainer 2>/dev/null)" ]]; then
  echo "Aviso: hay cambios sin confirmar en Frontend/ o apptainer/; el paquete no corresponde a un commit." >&2
  VERSION="$VERSION-dirty"
fi

if [[ "${1:-}" == "--rebuild" || ! -f "$SIF" ]]; then
  bash apptainer/build-all.sh frontend
fi
[[ -f "$SIF" ]] || { echo "No se encontró $SIF" >&2; exit 2; }

NAME="arsoft-frontend-$VERSION"
OUT="dist/$NAME"
rm -rf "$OUT" "dist/$NAME.tar.gz"
mkdir -p "$OUT"
cp "$SIF" "$OUT/frontend.sif"
cp apptainer/run-frontend.sh "$OUT/run-frontend.sh"
cp apptainer/verify-frontend.sh "$OUT/verificar.sh"
cat > "$OUT/LEEME.txt" <<TXT
ARSOFT Frontend - paquete $VERSION

Requisitos: Ubuntu (o WSL2 con WSLg en Windows 11) con Apptainer instalado y sesión gráfica.
  Instalación de Apptainer: ver apptainer/GUIA_INSTALACION_WINDOWS.md del repositorio.

1. Descomprimir:     tar -xzf $NAME.tar.gz && cd $NAME
2. Verificar:        bash verificar.sh
3. Abrir (demo):     bash run-frontend.sh
   Modo real:        ARSOFT_API_URL=http://127.0.0.1:8000 bash run-frontend.sh

Sin ARSOFT_API_URL la aplicación usa respuestas simuladas (no es el asistente real).
Otras variables opcionales: ARSOFT_MODO, ARSOFT_LOGIN_PATH, ARSOFT_HISTORIAL_PATH,
ARSOFT_CONSULTA_PATH, ARSOFT_TIMEOUT_S, ARSOFT_ALLOW_HTTP (ver Frontend/readme.md).
TXT
(cd "$OUT" && sha256sum frontend.sif run-frontend.sh verificar.sh LEEME.txt > SHA256SUMS)
chmod +x "$OUT/run-frontend.sh" "$OUT/verificar.sh"
tar -C dist -czf "dist/$NAME.tar.gz" "$NAME"
(cd dist && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
echo "Paquete generado:"
ls -lh "dist/$NAME.tar.gz"
cat "dist/$NAME.tar.gz.sha256"
