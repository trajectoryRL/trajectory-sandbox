#!/bin/bash

# Install curl
apt-get update
apt-get install -y curl

# Install uv
curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh

source $HOME/.local/bin/env

# Check if we're in a valid working directory
if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set. Please set a WORKDIR in your Dockerfile before running this script."
    exit 1
fi

# Stand up the agent's recovery before running tests. The agent's
# script (extracted from /app/recovery.sh in their container, then
# injected into this fresh verifier container by the validator) is
# now sitting at /app/recovery.sh. The fresh verifier container
# starts in the same broken state the agent saw thanks to the
# scenario image baking it in at build time. We run the script
# from /app/personal-site (the working dir an agent would naturally
# operate from) and capture its log for debugging.
mkdir -p /logs/verifier
RECOVERY_LOG=/logs/verifier/recovery.log

# Verifier user lacks a default git identity; provide one so any
# git commit/merge inside recovery.sh succeeds.
git config --global user.email "verifier@trajrl.local" || true
git config --global user.name "trajrl-verifier" || true
# /app/personal-site is owned by uid 10000 (agent) but test.sh runs
# as root, so plain git refuses with "dubious ownership". Whitelist
# the repo so the recovery.sh git commands succeed.
git config --global --add safe.directory /app/personal-site || true

echo "==> running agent recovery.sh" | tee -a "$RECOVERY_LOG"
if [ -f /app/recovery.sh ]; then
    (cd /app/personal-site && bash /app/recovery.sh) 2>&1 | tee -a "$RECOVERY_LOG"
    RECOVERY_EXIT=${PIPESTATUS[0]}
    echo "==> recovery.sh exited $RECOVERY_EXIT" | tee -a "$RECOVERY_LOG"
else
    echo "==> /app/recovery.sh missing — agent produced no output" | tee -a "$RECOVERY_LOG"
fi

uvx \
  -p 3.13 \
  -w pytest==8.4.1 \
  -w pytest-json-ctrf==0.3.5 \
  pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA


if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
