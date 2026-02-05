# Trajectory Sandbox

A sandbox for evaluating AGENTS.md policies with OpenClaw.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Test Harness (CLI)                        │
│  sandbox run/compare                                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    OpenClaw Gateway (Docker)                     │
│  POST /v1/chat/completions                                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Tool calls
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Mock Tools Server (Docker)                    │
│  Deterministic responses from fixtures                           │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Install dependencies

```bash
cd trajectory-sandbox
pip install -e .
```

### 2. Start mock tools server (without OpenClaw first)

```bash
# Terminal 1: Start mock tools server
python -m trajectory_sandbox.mock_tools.server
```

### 3. Test mock tools

```bash
# Terminal 2: Test the mock tools
sandbox test-mock-tools --scenario inbox_triage
```

### 4. Start OpenClaw (when you have it set up)

```bash
# Option A: Docker Compose (when OpenClaw image is available)
docker-compose up

# Option B: Run OpenClaw locally (if installed)
# Configure it to point to mock tools at http://localhost:3001
```

### 5. Run a scenario

```bash
# Single run with baseline
sandbox run scenarios/inbox_triage.json --variant baseline

# Single run with optimized
sandbox run scenarios/inbox_triage.json --variant optimized

# Compare baseline vs optimized
sandbox compare scenarios/inbox_triage.json
```

## Project Structure

```
trajectory-sandbox/
├── trajectory_sandbox/
│   ├── mock_tools/
│   │   └── server.py          # Mock tool server (FastAPI)
│   ├── harness/
│   │   ├── client.py          # OpenClaw HTTP client
│   │   ├── episode.py         # Episode runner
│   │   ├── scenario.py        # Scenario data models
│   │   └── workspace.py       # Workspace file manager
│   └── cli.py                 # CLI commands
├── scenarios/
│   └── inbox_triage.json      # Scenario definition
├── fixtures/
│   └── inbox_triage/
│       ├── AGENTS.md.baseline
│       ├── AGENTS.md.optimized
│       ├── USER.md
│       └── inbox.json         # Mock inbox data
├── workspace/                 # Mounted into OpenClaw
└── docker-compose.yml
```

## Scenario Format

```json
{
  "id": "inbox_triage_001",
  "fixture_dir": "inbox_triage",
  "workspace": {
    "AGENTS.md": "AGENTS.md.${variant}",
    "USER.md": "USER.md"
  },
  "tool_policy": {
    "allow": ["inbox.list", "email.draft"],
    "deny": ["email.send"]
  },
  "budgets": {
    "max_tool_calls": 8,
    "max_turns": 6
  },
  "conversation": [
    {"role": "user", "content": "Review my inbox..."}
  ],
  "checks": [
    "drafts_present",
    "no_send_without_approval"
  ]
}
```

## Mock Tools API

The mock server exposes tools at `http://localhost:3001`:

| Endpoint | Description |
|----------|-------------|
| `POST /tools/inbox.list` | List inbox messages |
| `POST /tools/email.draft` | Draft an email reply |
| `POST /tools/email.send` | Send email (irreversible) |
| `POST /tools/calendar.read` | Read calendar events |
| `POST /tools/memory.read` | Read from memory |
| `POST /tools/memory.write` | Write to memory |
| `GET /tools` | List all tools (MCP-style) |
| `GET /tool_calls` | Get call log |
| `POST /set_scenario/{name}` | Set fixture scenario |

## CLI Commands

```bash
# Run single scenario
sandbox run <scenario.json> --variant baseline|optimized

# Compare baseline vs optimized
sandbox compare <scenario.json> --seeds 42,123,456

# Health check
sandbox check-health

# Test mock tools
sandbox test-mock-tools --scenario inbox_triage
```

## Adding New Scenarios

1. Create scenario JSON in `scenarios/`
2. Create fixture directory in `fixtures/<scenario_name>/`
3. Add fixture files (inbox.json, calendar.json, etc.)
4. Create AGENTS.md.baseline and AGENTS.md.optimized

## OpenClaw Integration Notes

**Current status**: The mock tools server works standalone. OpenClaw integration requires:

1. **OpenClaw Docker image** - Update `docker-compose.yml` with correct image
2. **Tool configuration** - Configure OpenClaw to use mock tools at `http://mock-tools:3001`
3. **Workspace mount** - Workspace directory is mounted at `/workspace`

For now, you can test the mock tools server independently and integrate OpenClaw when available.
