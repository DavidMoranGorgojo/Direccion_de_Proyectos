#!/usr/bin/env bash
set -euo pipefail
instances="$(apptainer instance list)"
for name in arsoft-api arsoft-db; do
  if grep -q "^${name}[[:space:]]" <<< "$instances"; then
    apptainer instance stop "$name"
  fi
done
