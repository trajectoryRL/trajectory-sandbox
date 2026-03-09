"""
Shared runner utilities for ClawBench episode execution.

Extracted from run_episode.py and run_batch.py to eliminate duplication.
Both scripts import from this module for service interaction, scenario
loading, and workspace setup.
"""

import os
import shutil
import time
from pathlib import Path

import httpx
import yaml
from openai import OpenAI

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------
DEFAULT_OPENCLAW_URL = "http://localhost:18790"
DEFAULT_OPENCLAW_TOKEN = "sandbox-token-12345"
DEFAULT_MOCK_TOOLS_URL = "http://localhost:3001"
DEFAULT_MODEL = "zhipu/glm-5"


def _make_openai_client(
    base_url: str = DEFAULT_OPENCLAW_URL,
    api_key: str = DEFAULT_OPENCLAW_TOKEN,
    timeout: int = 180,
) -> OpenAI:
    """Create an OpenAI client pointing at the gateway."""
    return OpenAI(
        base_url=f"{base_url}/v1",
        api_key=api_key,
        timeout=float(timeout),
    )


# ---------------------------------------------------------------------------
# Service interaction
# ---------------------------------------------------------------------------

def wait_for_services(mock_url: str, openclaw_url: str, timeout: int = 120) -> bool:
    """Wait for OpenClaw and mock-tools to be ready."""
    print("Waiting for services...")
    start = time.time()
    mock_ready = False
    openclaw_ready = False

    while time.time() - start < timeout:
        if not mock_ready:
            try:
                r = httpx.get(f"{mock_url}/health", timeout=2)
                if r.status_code == 200:
                    health = r.json()
                    print(f"  Mock tools: OK ({health.get('tools_available', '?')} tools, scenario={health.get('scenario', '?')})")
                    mock_ready = True
            except httpx.RequestError:
                pass

        if mock_ready and not openclaw_ready:
            try:
                r = httpx.get(f"{openclaw_url}/health", timeout=2)
                if r.status_code == 200:
                    print("  OpenClaw: OK")
                    openclaw_ready = True
            except httpx.RequestError:
                pass

        if mock_ready and openclaw_ready:
            return True

        elapsed = int(time.time() - start)
        if elapsed > 0 and elapsed % 10 == 0:
            status = []
            if not mock_ready:
                status.append("mock-tools")
            if not openclaw_ready:
                status.append("openclaw")
            print(f"  Still waiting for {', '.join(status)}... ({elapsed}s)")

        time.sleep(1)

    if not mock_ready:
        print("  TIMEOUT: mock-tools not ready")
    if not openclaw_ready:
        print("  TIMEOUT: OpenClaw not ready")
    return False


def send_message(
    openclaw_url: str,
    token: str,
    message: str,
    model: str | None = None,
    timeout: int = 180,
    session_key: str | None = None,
) -> dict:
    """Send a message via OpenAI-compatible chat completions API.

    Uses the openai SDK to call the gateway's /v1/chat/completions endpoint.

    Args:
        openclaw_url: Gateway base URL.
        token: Gateway auth token (used as API key).
        message: User message content.
        model: Model identifier (e.g. "openai/glm-5").
        timeout: Request timeout in seconds.
        session_key: Optional session key for deterministic session tracking.
    """
    if model is None:
        model = os.getenv("CLAWBENCH_DEFAULT_MODEL", DEFAULT_MODEL)

    try:
        extra_headers = {}
        if session_key:
            extra_headers["x-openclaw-session-key"] = session_key

        client = _make_openai_client(
            base_url=openclaw_url, api_key=token, timeout=timeout,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": message}],
            stream=False,
            extra_headers=extra_headers if extra_headers else None,
        )
        return response.model_dump()
    except Exception as e:
        return {"error": str(e)}


def extract_usage(response: dict) -> dict | None:
    """Extract token usage from an OpenAI chat completions response.

    Returns None if no usage data is present.
    """
    usage = response.get("usage")
    if usage and isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", prompt_tokens + completion_tokens)
        if total > 0:
            cached = 0
            details = usage.get("prompt_tokens_details")
            if isinstance(details, dict):
                cached = details.get("cached_tokens", 0)
            return {
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "cache_read_tokens": cached,
                "cache_write_tokens": 0,
                "total_cost_usd": 0.0,
            }

    return None


def get_tool_calls(mock_url: str) -> list:
    """Get successful tool calls from mock-tools server."""
    try:
        response = httpx.get(f"{mock_url}/tool_calls", timeout=5)
        if response.status_code == 200:
            return response.json().get("calls", [])
    except httpx.RequestError:
        pass
    return []


def get_all_requests(mock_url: str) -> dict:
    """Get ALL requests (including failures) from mock-tools server."""
    try:
        response = httpx.get(f"{mock_url}/all_requests", timeout=5)
        if response.status_code == 200:
            return response.json()
    except httpx.RequestError:
        pass
    return {"requests": [], "summary": {"total": 0, "success": 0, "failed": 0}}


def reset_scenario(mock_url: str, scenario: str) -> bool:
    """Reset mock-tools to a specific scenario."""
    try:
        response = httpx.post(f"{mock_url}/set_scenario/{scenario}", timeout=5)
        return response.status_code == 200
    except httpx.RequestError:
        return False


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------

def load_scenario(name: str, scenarios_dir: Path) -> dict | None:
    """Load scenario YAML config. Returns None if not found."""
    path = scenarios_dir / f"{name}.yaml"
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def load_all_scenarios(scenarios_dir: Path) -> list[dict]:
    """Load all scenario YAML configs, sorted by name."""
    scenarios = []
    for path in sorted(scenarios_dir.glob("*.yaml")):
        with open(path) as f:
            s = yaml.safe_load(f)
        s["_path"] = path
        scenarios.append(s)
    return scenarios


# ---------------------------------------------------------------------------
# Workspace setup
# ---------------------------------------------------------------------------

def setup_workspace(
    scenario_config: dict,
    variant: str,
    fixtures_dir: Path,
    workspace_dir: Path,
) -> bool:
    """Copy AGENTS.md variant and workspace files for the scenario."""
    scenario_name = scenario_config["name"]
    fixture_dir = fixtures_dir / scenario_name

    variants = scenario_config.get("variants", {})
    if variant not in variants:
        print(f"  WARNING: Unknown variant '{variant}', available: {list(variants.keys())}")
        return False

    workspace_dir.mkdir(parents=True, exist_ok=True)

    agents_src = fixture_dir / variants[variant]
    if agents_src.exists():
        shutil.copy2(agents_src, workspace_dir / "AGENTS.md")
        print(f"  Copied {agents_src.name} -> workspace/AGENTS.md")
    else:
        print(f"  WARNING: {agents_src} not found")
        return False

    for dest_name, src_name in scenario_config.get("workspace", {}).items():
        src = fixture_dir / src_name
        if src.exists():
            shutil.copy2(src, workspace_dir / dest_name)

    return True
