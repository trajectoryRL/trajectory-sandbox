#!/bin/sh
# Claude Code harness entrypoint.
#
# Contract (set by HarnessContainer.start in trajrl_bench/containers.py):
#   SANDBOX_SSH_HOST / SANDBOX_SSH_PORT / SANDBOX_SSH_USER / SANDBOX_SSH_PRIVATE_KEY
#   LLM_API_KEY                 — Anthropic API key (sk-ant-*)
#   LLM_BASE_URL                — https://api.anthropic.com (default)
#   LLM_MODEL                   — claude-sonnet-4-6
#   UNIVERSAL_PROMPT / IPTABLES_SETUP / WORKSPACE_DIR
#
# The universal prompt tells Claude to SSH into the sandbox for all work.
# Claude's Bash tool runs `ssh agent@sandbox "<cmd>"` verbatim — no shim,
# no filesystem bridge, nothing to trap its internal subprocess calls.
set -e

echo "[cc-harness] starting (model=$LLM_MODEL)"

# Write the SSH key readable by the cc user we drop to.
echo "$SANDBOX_SSH_PRIVATE_KEY" > /tmp/id_ed25519
chmod 600 /tmp/id_ed25519
chown cc:cc /tmp/id_ed25519

eval "$IPTABLES_SETUP" 2>/dev/null || true

# Wait for the sandbox sshd to accept connections. Probe as cc (same user
# Claude will run as) so key perms / DNS visibility get checked together.
# Use the `if` form to keep a failing probe from tripping `set -e`.
ssh_ready=0
last_probe_out=""
last_probe_rc=0
# 30 iterations × (2s ConnectTimeout + 1s sleep) ≈ 90s budget. 15 iterations
# left ~46s of wall-clock which was racy under Docker network churn between
# episodes (see Run 3 openclaw+vanilla ep1 / claudecode+pskoett ep0).
for i in $(seq 1 30); do
    if probe_out=$(gosu cc ssh \
            -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
            -o ConnectTimeout=2 -o BatchMode=yes \
            -i /tmp/id_ed25519 -p "${SANDBOX_SSH_PORT:-22}" \
            "${SANDBOX_SSH_USER:-agent}@${SANDBOX_SSH_HOST}" true 2>&1)
    then
        ssh_ready=1
        echo "[cc-harness] sandbox ssh ready after ${i}s"
        break
    fi
    last_probe_rc=$?
    last_probe_out="$probe_out"
    if [ "$i" = "1" ] || [ "$i" = "10" ] || [ "$i" = "20" ] || [ "$i" = "30" ]; then
        echo "[cc-harness] ssh probe #${i} rc=$last_probe_rc: $last_probe_out"
    fi
    sleep 1
done
if [ "$ssh_ready" != "1" ]; then
    echo "[cc-harness] FATAL: sandbox ssh never became ready"
    echo "[cc-harness] last probe: rc=$last_probe_rc out=$last_probe_out"
    echo "[cc-harness] resolving sandbox hostname:"
    getent hosts sandbox || echo "(sandbox not resolvable)"
    getent hosts "$SANDBOX_SSH_HOST" || echo "($SANDBOX_SSH_HOST not resolvable)"
    exit 1
fi

# Make sure cc's ssh known_hosts dir exists so ssh won't warn on first use.
mkdir -p /home/cc/.ssh
chown cc:cc /home/cc/.ssh

# /workspace is auto-created as root:root by Docker (from working_dir= in
# containers.create). Stage files that the outer runner put_archive'd into
# /workspace (JUDGE.md / JUDGE_TASK.md when this container is a judge, or
# scenario files for a testee) to cc so claude can read AND write
# /workspace/evaluation.json during the judge pass.
if [ -d "${WORKSPACE_DIR:-/workspace}" ]; then
    chown -R cc:cc "${WORKSPACE_DIR:-/workspace}"
fi

echo "[cc-harness] launching claude -p as cc"
exec gosu cc env \
    ANTHROPIC_API_KEY="$LLM_API_KEY" \
    ANTHROPIC_BASE_URL="${LLM_BASE_URL:-https://api.anthropic.com}" \
    HOME=/home/cc \
    claude -p "$UNIVERSAL_PROMPT" \
        --model "$LLM_MODEL" \
        --dangerously-skip-permissions
