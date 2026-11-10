#!/bin/bash
# db/init.sh
# Executed by PostgreSQL's docker-entrypoint as the very first init script.
# Runs all *.sql files in the sub-directories in the correct order so that
# Docker's default mechanism (which only picks up files directly in
# /docker-entrypoint-initdb.d/) does not have to be patched.
set -e

for dir in migrations triggers procedures views seed; do
  dir_path="/docker-entrypoint-initdb.d/${dir}"
  if [ -d "$dir_path" ]; then
    for f in "$dir_path"/*.sql; do
      [ -f "$f" ] || continue
      echo "[init.sh] Running $f ..."
      psql -v ON_ERROR_STOP=1 \
           --username "$POSTGRES_USER" \
           --dbname   "$POSTGRES_DB" \
           -f "$f"
    done
  fi
done
