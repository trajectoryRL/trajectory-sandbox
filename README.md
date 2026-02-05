# Trajectory Sandbox

Sandbox for evaluating AGENTS.md policies with real OpenClaw.

## Prerequisites

Clone both repos as sibling directories:

```bash
git clone https://github.com/trajectoryRL/openclaw.git
git clone https://github.com/trajectoryRL/trajectory-sandbox.git
```

Expected layout:

```
your-workspace/
├── openclaw/                    # Fork: github.com/trajectoryRL/openclaw
│   ├── extensions/
│   │   └── trajectory-sandbox-tools/   # Mock tools plugin
│   ├── sandbox-config/
│   │   └── openclaw.json               # Pre-configured settings
│   └── Dockerfile.trajectory-sandbox   # Docker image
│
└── trajectory-sandbox/          # This repo
    ├── trajectory_sandbox/
    │   └── mock_tools/server.py        # Mock tool server
    ├── fixtures/
    │   └── inbox_triage/               # Test data + AGENTS.md variants
    ├── workspace/                      # Mounted into OpenClaw
    └── docker-compose.yml              # Runs everything
```

## Quick Start

```bash
cd trajectory-sandbox

# 1. Create .env from example
cp .env.example .env

# 2. Edit .env and add your API key
#    ANTHROPIC_API_KEY=sk-ant-...

# 3. Run with baseline AGENTS.md
./scripts/run.sh baseline

# Or with optimized AGENTS.md
./scripts/run.sh optimized
```

Dashboard: `http://localhost:18789/?token=sandbox-token-12345`

## Environment Variables (.env)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes* | - | Anthropic API key |
| `OPENAI_API_KEY` | Yes* | - | OpenAI API key |
| `OPENCLAW_GATEWAY_TOKEN` | No | `sandbox-token-12345` | Gateway auth token |
| `SCENARIO` | No | `inbox_triage` | Scenario fixtures to load |

*At least one API key required

## What's Pre-configured

The OpenClaw fork includes:

1. **Plugin** (`extensions/trajectory-sandbox-tools/`)
   - 6 mock tools: `inbox_list`, `email_draft`, `email_send`, `calendar_read`, `memory_read`, `memory_write`

2. **Config** (`sandbox-config/openclaw.json`)
   - Gateway: LAN bind, token auth, tailscale off
   - Tools: Built-in tools disabled, only mock tools allowed
   - Plugin: Enabled and configured

3. **Dockerfile** (`Dockerfile.trajectory-sandbox`)
   - Copies config to skip onboarding
   - Starts with `--allow-unconfigured`

## A/B Testing AGENTS.md

| Version | `inbox_list` calls | Safety |
|---------|-------------------|--------|
| Baseline | 2-3 | Violations possible |
| Optimized | 1 | No violations |

Check tool calls:
```bash
cat logs/inbox_triage_calls.jsonl
```

## Contributing

```bash
cd ../openclaw
git checkout -b trajectory-sandbox
git add .
git commit -m "Add trajectory-sandbox-tools plugin"
git push origin trajectory-sandbox
```
