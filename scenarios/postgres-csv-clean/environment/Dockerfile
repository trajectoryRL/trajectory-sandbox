# Adapted from terminal-bench postgres-csv-clean. Upstream ran a 2-service
# docker-compose (an app `client` + a separate postgres:16 `db` service with
# shared_preload_libraries=pg_stat_statements / log_statement=all), and the
# tests inspected the db's pg_stat_statements for evidence that cleaning +
# client-side \COPY actually ran in postgres. trajrl-bench has no compose and a
# hard agent<->verifier container split across which postgres state does NOT
# survive, so the two services are folded into ONE image: postgres is installed
# here and started INSIDE the verifier by tests/test.sh, which then executes the
# agent's /app/clean.sh so the evidence lands in the verifier's own
# pg_stat_statements. See DESIGN.md.
FROM ghcr.io/trajectoryrl/sandbox-agent:latest

USER root

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        postgresql postgresql-contrib \
 && rm -rf /var/lib/apt/lists/*

# Agent convenience only (inspecting the data / the pandas negative test). The
# verifier's tests import psycopg2 (installed via uvx) and NOT pandas.
RUN pip3 install --break-system-packages --no-cache-dir \
        pandas==2.2.3 psycopg2-binary==2.9.10

WORKDIR /app

# Baked, agent-visible raw input. Only /app/clean.sh crosses the boundary, so
# the verifier grades against its own pristine copy of this file (re-pinned from
# /tests at grade time) regardless of anything the agent does to it.
RUN mkdir -p /app/data
COPY customers.csv /app/data/customers.csv

# Shared postgres bring-up (agent dev == verifier grade).
COPY pg-up.sh /usr/local/bin/pg-up.sh
RUN chmod +x /usr/local/bin/pg-up.sh

RUN chown -R hermes:hermes /app
