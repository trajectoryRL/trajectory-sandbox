#!/usr/bin/env python3
"""
Init container script for ClawBench Docker setup.

Reads SCENARIO and VARIANT from environment variables, loads the scenario
YAML, and copies the correct AGENTS.md variant + workspace files into the
shared /workspace volume.

Reads scenario YAML and copies the correct workspace files into the shared
volume, eliminating the need to run Python on the host before docker compose up.
"""

import os
import shutil
import sys
from pathlib import Path

import yaml

# Paths — configurable via env vars for all-in-one image, with defaults
# that match the legacy multi-container Docker volume mounts.
SCENARIOS_DIR = Path(os.environ.get("SCENARIOS_DIR", "/scenarios"))
FIXTURES_DIR = Path(os.environ.get("FIXTURES_DIR", "/fixtures"))
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))


def main():
    scenario_name = os.environ.get("SCENARIO", "client_escalation")
    variant = os.environ.get("VARIANT", "optimized")

    print(f"[init] Setting up workspace: scenario={scenario_name}, variant={variant}")

    # Load scenario YAML
    scenario_path = SCENARIOS_DIR / f"{scenario_name}.yaml"
    if not scenario_path.exists():
        available = [p.stem for p in SCENARIOS_DIR.glob("*.yaml")]
        print(f"[init] ERROR: Scenario not found: {scenario_name}")
        print(f"[init] Available: {available}")
        sys.exit(1)

    with open(scenario_path) as f:
        scenario = yaml.safe_load(f)

    # Ensure workspace dir exists
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    # Copy AGENTS.md variant
    variants = scenario.get("variants", {})
    if variant not in variants:
        print(f"[init] ERROR: Unknown variant '{variant}'")
        print(f"[init] Available variants: {list(variants.keys())}")
        sys.exit(1)

    agents_src = FIXTURES_DIR / scenario_name / variants[variant]
    if not agents_src.exists():
        print(f"[init] ERROR: AGENTS.md variant not found: {agents_src}")
        sys.exit(1)

    shutil.copy2(agents_src, WORKSPACE_DIR / "AGENTS.md")
    print(f"[init] Copied {agents_src.name} -> /workspace/AGENTS.md")

    # Copy workspace files (USER.md, etc.)
    for dest_name, src_name in scenario.get("workspace", {}).items():
        src = FIXTURES_DIR / scenario_name / src_name
        if src.exists():
            shutil.copy2(src, WORKSPACE_DIR / dest_name)
            print(f"[init] Copied {src_name} -> /workspace/{dest_name}")
        else:
            print(f"[init] WARNING: Workspace file not found: {src}")

    # Generate openclaw.json from template with the selected model
    DEFAULT_MODEL = "zhipu/glm-5"
    CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))

    OPENCLAW_HOME = Path(os.environ.get("OPENCLAW_HOME", "/openclaw-home"))
    OPENCLAW_CONFIG_DIR = OPENCLAW_HOME / ".openclaw"

    template = CONFIG_DIR / "openclaw.json.template"
    DEFAULT_LLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
    if template.exists():
        model = os.environ.get("CLAWBENCH_DEFAULT_MODEL", DEFAULT_MODEL)
        base_url = os.environ.get("CLAWBENCH_LLM_BASE_URL", DEFAULT_LLM_BASE_URL)
        config_text = template.read_text()
        config_text = config_text.replace("${CLAWBENCH_DEFAULT_MODEL}", model)
        config_text = config_text.replace("${CLAWBENCH_LLM_BASE_URL}", base_url)
        api_key = os.environ.get("CLAWBENCH_LLM_API_KEY", "")
        config_text = config_text.replace("${CLAWBENCH_LLM_API_KEY}", api_key)
        mock_tools_url = os.environ.get("MOCK_TOOLS_URL", "http://localhost:3001")
        config_text = config_text.replace("${MOCK_TOOLS_URL}", mock_tools_url)
        # Write config to $OPENCLAW_HOME/.openclaw/openclaw.json
        # (matches gateway's state dir resolved via OPENCLAW_HOME)
        os.makedirs(OPENCLAW_CONFIG_DIR, exist_ok=True)
        (OPENCLAW_CONFIG_DIR / "openclaw.json").write_text(config_text)
        print(f"[init] Generated openclaw.json -> {OPENCLAW_CONFIG_DIR}/openclaw.json (model={model})")
    else:
        print("[init] WARNING: openclaw.json.template not found, skipping config generation")

    # Ensure the gateway (running as node, uid 1000) can write to workspace
    # (e.g. SOUL.md). The init container runs as root, so files it creates
    # are root-owned by default.
    import subprocess
    subprocess.run(["chown", "-R", "1000:1000", str(WORKSPACE_DIR)], check=False)
    print(f"[init] Set workspace ownership to node (uid 1000)")

    print(f"[init] Workspace ready for scenario '{scenario_name}' (variant: {variant})")


if __name__ == "__main__":
    main()
