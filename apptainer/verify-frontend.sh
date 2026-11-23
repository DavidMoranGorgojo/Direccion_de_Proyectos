#!/usr/bin/env bash
# Comprueba que el paquete del Frontend funciona en esta máquina (sin abrir ventana).
# Se ejecuta desde la carpeta del paquete (o con ARSOFT_FRONTEND_IMAGE=/ruta/frontend.sif).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${ARSOFT_FRONTEND_IMAGE:-$HERE/frontend.sif}"
fallos=0
ok()  { echo "  [OK]    $*"; }
mal() { echo "  [FALLO] $*"; fallos=$((fallos + 1)); }

echo "Verificación del Frontend ARSOFT"
command -v apptainer >/dev/null && ok "Apptainer $(apptainer version)" || mal "Apptainer no está instalado"
[[ -f "$IMAGE" ]] && ok "Imagen: $IMAGE" || { mal "Falta $IMAGE"; exit 1; }

if [[ -f "$HERE/SHA256SUMS" ]]; then
  (cd "$HERE" && sha256sum -c --quiet SHA256SUMS) && ok "Sumas SHA-256 correctas" || mal "Las sumas SHA-256 no coinciden"
fi

if [[ -n "${DISPLAY:-}" ]]; then ok "DISPLAY=$DISPLAY"; else mal "Sin DISPLAY: se necesita una sesión gráfica (WSLg en Windows 11)"; fi
[[ -d /tmp/.X11-unix ]] && ok "/tmp/.X11-unix presente" || mal "Falta /tmp/.X11-unix"

# Arranque sin ventana: importa Qt y recorre login, historial y consulta en modo simulado.
salida="$(env -u ARSOFT_API_URL -u ARSOFT_MODO apptainer exec --cleanenv \
  --env QT_QPA_PLATFORM=offscreen --env ARSOFT_MODO=simulado --env ARSOFT_MOCK_EMPTY_HISTORY=0 \
  --env PYTHONPATH=/opt/arsoft/frontend --pwd /opt/arsoft/frontend "$IMAGE" python -c '
from PySide6.QtWidgets import QApplication
import config
from services import api
app = QApplication([])
assert api.is_mock(), "no está en modo simulado"
st, data = api.call("GET", api.HISTORIAL_PATH)
assert st == 200 and "chats" in data, "historial simulado"
r = api.send_message("", "revisar refrigerante en el motor")
assert r.estado in ("respuesta", "aclaracion", "sin_evidencia", "fuera_de_ambito"), r.estado
print("modo simulado, historial y consulta correctos; consulta ->", api.CONSULTA_PATH)
' 2>&1)"
if [[ $? -eq 0 ]]; then ok "$salida"; else mal "El contenedor no arranca: $salida"; fi

# Que la imagen no lleve cachés, ajustes de editor ni .env.
sobrante="$(apptainer exec --cleanenv "$IMAGE" find /opt/arsoft/frontend \( -name '__pycache__' -o -name '.vscode' -o -name '.env' \) 2>/dev/null)"
[[ -z "$sobrante" ]] && ok "Imagen sin __pycache__, .vscode ni .env" || mal "Sobran archivos en la imagen: $sobrante"

echo
if (( fallos == 0 )); then echo "Todo correcto. Abre la aplicación con: bash run-frontend.sh"; else echo "$fallos comprobación(es) fallida(s)."; exit 1; fi
