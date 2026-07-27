#!/bin/bash
# Install curl + uv
apt-get update
apt-get install -y curl
curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh
source $HOME/.local/bin/env

if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set."
    exit 1
fi

mkdir -p /logs/verifier
cd /app

# 1. Re-pin the raw input from the verifier-only /tests copy. Only /app/clean.sh
#    crossed the agent->verifier boundary, so /app/data/customers.csv is already
#    the pristine image copy -- this restore makes the pin explicit and defends
#    against a clean.sh that would mutate it in place before importing.
mkdir -p /app/data
cp -f /tests/customers.csv /app/data/customers.csv

# 2. Start a FRESH postgres (pg_stat_statements preloaded + log_statement=all),
#    as the postgres OS user because the server refuses to run as root. Same
#    baked bring-up the agent developed against.
su postgres -c "bash /usr/local/bin/pg-up.sh" > /logs/verifier/pg-up.log 2>&1

# 3. Execute the AGENT'S deliverable so its cleaning + client-side \COPY queries
#    populate THIS verifier's pg_stat_statements. Guarded with `|| true`: a
#    broken clean.sh must not abort test.sh -- it just leaves no table / no CSV /
#    no evidence, and the DB and pg_stat cells fail.
if [ -f /app/clean.sh ]; then
  bash /app/clean.sh > /logs/verifier/clean-stdout.log 2>&1 || true
else
  echo "no /app/clean.sh delivered" > /logs/verifier/clean-stdout.log
fi

# 4. Place the hidden baseline AFTER clean.sh has run, so the agent's script can
#    never read or copy customers_v1.csv (defeats a cp-baseline shortcut).
cp -f /tests/customers_v1.csv /app/data/customers_v1.csv

# 5. Grade. 14 cells, all scored (no deselect). psycopg2-binary pinned to
#    upstream run-tests.sh's version; the tests import no pandas.
uvx \
  -p 3.13 \
  -w pytest==8.4.1 \
  -w pytest-json-ctrf==0.3.5 \
  -w psycopg2-binary==2.9.10 \
  pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
