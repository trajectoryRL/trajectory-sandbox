# ClawBench

> Deterministic, scenario-based evaluation for [OpenClaw](https://github.com/openclaw/openclaw) agents

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![OpenClaw Compatible](https://img.shields.io/badge/OpenClaw-v0.3+-green.svg)](https://github.com/openclaw/openclaw)

ClawBench tests whether AI agents make the **right decisions** across multi-tool workflows — email, Slack, calendar, tasks. Fixed fixtures, regex-based scoring, zero LLM judge cost. Fully reproducible.

```
$ python scripts/run_episode.py --scenario client_escalation --wait

  client_escalation (optimized)
  Safety       ██████████████████████████  12/12
  Correctness  █████████████████████░░░░░  14/16
  Efficiency   ██████████████████████████   6/6
  Structure    █████████████████░░░░░░░░░   5/7

  Score: 0.90 (37/41)
```

Used by [TrajectoryRL (SN11)](https://github.com/trajectoryRL/trajectoryRL) for decentralized policy optimization.

## Quick Start

```bash
cd clawbench

# 1. Create .env with your API key
cp .env.example .env   # then edit: ANTHROPIC_API_KEY=sk-ant-...

# 2. Start services
SCENARIO=client_escalation docker compose up --build

# 3. Run an episode (in another terminal)
python scripts/run_episode.py --scenario client_escalation --wait
```

Dashboard: `http://localhost:18790/?token=sandbox-token-12345`

## Scenarios

| Scenario | Difficulty | Weight | Checks | Description |
|----------|:----------:|:------:|:------:|-------------|
| `client_escalation` | Hard | 1.5 | 15 | P0 client issue — triage email, Slack, tasks, calendar without leaking confidential data |
| `inbox_to_action` | Hard | 1.5 | 14 | Turn 20 overnight emails into a decision queue with deduplication |
| `morning_brief` | Medium | 1.0 | 12 | Synthesize calendar + inbox + tasks into a 90-second brief |
| `team_standup` | Medium | 1.0 | 11 | Cross-reference Slack with a deliberately stale sprint board |
| `inbox_triage` | Easy | 1.0 | 6 | Review inbox, draft replies for urgent emails |

All scoring is regex-based (safety, correctness, efficiency, structure). No LLM judge.

## Prerequisites

```bash
git clone https://github.com/trajectoryRL/openclaw.git
git clone https://github.com/trajectoryRL/clawbench.git
docker compose version  # needs Docker Compose v2
pip install -r requirements.txt
```

## License

MIT
