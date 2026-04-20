#!/bin/sh
# OpenClaw harness entrypoint.
#
# Contract (set by HarnessContainer.start in trajrl_bench/containers.py):
#   SANDBOX_SSH_HOST / SANDBOX_SSH_PORT / SANDBOX_SSH_USER / SANDBOX_SSH_PRIVATE_KEY
#   LLM_API_KEY                 — Anthropic API key (sk-ant-*)
#   LLM_BASE_URL                — https://api.anthropic.com (default)
#   LLM_MODEL                   — claude-sonnet-4-6
#   UNIVERSAL_PROMPT / IPTABLES_SETUP / WORKSPACE_DIR
#
# The universal prompt tells OpenClaw to SSH into the sandbox for all
# work. OpenClaw's `exec` tool runs shell commands; we just ssh explicitly
# from there — matching the Hermes / Claude Code explicit-SSH model.
set -e

echo "[oc-harness] starting (model=$LLM_MODEL)"

# SSH key readable by the oc user we drop to.
echo "$SANDBOX_SSH_PRIVATE_KEY" > /tmp/id_ed25519
chmod 600 /tmp/id_ed25519
chown oc:oc /tmp/id_ed25519

eval "$IPTABLES_SETUP" 2>/dev/null || true

# Wait for sandbox sshd to accept connections.
ssh_ready=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if gosu oc ssh \
        -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=2 -o BatchMode=yes \
        -i /tmp/id_ed25519 -p "${SANDBOX_SSH_PORT:-22}" \
        "${SANDBOX_SSH_USER:-agent}@${SANDBOX_SSH_HOST}" true 2>/dev/null
    then
        ssh_ready=1
        echo "[oc-harness] sandbox ssh ready after ${i}s"
        break
    fi
    sleep 1
done
if [ "$ssh_ready" != "1" ]; then
    echo "[oc-harness] FATAL: sandbox ssh never became ready"
    exit 1
fi

mkdir -p /home/oc/.ssh
chown oc:oc /home/oc/.ssh

# Overlay the real Anthropic API key onto the baked-in auth profile.
# Onboard ran at build time with a placeholder so the provider + agent
# state is already wired; this is the per-run key injection. Python
# used for safe JSON update (API keys may contain chars that break sed).
python3 - <<'PY'
import json, os
p = "/home/oc/.openclaw/agents/main/agent/auth-profiles.json"
with open(p) as f:
    data = json.load(f)
key = os.environ["LLM_API_KEY"]
for prof in data.get("profiles", {}).values():
    if prof.get("provider") == "anthropic":
        prof["key"] = key
with open(p, "w") as f:
    json.dump(data, f, indent=2)
PY
chown oc:oc /home/oc/.openclaw/agents/main/agent/auth-profiles.json

# Auto-created working_dir is root:root — let oc read any files the
# outer runner put_archive'd into /workspace (e.g. JUDGE.md / JUDGE_TASK.md
# when this container runs as a judge).
if [ -d "${WORKSPACE_DIR:-/workspace}" ]; then
    chown -R oc:oc "${WORKSPACE_DIR:-/workspace}"
fi

# Map the bench's model name to OpenClaw's provider/model format. The
# bench passes the Anthropic-native name (e.g. "claude-sonnet-4-6");
# OpenClaw expects a provider prefix ("anthropic/..."). When LLM_BASE_URL
# isn't Anthropic direct we pass the model through unchanged and let
# OpenClaw's provider auto-detection route it.
case "$LLM_BASE_URL" in
    *api.anthropic.com*)
        OC_MODEL="anthropic/$LLM_MODEL"
        ;;
    *)
        OC_MODEL="$LLM_MODEL"
        ;;
esac
gosu oc openclaw config set agents.defaults.model.primary "$OC_MODEL" >/dev/null 2>&1 || true
echo "[oc-harness] model pinned -> $OC_MODEL"

echo "[oc-harness] launching openclaw agent --local as oc"
# OpenClaw writes its agent run JSON + logs to stderr (stdout stays
# empty). trajrl-bench's transcript-capture reads stdout, so we merge
# stderr into stdout here — the testee's transcript + the judge's
# tool trace all end up on the stdout channel EvalSession reads.
# --timeout is wall-clock seconds (not a turn count); give it a generous
# budget, Docker's harness_timeout_s is the real guard.
exec gosu oc env \
    ANTHROPIC_API_KEY="$LLM_API_KEY" \
    HOME=/home/oc \
    openclaw agent --local --agent main \
        --message "$UNIVERSAL_PROMPT" \
        --thinking off \
        --json \
        --timeout 600 \
    2>&1
