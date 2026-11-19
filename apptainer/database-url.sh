#!/usr/bin/env bash
# Source after loading .env.local to validate credentials and derive the DSN.
: "${POSTGRES_USER:?Configura POSTGRES_USER}"
: "${POSTGRES_DB:?Configura POSTGRES_DB}"
if [[ -z "${POSTGRES_PASSWORD:-}" || "$POSTGRES_PASSWORD" == CAMBIAR_ANTES_DE_USAR ]]; then
  echo 'Configura POSTGRES_PASSWORD en el archivo de entorno local' >&2
  return 2
fi
export POSTGRES_USER POSTGRES_DB POSTGRES_PASSWORD
if ! DATABASE_URL="$("${ARSOFT_PYTHON_BIN:-python3}" -c 'import os, urllib.parse as u; q=lambda name: u.quote(os.environ[name], safe=""); print("postgresql://%s:%s@127.0.0.1:5432/%s" % (q("POSTGRES_USER"), q("POSTGRES_PASSWORD"), q("POSTGRES_DB")))')"; then
  echo 'No se pudo construir DATABASE_URL; se necesita Python 3 en el host.' >&2
  return 2
fi
export DATABASE_URL
