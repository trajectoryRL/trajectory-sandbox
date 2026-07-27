# Adapted from terminal-bench large-scale-text-editing. Layered on
# sandbox-agent so the agent runs in this image directly (trajrl-bench
# option-1 architecture); inherits Hermes + the hermes user (uid 10000).
#
# The build COPYs gen_large_csv.py (which must live under environment/,
# because the scenario image's build context is scenarios/<name>/environment)
# and bakes BOTH /app/input.csv and /app/expected.csv (1M rows each) so the
# agent can inspect the source and the target, then removes the generator from
# /app. A second copy of the generator ships under tests/ and is mounted at
# /tests at grade time: tests/test.sh uses it to regenerate a FRESH, sanitary
# input.csv, and test_outputs.py uses it to generate expected.csv only AFTER
# the agent's vim script has run — so a pre-transformed input.csv or a planted
# output CSV left in /app is discarded before grading. vim is the only extra
# apt package (upstream installed exactly this).
FROM ghcr.io/trajectoryrl/sandbox-agent:latest

USER root

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        vim \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bake input.csv + expected.csv at build (gen_large_csv.py writes them relative
# to cwd, which WORKDIR fixes at /app), then remove the generator from /app so
# the agent cannot read it to reverse-engineer the transform.
COPY gen_large_csv.py /app/gen_large_csv.py
RUN python3 /app/gen_large_csv.py both \
 && rm /app/gen_large_csv.py

RUN chown -R hermes:hermes /app
