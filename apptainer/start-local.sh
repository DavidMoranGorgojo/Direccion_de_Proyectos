#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ARSOFT_LOCAL_ENV:-$HERE/.env.local}"
IMAGES="${ARSOFT_IMAGES_DIR:-$HOME/arsoft-images}"
STATE="${ARSOFT_STATE_DIR:-$HOME/arsoft-state}"
[[ -f "$ENV_FILE" ]] || { echo "Falta $ENV_FILE. Copia .env.local.example y configura PostgreSQL." >&2; exit 2; }
source "$ENV_FILE"
: "${POSTGRES_USER:?Configura POSTGRES_USER}"
: "${POSTGRES_DB:?Configura POSTGRES_DB}"
if [[ -z "${POSTGRES_PASSWORD:-}" || "$POSTGRES_PASSWORD" == CAMBIAR_ANTES_DE_USAR ]]; then
  echo 'Configura POSTGRES_PASSWORD en el archivo de entorno local' >&2
  exit 2
fi
: "${ARSOFT_SERVICE_TOKEN:?Configura ARSOFT_SERVICE_TOKEN en el archivo local de entorno}"
for name in postgres backend; do
  [[ -f "$IMAGES/$name.sif" ]] || { echo "Falta $IMAGES/$name.sif" >&2; exit 2; }
done
mkdir -p "$STATE/postgres" "$STATE/postgres-run"
chmod 700 "$STATE/postgres" "$STATE/postgres-run"

instances="$(apptainer instance list)"
if ! grep -q '^arsoft-db[[:space:]]' <<< "$instances"; then
  APPTAINERENV_POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256 \
  APPTAINERENV_POSTGRES_USER="$POSTGRES_USER" \
  APPTAINERENV_POSTGRES_DB="$POSTGRES_DB" \
  APPTAINERENV_POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    apptainer instance start --cleanenv \
      --bind "$STATE/postgres-run:/var/run/postgresql" \
      --bind "$STATE/postgres:/var/lib/postgresql/data" "$IMAGES/postgres.sif" arsoft-db
fi

for attempt in {1..40}; do
  if APPTAINERENV_PGPASSWORD="$POSTGRES_PASSWORD" apptainer exec --cleanenv instance://arsoft-db \
      psql -X -w -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc \
      "SELECT to_regclass('conocimiento.chunk') IS NOT NULL AND EXISTS (SELECT FROM pg_extension WHERE extname = 'vector')" 2>/dev/null | grep -qx t; then
    break
  fi
  if (( attempt == 40 )); then
    echo 'PostgreSQL no acepta las credenciales o falta el esquema. Revisa los logs de arsoft-db.' >&2
    exit 1
  fi
  sleep 2
done

if ! grep -q '^arsoft-api[[:space:]]' <<< "$instances"; then
  APPTAINERENV_ARSOFT_SERVICE_TOKEN="${ARSOFT_SERVICE_TOKEN:-}" \
  APPTAINERENV_DATABASE_URL="${DATABASE_URL:-}" \
  APPTAINERENV_AGENTES_URL="${AGENTES_URL:-http://127.0.0.1:8001}" \
    apptainer instance start --cleanenv "$IMAGES/backend.sif" arsoft-api
fi
for attempt in {1..20}; do
  if curl --max-time 2 -fsS http://127.0.0.1:8000/health 2>/dev/null; then
    printf '\n'
    exit 0
  fi
  sleep 1
done
echo 'FastAPI no responde en /health. Revisa los logs de arsoft-api.' >&2
exit 1
