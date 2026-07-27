#!/bin/bash
# Bring up a fresh PostgreSQL server with pg_stat_statements preloaded and
# log_statement=all, then create `customers_db` and the extension. Baked into
# the image and used IDENTICALLY by the agent (development) and the verifier
# (grading), so the DB the agent targets is byte-for-byte the one that scores.
#
# postgres refuses to run as root: this script hard-requires a non-root user.
#   verifier (test.sh runs as root):  su postgres -c "bash /usr/local/bin/pg-up.sh"
#   agent    (runs as hermes):        bash /usr/local/bin/pg-up.sh
set -euo pipefail

if [ "$(id -u)" = "0" ]; then
  echo "pg-up.sh must not run as root; invoke via: su postgres -c 'bash /usr/local/bin/pg-up.sh'" >&2
  exit 1
fi

PGBIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)"
[ -n "$PGBIN" ] || { echo "no postgresql server binaries found under /usr/lib/postgresql" >&2; exit 1; }
export PGDATA=/tmp/pgdata
LOG=/tmp/pg.log

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  rm -rf "$PGDATA"; mkdir -p "$PGDATA"
  # -A trust => 127.0.0.1 connections are trusted (tests pass an ignored password);
  # -U postgres => superuser role is `postgres` regardless of the OS user.
  "$PGBIN/initdb" -D "$PGDATA" -A trust -U postgres >/dev/null
  {
    echo "shared_preload_libraries = 'pg_stat_statements'"
    echo "log_statement = 'all'"
    echo "pg_stat_statements.track = 'all'"
    echo "pg_stat_statements.track_utility = on"   # so COPY (a utility stmt) is recorded
    echo "listen_addresses = '127.0.0.1'"
    echo "port = 5432"
    echo "unix_socket_directories = '/tmp'"
  } >> "$PGDATA/postgresql.conf"
fi

"$PGBIN/pg_ctl" -D "$PGDATA" -l "$LOG" -w -t 60 start || true

for i in $(seq 1 30); do
  "$PGBIN/pg_isready" -h 127.0.0.1 -p 5432 >/dev/null 2>&1 && break
  sleep 1
done

"$PGBIN/psql" -h 127.0.0.1 -p 5432 -U postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='customers_db'" | grep -q 1 \
  || "$PGBIN/createdb" -h 127.0.0.1 -p 5432 -U postgres \
       --encoding=UTF8 --template=template0 --lc-collate=C --lc-ctype=C customers_db
"$PGBIN/psql" -h 127.0.0.1 -p 5432 -U postgres -d customers_db \
  -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;" >/dev/null

echo "postgres ready: 127.0.0.1:5432 db=customers_db (pg_stat_statements preloaded)"
