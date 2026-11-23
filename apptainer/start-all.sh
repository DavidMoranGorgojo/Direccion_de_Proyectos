#!/usr/bin/env bash
# Levanta el stack local ARSOFT con Apptainer y abre el Frontend conectado.
set -eo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
CONFIG_DIR="$(printenv ARSOFT_CONFIG_DIR || true)"
[[ -n "$CONFIG_DIR" ]] || CONFIG_DIR="$HOME/.config/arsoft"
ENV_FILE="$(printenv ARSOFT_LOCAL_ENV || true)"
[[ -n "$ENV_FILE" ]] || ENV_FILE="$CONFIG_DIR/local.env"
AGENTS_ENV="$(printenv ARSOFT_AGENTS_ENV || true)"
[[ -n "$AGENTS_ENV" ]] || AGENTS_ENV="$CONFIG_DIR/agentes.env"
IMAGES="$(printenv ARSOFT_IMAGES_DIR || true)"
[[ -n "$IMAGES" ]] || IMAGES="$HOME/arsoft-images"
STATE="$(printenv ARSOFT_STATE_DIR || true)"
[[ -n "$STATE" ]] || STATE="$HOME/arsoft-state"
MANUALES="$(printenv ARSOFT_MANUALES_DIR || true)"
[[ -n "$MANUALES" ]] || MANUALES="$ROOT/data/manuales"
INGESTA_MODE="$(printenv ARSOFT_INGESTA || true)"
[[ -n "$INGESTA_MODE" ]] || INGESTA_MODE=auto

OWN_DB=0
OWN_API=0
OWN_AGENTS=0
log() { printf '[ARSOFT] %s\n' "$*"; }
fail() { printf '[ARSOFT] ERROR: %s\n' "$*" >&2; exit 1; }
set_env_value() {
  env_file="$1"
  env_key="$2"
  env_value="$3"
  if grep -q "^$env_key=" "$env_file"; then
    sed -i "s|^$env_key=.*|$env_key=$env_value|" "$env_file"
  else
    printf '%s=%s\n' "$env_key" "$env_value" >> "$env_file"
  fi
}
has_instance() { grep -Eq "^$1[[:space:]]" <<< "$2"; }
source_newer() {
  image="$1"
  source_path="$2"
  if [[ -f "$source_path" ]]; then
    [[ "$source_path" -nt "$image" ]]
  elif [[ -d "$source_path" ]]; then
    find "$source_path" -type f -newer "$image" -print -quit | grep -q .
  else
    return 1
  fi
}
needs_rebuild() {
  name="$1"
  image="$IMAGES/$name.sif"
  [[ -f "$image" ]] || return 0
  case "$name" in
    postgres) def="$ROOT/Backend/apptainer/postgres.def" ;;
    backend) def="$ROOT/Backend/apptainer/backend.def" ;;
    ingesta) def="$ROOT/Backend/apptainer/ingesta.def" ;;
    agentes) def="$ROOT/Agents/apptainer/agentes.def" ;;
    frontend) def="$ROOT/Frontend/apptainer/frontend.def" ;;
  esac
  source_newer "$image" "$def" && return 0
  case "$name" in
    postgres) source_newer "$image" "$ROOT/Backend/db/init" ;;
    backend) source_newer "$image" "$ROOT/Backend/api" || source_newer "$image" "$ROOT/shared/arsoft_http.py" ;;
    ingesta) source_newer "$image" "$ROOT/Backend/ingesta" || source_newer "$image" "$ROOT/Backend/db/init/01_conocimiento.sql" ;;
    agentes) source_newer "$image" "$ROOT/Agents" || source_newer "$image" "$ROOT/shared/arsoft_http.py" ;;
    frontend) source_newer "$image" "$ROOT/Frontend" ;;
  esac
}
instance_list() { apptainer instance list 2>/dev/null || true; }

