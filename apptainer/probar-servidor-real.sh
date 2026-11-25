#!/usr/bin/env bash
# Comprueba, sin abrir la interfaz, que el servidor real responde antes de pasar el checklist.
# Uso:
#   ARSOFT_API_URL=https://servidor bash apptainer/probar-servidor-real.sh [usuario] [contraseña]
# Con usuario y contraseña también prueba login (CTR-005), historial (CTR-006) y una consulta (CTR-001).
# No guarda ni imprime la contraseña ni el token.
set -uo pipefail
URL="${ARSOFT_API_URL:-}"
[[ -n "$URL" ]] || { echo "Define ARSOFT_API_URL (sin barra final)."; exit 2; }
URL="${URL%/}"
USUARIO="${1:-}"; CLAVE="${2:-}"
TO="${ARSOFT_TIMEOUT_S:-60}"
fallos=0
ok()  { echo "  [OK]    $*"; }
mal() { echo "  [FALLO] $*"; fallos=$((fallos + 1)); }
curl_code() { local c; c="$(curl -sS -m "$TO" -o "$1" -w '%{http_code}' "${@:2}" 2>/dev/null)" || true; echo "${c:-000}"; }
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT

echo "Servidor: $URL"
c="$(curl_code "$tmp" "$URL/ready")"
[[ "$c" == 200 ]] && ok "/ready -> 200 (PostgreSQL y Agentes disponibles)" || mal "/ready -> $c (el servidor no está listo o no es alcanzable)"

if [[ -n "$USUARIO" && -n "$CLAVE" ]]; then
  c="$(curl_code "$tmp" -X POST "$URL/auth/login" -H 'Content-Type: application/json' \
       --data "$(printf '{"usuario":"%s","contrasena":"%s"}' "$USUARIO" "$CLAVE")")"
  if [[ "$c" == 200 ]]; then
    ok "POST /auth/login -> 200"
    TOKEN="$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$tmp")"
    [[ -n "$TOKEN" ]] && ok "El login devuelve token" || mal "El login no devuelve 'token'"
    H=(-H "Authorization: Bearer $TOKEN")
    c="$(curl_code "$tmp" "${H[@]}" "$URL/chats")"
    [[ "$c" == 200 ]] && ok "GET /chats -> 200" || mal "GET /chats -> $c"
    c="$(curl_code "$tmp" "${H[@]}" -X POST "$URL/consulta" -H 'Content-Type: application/json' \
         --data '{"conversacion_id":"","pregunta":"¿Cada cuánto se cambia el refrigerante?"}')"
    if [[ "$c" == 200 ]]; then
      estado="$(sed -n 's/.*"estado"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$tmp" | head -1)"
      if [[ "$estado" == "error" ]]; then
        codigo="$(sed -n 's/.*"codigo_error"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$tmp" | head -1)"
        mal "POST /consulta -> 200 pero estado: error (codigo_error: ${codigo:-desconocido})"
      else
        ok "POST /consulta -> 200 (respuesta con estado: ${estado:-desconocido})"
      fi
    else
      mal "POST /consulta -> $c"
    fi
  else
    mal "POST /auth/login -> $c"
  fi
else
  echo "  (sin usuario y contraseña: solo se ha probado /ready)"
fi
echo; [[ $fallos -eq 0 ]] && echo "Servidor correcto." || { echo "$fallos comprobación(es) fallida(s)."; exit 1; }
