# trajrl-bench

Shell-verifier scenarios + a unified sandbox+agent image, used by [TrajectoryRL](https://github.com/trajectoryRL/trajectoryRL) validators (Bittensor SN11) to score miner SKILL.md submissions.

## Architecture (2026-05)

One **sandbox-agent container** per eval session holds the puzzle filesystem (`/app` injected per-session from a per-scenario environment image) and runs Hermes as the `agent` user. The validator drives episodes via `docker exec -u agent` — no testee container, no SSH boundary between agent and puzzle.

After each episode, a one-shot **verifier container** runs the scenario's `tests/test.sh` against the agent's output and writes a binary 0/1 reward to `/logs/verifier/reward.txt`.

```
┌───────────────────────────────┐    ┌────────────────────────────┐
│ ghcr.io/trajectoryrl/         │    │ ghcr.io/trajectoryrl/      │
│   sandbox-agent:<tag>         │    │   scenario-<name>:<tag>    │
│ ┌─────────────────────────┐   │    │ /app/<reference data>      │
│ │ /workspace/SKILL.md     │   │    │ tests/test.sh              │
│ │ /workspace/INSTRUCTION  │   │    │ tests/test_outputs.py      │
│ │ /workspace/learned/     │   │    └────────────────────────────┘
│ │ /app/  (injected)       │   │              ↑
│ └─────────────────────────┘   │              │ run as one-shot
│   ↑ docker exec hermes        │              │ verifier container
│   │ as agent (uid 10000)      │              │ per episode
└───────────────────────────────┘              │
        │                                      │
        └─→ writes /app/<output> ──────────────┘
```

## Adopted scenarios

All scenarios are [Terminal-Bench](https://github.com/laude-institute/terminal-bench)-format `shell_verifier` tasks. Each lives at `scenarios/<name>/` with the standard layout:

```
scenarios/<name>/
  task.toml              # metadata, verifier timeout, agent_output_path
  instruction.md         # static task statement
  environment/
    Dockerfile           # built into ghcr.io/trajectoryrl/scenario-<name>
  tests/
    test.sh              # verifier — exits 0/1, writes reward.txt
    test_outputs.py      # pytest assertions
  solution/
    solve.sh             # reference solution (not used at eval time)
```

Provenance + license tracked per scenario in `scenarios/<name>/DESIGN.md` (when present) and aggregated in [`NOTICE`](NOTICE) / [`THIRD_PARTY_LICENSES`](THIRD_PARTY_LICENSES).

Currently published:

- `break-filter-js-from-html` (software-engineering, hard)
- `cancel-async-tasks` (async/concurrency, hard)
- `log-summary-date-ranges` (data-processing, medium)

## CLI

The validator queries scenario metadata inside the sandbox image without importing trajrl-bench as a Python dep.

```bash
docker run --rm ghcr.io/trajectoryrl/sandbox-agent:latest \
    python -m trajrl_bench.cli scenarios

docker run --rm ghcr.io/trajectoryrl/sandbox-agent:latest \
    python -m trajrl_bench.cli scenario-info --scenario cancel-async-tasks
```

`scenario-info` returns one JSON blob per scenario: the image repo, `instruction.md` body, `agent_output_path`, `verifier_timeout_s`, and the contents of every file under `tests/` (base64). The validator drives a full session from that one payload.

## Build locally

```bash
make install                          # uv sync
make build                            # docker build sandbox-agent
make build-scenario SCENARIO=cancel-async-tasks
make test                             # pytest
```

## CI

`.github/workflows/ci.yml` runs unit tests on every PR. On tag push (`v*`) or manual workflow_dispatch it publishes:

- `ghcr.io/trajectoryrl/sandbox-agent:<tag>`
- `ghcr.io/trajectoryrl/scenario-<name>:<tag>` per scenario

Tag scheme matches the validator's pinning: `latest` / `vX.Y.Z` / `vX.Y` / `vX` / `staging`. A validator pinned to `sandbox-agent:vX.Y.Z` always gets the matching `scenario-<name>:vX.Y.Z`.

## Adopted from Terminal-Bench

Terminal-Bench tasks are MIT-licensed. Each adopted scenario notes its provenance in its own `DESIGN.md`.