cleanup() {
  status=$?
  trap - EXIT INT TERM
  if (( OWN_AGENTS )); then apptainer instance stop arsoft-agentes >/dev/null 2>&1 || true; fi
  if (( OWN_API )); then apptainer instance stop arsoft-api >/dev/null 2>&1 || true; fi
  if (( OWN_DB )); then apptainer instance stop arsoft-db >/dev/null 2>&1 || true; fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  cat <<'HELP'
Uso: bash apptainer/start-all.sh

Construye imágenes ausentes, inicia PostgreSQL, Backend y Agentes, ejecuta
la ingesta si encuentra PDF nuevos y abre el Frontend conectado. Ctrl+C
cierra el Frontend y detiene solo las instancias que inició este comando.

Variables: ARSOFT_MANUALES_DIR, ARSOFT_INGESTA=auto|siempre|nunca,
ARSOFT_IMAGES_DIR, ARSOFT_STATE_DIR, ARSOFT_LOCAL_ENV, ARSOFT_AGENTS_ENV,
ARSOFT_SEED_DEV_USERS=0.
HELP
  exit 0
fi
[[ "$#" -eq 0 ]] || fail "No se admiten argumentos. Usa --help para ver la configuración."
for bin in apptainer curl python3 openssl sha256sum; do
  command -v "$bin" >/dev/null 2>&1 || fail "No encuentro '$bin' en Ubuntu."
done
display="$(printenv DISPLAY || true)"
[[ -n "$display" ]] || fail "No hay DISPLAY. Ejecuta el comando en Ubuntu con WSLg o una sesión gráfica X11."

mkdir -p "$CONFIG_DIR" "$(dirname "$ENV_FILE")" "$(dirname "$AGENTS_ENV")"
chmod 700 "$CONFIG_DIR"

# En una instalación nueva se generan secretos locales una sola vez. Nunca se imprimen.
if [[ ! -f "$ENV_FILE" ]]; then
  service_token="$(openssl rand -hex 32)"
  postgres_password="$(openssl rand -hex 32)"
  jwt_secret="$(openssl rand -hex 32)"
  cat > "$ENV_FILE" <<EOF
# Generado por apptainer/start-all.sh. Solo para desarrollo local.
POSTGRES_USER=arsoft
POSTGRES_DB=arsoft
POSTGRES_PASSWORD=$postgres_password
AGENTES_URL=http://127.0.0.1:8001
ARSOFT_SERVICE_TOKEN=$service_token
ARSOFT_JWT_SECRET=$jwt_secret
ARSOFT_SEED_DEV_USERS=1
ARSOFT_INGESTA=auto
EOF
  chmod 600 "$ENV_FILE"
  log "Configuración local creada en $ENV_FILE."
fi
# Acepta los finales CRLF que pueden tener archivos editados desde Windows.
chmod 600 "$ENV_FILE"
# shellcheck disable=SC1090
source <(sed 's/\r$//' "$ENV_FILE")
if [[ -z "$POSTGRES_PASSWORD" || "$POSTGRES_PASSWORD" == "CAMBIAR_ANTES_DE_USAR" ]]; then
  POSTGRES_PASSWORD="$(openssl rand -hex 32)"
  set_env_value "$ENV_FILE" POSTGRES_PASSWORD "$POSTGRES_PASSWORD"
fi
if [[ -z "$ARSOFT_SERVICE_TOKEN" ]]; then
  ARSOFT_SERVICE_TOKEN="$(openssl rand -hex 32)"
  set_env_value "$ENV_FILE" ARSOFT_SERVICE_TOKEN "$ARSOFT_SERVICE_TOKEN"
fi
if [[ -z "$ARSOFT_JWT_SECRET" ]]; then
  ARSOFT_JWT_SECRET="$(openssl rand -hex 32)"
  set_env_value "$ENV_FILE" ARSOFT_JWT_SECRET "$ARSOFT_JWT_SECRET"
fi
chmod 600 "$ENV_FILE"
[[ -n "$POSTGRES_USER" ]] || fail "Falta POSTGRES_USER en $ENV_FILE."
[[ -n "$POSTGRES_DB" ]] || fail "Falta POSTGRES_DB en $ENV_FILE."
[[ -n "$POSTGRES_PASSWORD" && "$POSTGRES_PASSWORD" != "CAMBIAR_ANTES_DE_USAR" ]] ||
  fail "Configura POSTGRES_PASSWORD en $ENV_FILE."
[[ -n "$ARSOFT_SERVICE_TOKEN" ]] || fail "Falta ARSOFT_SERVICE_TOKEN en $ENV_FILE."
LOCAL_SERVICE_TOKEN="$ARSOFT_SERVICE_TOKEN"
SEED_USERS="$ARSOFT_SEED_DEV_USERS"
[[ -n "$SEED_USERS" ]] || SEED_USERS=1
[[ -n "$ARSOFT_INGESTA" ]] && INGESTA_MODE="$ARSOFT_INGESTA"
[[ -n "$ARSOFT_MANUALES_DIR" ]] && MANUALES="$ARSOFT_MANUALES_DIR"

if [[ ! -f "$AGENTS_ENV" ]]; then
  cat > "$AGENTS_ENV" <<EOF
# Generado por apptainer/start-all.sh. Edita Ollama/modelo si usas otros valores.
ARSOFT_SERVICE_TOKEN=$LOCAL_SERVICE_TOKEN
OLLAMA_URL=http://127.0.0.1:11434/v1
OLLAMA_MODEL=qwen2.5:14b
USE_REAL_AGENT2=1
AGENT2_BACKEND_BASE_URL=http://127.0.0.1:8000
ARSOFT_ENV=production
EOF
  chmod 600 "$AGENTS_ENV"
  log "Configuración de Agentes creada en $AGENTS_ENV."
fi
chmod 600 "$ENV_FILE" "$AGENTS_ENV"
# shellcheck disable=SC1090
source <(sed 's/\r$//' "$AGENTS_ENV")
if [[ -z "$ARSOFT_SERVICE_TOKEN" ]]; then
  ARSOFT_SERVICE_TOKEN="$LOCAL_SERVICE_TOKEN"
  set_env_value "$AGENTS_ENV" ARSOFT_SERVICE_TOKEN "$LOCAL_SERVICE_TOKEN"
  source <(sed 's/\r$//' "$AGENTS_ENV")
fi
chmod 600 "$AGENTS_ENV"
[[ "$ARSOFT_SERVICE_TOKEN" == "$LOCAL_SERVICE_TOKEN" ]] ||
  fail "ARSOFT_SERVICE_TOKEN debe coincidir en $ENV_FILE y $AGENTS_ENV."
ARSOFT_SERVICE_TOKEN="$LOCAL_SERVICE_TOKEN"
[[ -n "$OLLAMA_URL" ]] || OLLAMA_URL=http://127.0.0.1:11434/v1
[[ -n "$OLLAMA_MODEL" ]] || OLLAMA_MODEL=qwen2.5:14b
[[ -n "$AGENT2_BACKEND_BASE_URL" ]] || AGENT2_BACKEND_BASE_URL=http://127.0.0.1:8000
case "$INGESTA_MODE" in auto|siempre|nunca) ;; *) fail "ARSOFT_INGESTA debe ser auto, siempre o nunca." ;; esac
case "$SEED_USERS" in
  1|true|yes|si|sí) SEED_USERS=1 ;;
  0|false|no) SEED_USERS=0 ;;
  *) fail "ARSOFT_SEED_DEV_USERS debe ser 1 o 0." ;;
