#!/usr/bin/env python3
"""
Run a single episode against the OpenClaw sandbox.

Scenario-aware: reads the scenario YAML config to get the default prompt,
tool list, and other settings. Can also accept a custom message.

Usage:
    python scripts/run_episode.py --scenario inbox_triage
    python scripts/run_episode.py --scenario inbox_triage --message "Custom prompt"
    python scripts/run_episode.py --wait --scenario inbox_triage
    python scripts/run_episode.py --scenario inbox_triage --user-context '{"USER_NAME":"Jordan Rivera","COMPANY":"Meridian Tech"}'
"""

import argparse
import json
import os
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

import yaml

# Allow imports from the clawbench package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clawbench.scoring import score_episode
from clawbench.runner import (
    DEFAULT_OPENCLAW_URL, DEFAULT_OPENCLAW_TOKEN, DEFAULT_MOCK_TOOLS_URL,
    wait_for_services, send_message, get_tool_calls, get_all_requests,
    reset_scenario, setup_workspace, load_scenario,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SANDBOX_DIR = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = SANDBOX_DIR / "scenarios"
FIXTURES_DIR = SANDBOX_DIR / "fixtures"
WORKSPACE_DIR = SANDBOX_DIR / "workspace"

# ---------------------------------------------------------------------------
# Configuration (env vars with defaults)
# ---------------------------------------------------------------------------
OPENCLAW_URL = os.getenv("OPENCLAW_URL", DEFAULT_OPENCLAW_URL)
OPENCLAW_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", DEFAULT_OPENCLAW_TOKEN)
MOCK_TOOLS_URL = os.getenv("MOCK_TOOLS_URL", DEFAULT_MOCK_TOOLS_URL)
CLAWBENCH_MODEL = os.getenv("CLAWBENCH_MODEL", "anthropic/claude-sonnet-4-6")


def set_mock_user_context(user_context: dict) -> bool:
    """Send user context to mock server for runtime {{PLACEHOLDER}} substitution."""
    import httpx
    try:
        response = httpx.post(
            f"{MOCK_TOOLS_URL}/set_user_context",
            json=user_context,
            timeout=5,
        )
        return response.status_code == 200
    except httpx.RequestError:
        return False


def fill_templates(content: str, context: dict) -> str:
    """Replace {{KEY}} placeholders in content with values from context.

    Auto-derives USER_FIRST_NAME from USER_NAME if not explicitly set.

    Args:
        content: Template string with {{PLACEHOLDER}} markers
        context: Dict of placeholder_name -> value

    Returns:
        Content with all known placeholders replaced
    """
    if not context:
        return content

    # Auto-derive first name if not provided
    ctx = dict(context)
    if "USER_FIRST_NAME" not in ctx and "USER_NAME" in ctx:
        ctx["USER_FIRST_NAME"] = ctx["USER_NAME"].split()[0]

    # Replace all {{KEY}} patterns with corresponding values
    def replacer(match):
        key = match.group(1)
        return ctx.get(key, match.group(0))  # Leave unmatched placeholders as-is

    return re.sub(r"\{\{(\w+)\}\}", replacer, content)


def resolve_user_context(scenario_config: dict | None, overrides: dict | None) -> dict:
    """Merge scenario defaults with caller overrides to produce template context.

    Args:
        scenario_config: Loaded scenario YAML (may contain user_context_defaults)
        overrides: Caller-provided overrides (from --user-context)

    Returns:
        Merged context dict ready for fill_templates()
    """
    defaults = {}
    if scenario_config:
        defaults = dict(scenario_config.get("user_context_defaults", {}))
    if overrides:
        defaults.update(overrides)
    return defaults


def setup_workspace_with_templates(
    scenario_config: dict,
    variant: str,
    user_context: dict | None = None,
) -> bool:
    """Copy AGENTS.md variant and workspace files with template substitution.

    Workspace files containing {{PLACEHOLDER}} markers are filled using
    user_context (merged from scenario defaults + caller overrides).

    Args:
        scenario_config: Loaded scenario YAML
        variant: AGENTS.md variant name (e.g., "optimized")
        user_context: Template context dict for {{PLACEHOLDER}} substitution
    """
    scenario_name = scenario_config["name"]
    fixture_dir = FIXTURES_DIR / scenario_name

    variants = scenario_config.get("variants", {})
    if variant not in variants:
        print(f"  WARNING: Unknown variant '{variant}', available: {list(variants.keys())}")
        return False

    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    agents_src = fixture_dir / variants[variant]
    if agents_src.exists():
        shutil.copy2(agents_src, WORKSPACE_DIR / "AGENTS.md")
        print(f"  Copied {agents_src.name} -> workspace/AGENTS.md")
    else:
        print(f"  WARNING: {agents_src} not found")
        return False

    ctx = resolve_user_context(scenario_config, user_context)

    for dest_name, src_name in scenario_config.get("workspace", {}).items():
        src = fixture_dir / src_name
        if src.exists():
            if ctx and dest_name.endswith(".md"):
                # Template-substitute markdown workspace files
                content = src.read_text()
                content = fill_templates(content, ctx)
                (WORKSPACE_DIR / dest_name).write_text(content)
                print(f"  Templated {src_name} -> workspace/{dest_name}")
            else:
                shutil.copy2(src, WORKSPACE_DIR / dest_name)

    return True


def run_episode(
    message: str,
    scenario: str = "inbox_triage",
    user_context: dict | None = None,
) -> dict:
    """Run a complete episode and return results."""

    # Reset scenario
    print(f"\nResetting to scenario: {scenario}")
    if not reset_scenario(MOCK_TOOLS_URL, scenario):
        print("  Warning: Could not reset scenario")

    # Push user context to mock server for runtime template substitution
    if user_context:
        if set_mock_user_context(user_context):
            print(f"  Set user context: {user_context.get('USER_NAME', '?')} at {user_context.get('COMPANY', '?')}")
        else:
            print("  Warning: Could not set user context on mock server")

    # Send message
    print(f"\nSending message to OpenClaw:")
    print(f"  URL: {OPENCLAW_URL}/v1/chat/completions")
    print(f"  Message: {message[:100]}...")
    response = send_message(OPENCLAW_URL, OPENCLAW_TOKEN, message)

    # Get tool calls
    tool_calls = get_tool_calls(MOCK_TOOLS_URL)
    all_reqs = get_all_requests(MOCK_TOOLS_URL)

    # Extract assistant response
    assistant_message = ""
    if "choices" in response:
        assistant_message = response["choices"][0].get("message", {}).get("content", "")

    # Detect errors
    failed_requests = [r for r in all_reqs.get("requests", []) if not r.get("success")]

    error_patterns = [
        "technical issue", "encountered an error", "unable to",
        "couldn't", "failed to", "try again",
    ]
    response_has_error_hints = any(
        pattern in assistant_message.lower() for pattern in error_patterns
    )

    result = {
        "scenario": scenario,
        "input_message": message,
        "response": assistant_message,
        "tool_calls": tool_calls,
        "all_requests": all_reqs.get("requests", []),
        "request_summary": all_reqs.get("summary", {}),
        "failed_requests": failed_requests,
        "response_has_error_hints": response_has_error_hints,
        "raw_response": response,
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="Run an episode against the OpenClaw sandbox")
    parser.add_argument("--scenario", "-s", type=str, default="inbox_triage",
                        help="Scenario name (must have a YAML config in scenarios/)")
    parser.add_argument("--variant", "-v", type=str, default="optimized",
                        help="AGENTS.md variant (default: optimized)")
    parser.add_argument("--message", "-m", type=str, default=None,
                        help="Message to send (overrides scenario default prompt)")
    parser.add_argument("--wait", "-w", action="store_true",
                        help="Wait for services to be ready")
    parser.add_argument("--output", "-o", type=str,
                        help="Output file for results (JSON)")
    parser.add_argument("--json", "-j", action="store_true",
                        help="Output scored JSON to stdout (for validator integration)")
    parser.add_argument("--workspace", type=str,
                        help="Custom workspace directory (skips default workspace setup)")
    parser.add_argument("--user-context", type=str, default=None,
                        help="JSON dict of user identity overrides for {{PLACEHOLDER}} substitution "
                             "in workspace files (e.g., USER.md). Merges with scenario defaults.")
    parser.add_argument("--list", "-l", action="store_true",
                        help="List available scenarios")

    args = parser.parse_args()

    # In --json mode, redirect verbose prints to stderr so only JSON goes to stdout
    if args.json:
        _real_stdout = sys.stdout
        sys.stdout = sys.stderr

    if args.list:
        scenarios = sorted(SCENARIOS_DIR.glob("*.yaml"))
        print("Available scenarios:")
        for p in scenarios:
            with open(p) as f:
                s = yaml.safe_load(f)
            tools = s.get("tools", [])
            print(f"  {p.stem:25s} — {s.get('description', '').strip()[:60]}")
            print(f"  {'':25s}   tools: {len(tools)}, variants: {', '.join(s.get('variants', {}).keys())}")
        return

    # Load scenario config for default prompt
    scenario_config = load_scenario(args.scenario, SCENARIOS_DIR)
    if scenario_config is None:
        print(f"WARNING: No scenario config found for '{args.scenario}' — using defaults")
        default_prompt = "Review my inbox and draft replies for urgent emails."
    else:
        default_prompt = scenario_config.get("prompt", "Help me with my tasks.").strip()
        print(f"Loaded scenario: {scenario_config.get('name', args.scenario)}")
        print(f"  Tools: {', '.join(scenario_config.get('tools', []))}")

    message = args.message or default_prompt

    # Parse --user-context JSON if provided
    user_context = None
    if args.user_context:
        try:
            user_context = json.loads(args.user_context)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid --user-context JSON: {e}")
            sys.exit(1)

    # Setup workspace files for this scenario/variant.
    # If --workspace is given, the caller already prepared the workspace (e.g.,
    # validator wrote the pack's AGENTS.md there), so we skip the default
    # variant/file setup — but we still template-fill workspace files if
    # --user-context was provided.
    if args.workspace:
        global WORKSPACE_DIR
        WORKSPACE_DIR = Path(args.workspace)
        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

        # When --workspace + --user-context, template-fill workspace .md files
        # that weren't written by the caller (e.g., USER.md from fixtures).
        if user_context and scenario_config:
            ctx = resolve_user_context(scenario_config, user_context)
            for dest_name, src_name in scenario_config.get("workspace", {}).items():
                dest = WORKSPACE_DIR / dest_name
                if dest.exists() and dest_name.endswith(".md"):
                    # File already in workspace (maybe from fixture copy) — re-template
                    content = dest.read_text()
                    # If it still has {{...}} placeholders, fill them
                    if "{{" in content:
                        content = fill_templates(content, ctx)
                        dest.write_text(content)
                else:
                    # Not in workspace yet — copy from fixture and template
                    src = FIXTURES_DIR / scenario_config["name"] / src_name
                    if src.exists() and dest_name.endswith(".md"):
                        content = fill_templates(src.read_text(), ctx)
                        dest.write_text(content)
                    elif src.exists():
                        shutil.copy2(src, dest)
    elif scenario_config:
        setup_workspace_with_templates(scenario_config, args.variant, user_context)

    if args.wait:
        if not wait_for_services(MOCK_TOOLS_URL, OPENCLAW_URL):
            print("ERROR: Services not ready")
            sys.exit(1)

    # Resolve merged user context (defaults + overrides) for the mock server
    resolved_ctx = resolve_user_context(scenario_config, user_context) if scenario_config else (user_context or {})

    # Run episode
    result = run_episode(message, args.scenario, user_context=resolved_ctx or None)

    # Restore stdout for JSON output
    if args.json:
        sys.stdout = _real_stdout

    # --json mode: score and output JSON for validator integration
    if args.json:
        tool_calls = result.get("tool_calls", [])
        tool_counts = dict(Counter(tc["tool"] for tc in tool_calls))

        # Build the result dict that scoring.py expects
        scorable = {
            "response": result.get("response", ""),
            "tool_calls_raw": tool_calls,
            "tool_calls_by_type": tool_counts,
            "tool_calls_total": len(tool_calls),
        }

        # Score against scenario rubric
        rubric = {}
        score_val = 0.0
        success = False

        if scenario_config:
            scoring_config = scenario_config.get("scoring")
            if scoring_config:
                score_result = score_episode(scorable, scoring_config)
                score_val = score_result.get("score", 0.0)
                success = score_result.get("failed", 1) == 0
                rubric = score_result

        output = {
            "score": score_val,
            "success": success,
            "tool_calls": len(tool_calls),
            "response": result.get("response", ""),
            "rubric": rubric,
        }

        if result.get("response_has_error_hints"):
            output["error"] = "Response contains error language"

        print(json.dumps(output))
        return result

    # Normal mode: print human-readable summary
    print("\n" + "=" * 60)
    print("EPISODE RESULTS")
    print("=" * 60)

    summary = result.get("request_summary", {})
    print(f"\nRequests: {summary.get('total', '?')} total, "
          f"{summary.get('success', '?')} succeeded, "
          f"{summary.get('failed', '?')} failed")

    print(f"\nSuccessful Tool Calls ({len(result['tool_calls'])}):")
    for call in result["tool_calls"]:
        print(f"  + {call['tool']}: {call.get('args', {})}")

    if result.get("failed_requests"):
        print(f"\nFailed Requests ({len(result['failed_requests'])}):")
        for req in result["failed_requests"]:
            print(f"  ! {req.get('tool', '?')} (HTTP {req.get('status_code', '?')})")

    if result.get("response_has_error_hints"):
        print("\n** WARNING: Assistant response contains error language **")

    print(f"\nAssistant Response:")
    resp_text = result["response"]
    print(f"  {resp_text[:500]}{'...' if len(resp_text) > 500 else ''}")

    # Save to file if requested
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nResults saved to: {args.output}")

    return result


if __name__ == "__main__":
    main()
