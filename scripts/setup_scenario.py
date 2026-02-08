#!/usr/bin/env python3
"""
Setup a scenario for the trajectory sandbox.

Reads a scenario YAML config, generates the OpenClaw config with the
correct tool allow-list, and copies workspace files (AGENTS.md variant,
USER.md, etc.).

Usage:
    python scripts/setup_scenario.py inbox_triage baseline
    python scripts/setup_scenario.py --scenario inbox_triage --variant baseline
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

SANDBOX_DIR = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = SANDBOX_DIR / "scenarios"
FIXTURES_DIR = SANDBOX_DIR / "fixtures"
WORKSPACE_DIR = SANDBOX_DIR / "workspace"
GENERATED_DIR = SANDBOX_DIR / "generated"

# Corrected-schema mock tool names (matching real OpenClaw tool surface)
ALL_MOCK_TOOLS = [
    "slack",          # Single tool with action param (readMessages, sendMessage, etc.)
    "exec",           # Shell execution (pattern-matches himalaya/curl/gh commands)
    "memory_search",  # Semantic memory search
    "memory_get",     # Memory file read
    "web_search",     # Web search
    "web_fetch",      # Web page fetch
    "read",           # File read
]

# Built-in OpenClaw tools to deny (prevent real execution in sandbox)
DENY_TOOLS = [
    "process", "browser", "canvas", "nodes",
    "cron", "gateway", "apply_patch",
]

# Built-in OpenClaw tools to always allow alongside mock tools
ALWAYS_ALLOW = ["session_status"]

# Base OpenClaw config template
BASE_CONFIG = {
    "gateway": {
        "mode": "local",
        "bind": "lan",
        "port": 18789,
        "auth": {
            "mode": "token",
            "token": "sandbox-token-12345",
        },
        "tailscale": {"mode": "off"},
        "http": {
            "endpoints": {
                "chatCompletions": {"enabled": True},
            },
        },
    },
    "agents": {
        "defaults": {
            "workspace": "/workspace",
            "model": {
                "primary": "anthropic/claude-sonnet-4-5-20250929",
            },
        },
    },
    "plugins": {
        # Disable memory-core plugin so its memory_search/memory_get
        # don't conflict with the sandbox plugin's mock versions.
        "slots": {"memory": "none"},
        "entries": {
            "trajectory-sandbox-tools": {
                "enabled": True,
                "config": {
                    "mockServerUrl": "http://mock-tools:3001",
                    "scenario": "inbox_triage",
                },
            },
        },
    },
    "tools": {
        # Disable built-in web_search/web_fetch so they don't conflict
        # with the sandbox plugin's mock versions.
        "web": {
            "search": {"enabled": False},
            "fetch": {"enabled": False},
        },
        "deny": DENY_TOOLS,
        "allow": [],
    },
    "channels": {},
}


def load_scenario(name: str) -> dict:
    """Load a scenario YAML config by name."""
    path = SCENARIOS_DIR / f"{name}.yaml"
    if not path.exists():
        print(f"ERROR: Scenario not found: {path}")
        print(f"Available scenarios: {[p.stem for p in SCENARIOS_DIR.glob('*.yaml')]}")
        sys.exit(1)

    with open(path) as f:
        return yaml.safe_load(f)


def generate_openclaw_config(scenario: dict) -> dict:
    """Generate openclaw.json with tool allow-list from scenario config."""
    config = json.loads(json.dumps(BASE_CONFIG))  # deep copy

    # Set scenario in plugin config
    config["plugins"]["entries"]["trajectory-sandbox-tools"]["config"]["scenario"] = scenario["name"]

    # Build tool allow-list from scenario
    scenario_tools = scenario.get("tools", [])
    unknown_tools = [t for t in scenario_tools if t not in ALL_MOCK_TOOLS]
    if unknown_tools:
        print(f"WARNING: Unknown tools in scenario: {unknown_tools}")
        print(f"Known tools: {ALL_MOCK_TOOLS}")

    config["tools"]["allow"] = scenario_tools + ALWAYS_ALLOW
    return config


def setup_workspace(scenario: dict, variant: str):
    """Copy AGENTS.md variant and workspace files into the workspace directory."""
    scenario_name = scenario["name"]
    fixture_dir = FIXTURES_DIR / scenario_name

    # Ensure workspace exists
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    # Copy AGENTS.md variant
    variants = scenario.get("variants", {})
    if variant not in variants:
        print(f"ERROR: Unknown variant '{variant}'")
        print(f"Available variants: {list(variants.keys())}")
        sys.exit(1)

    agents_src = fixture_dir / variants[variant]
    if not agents_src.exists():
        print(f"ERROR: AGENTS.md variant not found: {agents_src}")
        sys.exit(1)

    shutil.copy2(agents_src, WORKSPACE_DIR / "AGENTS.md")
    print(f"  Copied {agents_src.name} -> workspace/AGENTS.md")

    # Copy workspace files
    for dest_name, src_name in scenario.get("workspace", {}).items():
        src = fixture_dir / src_name
        if src.exists():
            shutil.copy2(src, WORKSPACE_DIR / dest_name)
            print(f"  Copied {src_name} -> workspace/{dest_name}")
        else:
            print(f"  WARNING: Workspace file not found: {src}")


def main():
    parser = argparse.ArgumentParser(description="Setup a trajectory sandbox scenario")
    parser.add_argument("scenario", nargs="?", default=None, help="Scenario name")
    parser.add_argument("variant", nargs="?", default="baseline", help="AGENTS.md variant (default: baseline)")
    parser.add_argument("--scenario", "-s", dest="scenario_flag", help="Scenario name (alternative)")
    parser.add_argument("--variant", "-v", dest="variant_flag", help="Variant name (alternative)")
    parser.add_argument("--list", "-l", action="store_true", help="List available scenarios")

    args = parser.parse_args()

    if args.list:
        scenarios = sorted(SCENARIOS_DIR.glob("*.yaml"))
        print("Available scenarios:")
        for p in scenarios:
            with open(p) as f:
                s = yaml.safe_load(f)
            print(f"  {p.stem:25s} — {s.get('description', '').strip()[:60]}")
            print(f"  {'':25s}   tools: {', '.join(s.get('tools', []))}")
            print(f"  {'':25s}   variants: {', '.join(s.get('variants', {}).keys())}")
        return

    scenario_name = args.scenario_flag or args.scenario
    variant = args.variant_flag or args.variant

    if not scenario_name:
        parser.print_help()
        sys.exit(1)

    print(f"Setting up scenario: {scenario_name} (variant: {variant})")

    # Load scenario
    scenario = load_scenario(scenario_name)

    # Generate OpenClaw config
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    config = generate_openclaw_config(scenario)
    config_path = GENERATED_DIR / "openclaw.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"  Generated {config_path}")
    print(f"  Tools allowed: {config['tools']['allow']}")

    # Setup workspace
    setup_workspace(scenario, variant)

    # Write scenario env for docker-compose
    env_path = GENERATED_DIR / ".env.scenario"
    with open(env_path, "w") as f:
        f.write(f"SCENARIO={scenario_name}\n")
    print(f"  Generated {env_path}")

    print(f"\nScenario '{scenario_name}' ready (variant: {variant})")


if __name__ == "__main__":
    main()