esac

source "$HERE/database-url.sh"
mkdir -p "$IMAGES" "$STATE/agents/huggingface" "$STATE/agents/state" \
  "$STATE/ingesta/salida" "$STATE/cache/huggingface"
chmod 700 "$STATE/agents/state"

# Construye solo las imágenes ausentes. Apptainer ejecuta el %test al final del build.
missing=""
for name in postgres backend ingesta agentes frontend; do
  if needs_rebuild "$name"; then missing="$missing $name"; fi
done
if [[ -n "$missing" ]]; then
  log "Construyendo imágenes ausentes o desactualizadas:$missing (puede tardar)."
  (cd "$ROOT" && ARSOFT_IMAGES_DIR="$IMAGES" bash apptainer/build-all.sh $missing)
fi
for name in postgres backend ingesta agentes frontend; do
  [[ -f "$IMAGES/$name.sif" ]] || fail "No se generó $IMAGES/$name.sif."
done

before="$(instance_list)"
if ! ARSOFT_LOCAL_ENV="$ENV_FILE" ARSOFT_IMAGES_DIR="$IMAGES" ARSOFT_STATE_DIR="$STATE" \
     bash "$HERE/start-local.sh"; then
  after="$(instance_list)"
  if ! has_instance arsoft-db "$before" && has_instance arsoft-db "$after"; then OWN_DB=1; fi
  if ! has_instance arsoft-api "$before" && has_instance arsoft-api "$after"; then OWN_API=1; fi
  exit 1
fi
after="$(instance_list)"
if ! has_instance arsoft-db "$before" && has_instance arsoft-db "$after"; then OWN_DB=1; fi
if ! has_instance arsoft-api "$before" && has_instance arsoft-api "$after"; then OWN_API=1; fi

# La ingesta es un proceso puntual. Sin PDF, el stack básico sigue arrancando.
pdf_found=0
if [[ -d "$MANUALES" ]] && find "$MANUALES" -type f -iname '*.pdf' -print -quit | grep -q .; then
  pdf_found=1
fi
active_index="$(APPTAINERENV_PGPASSWORD="$POSTGRES_PASSWORD" apptainer exec --cleanenv instance://arsoft-db psql -X -w -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT EXISTS (SELECT 1 FROM conocimiento.indice_version WHERE activo)" 2>/dev/null || true)"
marker="$STATE/ingesta/.corpus.sha256"
if (( pdf_found )) && [[ "$INGESTA_MODE" != "nunca" ]]; then
  fingerprint="$(find "$MANUALES" -type f -iname '*.pdf' -print0 | sort -z | xargs -0 -r sha256sum | sha256sum | awk '{print $1}')"
  previous=""
  [[ -f "$marker" ]] && previous="$(cat "$marker")"
  if [[ "$INGESTA_MODE" == "siempre" || "$fingerprint" != "$previous" || "$active_index" != "t" ]]; then
    log "Ejecutando ingesta de los PDF encontrados en $MANUALES."
    ARSOFT_LOCAL_ENV="$ENV_FILE" ARSOFT_IMAGES_DIR="$IMAGES" ARSOFT_STATE_DIR="$STATE" \
      ARSOFT_MANUALES_DIR="$MANUALES" bash "$HERE/run-ingesta.sh"
    printf '%s\n' "$fingerprint" > "$marker"
  else
    log "Los PDF no han cambiado; se conserva la ingesta existente."
  fi
elif (( pdf_found )); then
  log "Ingesta desactivada con ARSOFT_INGESTA=nunca."
else
  log "No hay PDF en $MANUALES; se omite la ingesta. El RAG necesitará documentos para responder."
fi

if (( SEED_USERS )); then
  log "Preparando usuarios locales de desarrollo."
  APPTAINERENV_DATABASE_URL="$DATABASE_URL" \
    apptainer exec --cleanenv instance://arsoft-api python -m app.usuarios_prueba --desarrollo
fi

if ! has_instance arsoft-agentes "$(instance_list)"; then
  export APPTAINERENV_ARSOFT_SERVICE_TOKEN="$LOCAL_SERVICE_TOKEN"
  export APPTAINERENV_OLLAMA_URL="$OLLAMA_URL"
  export APPTAINERENV_OLLAMA_MODEL="$OLLAMA_MODEL"
  export APPTAINERENV_USE_REAL_AGENT2=1
  export APPTAINERENV_AGENT2_BACKEND_BASE_URL="$AGENT2_BACKEND_BASE_URL"
  agent_environment="$ARSOFT_ENV"
  [[ -n "$agent_environment" ]] || agent_environment=production
  export APPTAINERENV_ARSOFT_ENV="$agent_environment"
  if [[ "$ARSOFT_APPTAINER_GPU" == "1" ]]; then
    log "Iniciando Agentes con GPU."
    apptainer instance start --nv --cleanenv --bind "$STATE/agents:/models" \
      "$IMAGES/agentes.sif" arsoft-agentes
  else
    log "Iniciando Agentes."
    apptainer instance start --cleanenv --bind "$STATE/agents:/models" \
      "$IMAGES/agentes.sif" arsoft-agentes
  fi
  OWN_AGENTS=1
fi
unset APPTAINERENV_ARSOFT_SERVICE_TOKEN APPTAINERENV_OLLAMA_URL APPTAINERENV_OLLAMA_MODEL \
  APPTAINERENV_USE_REAL_AGENT2 APPTAINERENV_AGENT2_BACKEND_BASE_URL APPTAINERENV_ARSOFT_ENV

agent_auth="Authorization: Bearer $LOCAL_SERVICE_TOKEN"
ready=0
for ((attempt=1; attempt<=60; attempt++)); do
  if curl --max-time 2 -fsS -H "$agent_auth" http://127.0.0.1:8001/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
(( ready )) || fail "Los Agentes no responden en /health; revisa la instancia arsoft-agentes."

if (( SEED_USERS )); then
  log "Comprobando login e historial del Backend."
  login_json="$(curl --max-time 10 -fsS -H 'Content-Type: application/json' \
    -d '{"usuario":"usuario1","contrasena":"usuario123"}' http://127.0.0.1:8000/auth/login)"
  login_token="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<< "$login_json")"
  [[ -n "$login_token" ]] || fail "El login de usuario1 no devolvió token."
  curl --max-time 10 -fsS -H "Authorization: Bearer $login_token" \
    http://127.0.0.1:8000/chats |
    python3 -c 'import json,sys; data=json.load(sys.stdin); assert isinstance(data.get("chats"), list)'
  log "Login e historial responden correctamente."
else
  log "No se sembraron usuarios demo; se omite la comprobación automática de login."
fi

log "Comprobando que la imagen del Frontend alcanza al Backend."
frontend_timeout="$(printenv ARSOFT_TIMEOUT_S || true)"
[[ -n "$frontend_timeout" ]] || frontend_timeout=120
apptainer exec --cleanenv --env QT_QPA_PLATFORM=offscreen \
  --env ARSOFT_MODO=real --env ARSOFT_API_URL=http://127.0.0.1:8000 \
  --pwd /opt/arsoft/frontend "$IMAGES/frontend.sif" python -c \
  'import config, urllib.request; assert config.MODO == "real" and config.API_URL == "http://127.0.0.1:8000"; assert urllib.request.urlopen(config.API_URL + "/health", timeout=3).status == 200; print("Frontend conectado al Backend")'

log "Abriendo el Frontend en modo real. Cierra la ventana o pulsa Ctrl+C para terminar."
ARSOFT_MODO=real ARSOFT_API_URL=http://127.0.0.1:8000 ARSOFT_TIMEOUT_S="$frontend_timeout" \
  bash "$HERE/run-frontend.sh"
