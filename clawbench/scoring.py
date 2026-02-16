"""
Scoring engine for ClawBench episodes.

Evaluates agent performance against scenario-specific rubrics defined
in the scoring: section of scenario YAML files.

Design principles:
  - Deterministic, fast, cheap (no LLM calls — all regex/counting)
  - Same rubric for baseline and optimized (the reward function is fixed;
    the policy is the thing being optimized)
  - Produces a scalar score in [0, 1] for RL, plus a detailed breakdown
    for human review

Check types:
  tool_called             — specific tool(s) were called at least once
  tool_not_called         — specific tool(s) were NOT called
  tool_arg_contains       — a tool call with args matching a regex pattern exists
  tool_arg_excludes       — NO tool call has args matching a regex pattern
  tool_response_contains  — a tool call with response matching a regex pattern exists
  tool_count_max          — total (or per-tool) calls ≤ max
  tool_count_min          — total (or per-tool) calls ≥ min
  tool_called_before      — tool A appears before tool B in the call log
  response_contains       — regex found in response text
  response_excludes       — regex NOT found in response text
  response_length_max     — response length ≤ max characters

Each check has: id, type, points, category, description, and type-specific params.
Categories: safety, correctness, efficiency, structure
"""

import json
import re
from typing import Any


# ---------------------------------------------------------------------------
# Evaluate a single check
# ---------------------------------------------------------------------------

def evaluate_check(check: dict, result: dict) -> dict:
    """Evaluate one scoring check against an episode result."""
    check_type = check["type"]
    passed = False
    detail = ""

    tool_calls_raw = result.get("tool_calls_raw", [])
    tool_counts = result.get("tool_calls_by_type", {})
    response = result.get("response", "")
    total_tools = result.get("tool_calls_total", 0)

    # --- tool_called: specific tool(s) called at least once ----------------
    if check_type == "tool_called":
        tools = _as_list(check, "tool", "tools")
        called = [t for t in tools if t in tool_counts]
        passed = len(called) == len(tools)
        missing = [t for t in tools if t not in tool_counts]
        detail = f"called={called}" if passed else f"missing={missing}"

    # --- tool_not_called: specific tool(s) were NOT called -----------------
    elif check_type == "tool_not_called":
        tools = _as_list(check, "tool", "tools")
        violated = [t for t in tools if t in tool_counts]
        passed = len(violated) == 0
        detail = f"forbidden tools called: {violated}" if violated else "none called"

    # --- tool_arg_contains: a tool call with matching args exists ----------
    elif check_type == "tool_arg_contains":
        tool = check.get("tool")
        pattern = check["pattern"]
        flags = re.DOTALL
        if check.get("case_insensitive", True):
            flags |= re.IGNORECASE
        matched = False
        for tc in tool_calls_raw:
            if tool and tc.get("tool") != tool:
                continue
            args_str = _tool_call_args_str(tc)
            if re.search(pattern, args_str, flags):
                matched = True
                break
        passed = matched
        scope = f"tool={tool}" if tool else "any tool"
        detail = f"'{pattern[:60]}' in {scope} → {'found' if matched else 'NOT FOUND'}"

    # --- tool_arg_excludes: NO tool call has matching args -----------------
    elif check_type == "tool_arg_excludes":
        tool = check.get("tool")
        pattern = check["pattern"]
        flags = re.DOTALL
        if check.get("case_insensitive", True):
            flags |= re.IGNORECASE
        violated_tc = None
        for tc in tool_calls_raw:
            if tool and tc.get("tool") != tool:
                continue
            args_str = _tool_call_args_str(tc)
            if re.search(pattern, args_str, flags):
                violated_tc = tc
                break
        passed = violated_tc is None
        scope = f"tool={tool}" if tool else "any tool"
        if violated_tc:
            detail = f"'{pattern[:60]}' in {scope} → FOUND in {violated_tc.get('tool', '?')}"
        else:
            detail = f"'{pattern[:60]}' in {scope} → not found (good)"

    # --- tool_response_contains: a tool call with matching response exists --
    elif check_type == "tool_response_contains":
        tool = check.get("tool")
        pattern = check["pattern"]
        flags = re.DOTALL
        if check.get("case_insensitive", True):
            flags |= re.IGNORECASE
        matched = False
        for tc in tool_calls_raw:
            if tool and tc.get("tool") != tool:
                continue
            resp_str = _tool_call_response_str(tc)
            if re.search(pattern, resp_str, flags):
                matched = True
                break
        passed = matched
        scope = f"tool={tool}" if tool else "any tool"
        detail = f"'{pattern[:60]}' in {scope} response → {'found' if matched else 'NOT FOUND'}"

    # --- tool_count_max: call count ≤ max ----------------------------------
    elif check_type == "tool_count_max":
        tool = check.get("tool")
        max_val = check["max"]
        actual = tool_counts.get(tool, 0) if tool else total_tools
        passed = actual <= max_val
        label = tool or "total"
        detail = f"{label}={actual} (max {max_val})"

    # --- tool_count_min: call count ≥ min ----------------------------------
    elif check_type == "tool_count_min":
        tool = check.get("tool")
        min_val = check["min"]
        actual = tool_counts.get(tool, 0) if tool else total_tools
        passed = actual >= min_val
        label = tool or "total"
        detail = f"{label}={actual} (min {min_val})"

    # --- tool_called_before: tool A before tool B in timeline --------------
    elif check_type == "tool_called_before":
        before_tool = check["before"]
        after_tool = check["after"]
        tool_names = [tc["tool"] for tc in tool_calls_raw]
        idx_before = _first_index(tool_names, before_tool)
        idx_after = _first_index(tool_names, after_tool)

        if idx_after is None:
            # after_tool never called — vacuously true (e.g. task.create never called)
            passed = True
            detail = f"{after_tool} never called"
        elif idx_before is None:
            passed = False
            detail = f"{before_tool} never called but {after_tool} was"
        else:
            passed = idx_before < idx_after
            detail = f"{before_tool}@{idx_before} {'<' if passed else '>='} {after_tool}@{idx_after}"

    # --- response_contains: regex match in response text -------------------
    elif check_type == "response_contains":
        pattern = check["pattern"]
        flags = re.DOTALL  # always allow . to match newlines
        if check.get("case_insensitive", True):
            flags |= re.IGNORECASE
        match = re.search(pattern, response, flags)
        passed = match is not None
        detail = f"'{pattern[:60]}' → {'found' if match else 'NOT FOUND'}"

    # --- response_excludes: regex must NOT match ---------------------------
    elif check_type == "response_excludes":
        pattern = check["pattern"]
        flags = re.DOTALL
        if check.get("case_insensitive", True):
            flags |= re.IGNORECASE
        match = re.search(pattern, response, flags)
        passed = match is None
        snippet = response[match.start():match.start()+50] if match else ""
        detail = f"'{pattern[:60]}' → {'not found (good)' if not match else f'FOUND: ...{snippet}...'}"

    # --- response_length_max: response length ≤ max characters --------------
    elif check_type == "response_length_max":
        max_val = check["max"]
        passed = len(response) <= max_val
        detail = f"length={len(response)} (max {max_val})"

    else:
        detail = f"unknown check type: {check_type}"
        passed = False

    return {
        "id": check["id"],
        "type": check_type,
        "passed": passed,
        "points": check.get("points", 1) if passed else 0,
        "max_points": check.get("points", 1),
        "category": check.get("category", "other"),
        "description": check.get("description", ""),
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Score an entire episode
# ---------------------------------------------------------------------------

def score_episode(result: dict, scoring_config: dict) -> dict:
    """
    Score an episode result against a scoring rubric.

    Args:
        result: Episode result dict (from run_single)
        scoring_config: The 'scoring' section from the scenario YAML

    Returns:
        Score dict with normalized score, per-check results, category breakdown
    """
    checks = scoring_config.get("checks", [])
    if not checks:
        return {"score": None, "reason": "no scoring checks defined"}

    evaluated = [evaluate_check(check, result) for check in checks]

    total_earned = sum(e["points"] for e in evaluated)
    total_possible = sum(e["max_points"] for e in evaluated)

    # Per-category breakdown
    categories: dict[str, dict[str, Any]] = {}
    for e in evaluated:
        cat = e["category"]
        if cat not in categories:
            categories[cat] = {"earned": 0, "possible": 0, "passed": 0, "failed": 0}
        categories[cat]["earned"] += e["points"]
        categories[cat]["possible"] += e["max_points"]
        categories[cat]["passed" if e["passed"] else "failed"] += 1

    for info in categories.values():
        info["score"] = info["earned"] / info["possible"] if info["possible"] > 0 else 0.0

    passed_count = sum(1 for e in evaluated if e["passed"])
    failed_count = sum(1 for e in evaluated if not e["passed"])

    return {
        "score": round(total_earned / total_possible, 4) if total_possible > 0 else 0.0,
        "points_earned": total_earned,
        "points_possible": total_possible,
        "passed": passed_count,
        "failed": failed_count,
        "total_checks": len(evaluated),
        "checks": evaluated,
        "by_category": {
            cat: {
                "earned": info["earned"],
                "possible": info["possible"],
                "score": round(info["score"], 4),
                "passed": info["passed"],
                "failed": info["failed"],
            }
            for cat, info in categories.items()
        },
    }


# ---------------------------------------------------------------------------
# Format score for display
# ---------------------------------------------------------------------------

def format_score_summary(score: dict) -> str:
    """Format a score dict as a human-readable summary."""
    if score.get("score") is None:
        return "  (no scoring rubric)"

    lines = []
    pct = score["score"] * 100
    lines.append(f"  Score: {pct:.0f}% ({score['points_earned']}/{score['points_possible']} points, "
                 f"{score['passed']}/{score['total_checks']} checks passed)")

    # Category bars
    cat_order = ["safety", "correctness", "efficiency", "structure"]
    for cat in cat_order:
        info = score["by_category"].get(cat)
        if not info:
            continue
        cat_pct = info["score"] * 100
        bar_filled = int(info["score"] * 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        lines.append(f"    {cat:<14s} {info['earned']:>2}/{info['possible']:<2} ({cat_pct:>3.0f}%) {bar}")

    # Failed checks
    failed = [c for c in score.get("checks", []) if not c["passed"]]
    if failed:
        lines.append("  Failed:")
        for c in failed:
            lines.append(f"    ✗ {c['id']}: {c['description']} [{c['detail']}]")

    return "\n".join(lines)


def format_score_markdown(score: dict, scenario: str, variant: str) -> str:
    """Format a score dict as markdown for the summary report."""
    if score.get("score") is None:
        return ""

    lines = []
    pct = score["score"] * 100
    lines.append(f"#### {scenario}/{variant} — {pct:.0f}% ({score['points_earned']}/{score['points_possible']})")
    lines.append("")

    # Category table
    lines.append("| Category | Score | Passed | Failed |")
    lines.append("|----------|-------|--------|--------|")
    for cat in ["safety", "correctness", "efficiency", "structure"]:
        info = score["by_category"].get(cat)
        if not info:
            continue
        cat_pct = info["score"] * 100
        lines.append(f"| {cat} | {info['earned']}/{info['possible']} ({cat_pct:.0f}%) | {info['passed']} | {info['failed']} |")

    lines.append("")

    # All checks
    lines.append("| Check | Status | Points | Detail |")
    lines.append("|-------|--------|--------|--------|")
    for c in score.get("checks", []):
        icon = "✅" if c["passed"] else "❌"
        lines.append(f"| {c['id']} | {icon} | {c['points']}/{c['max_points']} | {c['detail'][:60]} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _as_list(d: dict, singular_key: str, plural_key: str) -> list:
    """Get a list from either a singular or plural key."""
    if plural_key in d:
        return d[plural_key]
    if singular_key in d:
        val = d[singular_key]
        return val if isinstance(val, list) else [val]
    return []


def _tool_call_args_str(tc: dict) -> str:
    """Flatten a tool call's args dict into a searchable string."""
    args = tc.get("args", {})
    if isinstance(args, str):
        return args
    if isinstance(args, dict):
        return json.dumps(args, default=str)
    return str(args)


def _tool_call_response_str(tc: dict) -> str:
    """Flatten a tool call's response into a searchable string."""
    resp = tc.get("response", "")
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        return json.dumps(resp, default=str)
    return str(resp)


def _first_index(lst: list, value: str) -> int | None:
    """Return index of first occurrence, or None."""
    try:
        return lst.index(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Scenario YAML validation
# ---------------------------------------------------------------------------

KNOWN_TOOLS = {"exec", "slack", "memory_search", "memory_get", "web_search", "web_fetch", "read"}

KNOWN_CHECK_TYPES = {
    "tool_called", "tool_not_called",
    "tool_arg_contains", "tool_arg_excludes", "tool_response_contains",
    "tool_count_max", "tool_count_min", "tool_called_before",
    "response_contains", "response_excludes", "response_length_max",
}

KNOWN_CATEGORIES = {"safety", "correctness", "efficiency", "structure"}

# Required fields per check type (beyond the universal ones)
_TYPE_REQUIRED: dict[str, list[str]] = {
    "response_contains": ["pattern"],
    "response_excludes": ["pattern"],
    "tool_arg_contains": ["pattern"],
    "tool_arg_excludes": ["pattern"],
    "tool_response_contains": ["pattern"],
    "tool_count_max": ["max"],
    "tool_count_min": ["min"],
    "tool_called_before": ["before", "after"],
    "response_length_max": ["max"],
}


def validate_scenario(scenario: dict) -> list[str]:
    """Validate a scenario dict and return a list of error strings (empty = valid)."""
    errors: list[str] = []

    # Required top-level fields
    if not isinstance(scenario.get("name"), str):
        errors.append("missing or invalid top-level field: 'name' (str)")
    if not isinstance(scenario.get("tools"), list):
        errors.append("missing or invalid top-level field: 'tools' (list)")
    if not isinstance(scenario.get("prompt"), str):
        errors.append("missing or invalid top-level field: 'prompt' (str)")
    if not isinstance(scenario.get("variants"), dict):
        errors.append("missing or invalid top-level field: 'variants' (dict)")

    # Valid tool names
    for tool in scenario.get("tools", []):
        if tool not in KNOWN_TOOLS:
            errors.append(f"unknown tool: '{tool}' (known: {sorted(KNOWN_TOOLS)})")

    # Validate scoring checks
    checks = scenario.get("scoring", {}).get("checks", [])
    seen_ids: set[str] = set()

    for i, chk in enumerate(checks):
        prefix = f"check[{i}]"

        # Required universal fields
        for field in ("id", "type", "points", "category", "description"):
            if field not in chk:
                errors.append(f"{prefix}: missing required field '{field}'")

        chk_id = chk.get("id", f"<unnamed-{i}>")
        chk_type = chk.get("type", "")

        # Duplicate IDs
        if chk_id in seen_ids:
            errors.append(f"{prefix}: duplicate check id '{chk_id}'")
        seen_ids.add(chk_id)

        # Valid type
        if chk_type and chk_type not in KNOWN_CHECK_TYPES:
            errors.append(f"{prefix} ({chk_id}): unknown check type '{chk_type}' (known: {sorted(KNOWN_CHECK_TYPES)})")

        # Valid category
        cat = chk.get("category")
        if cat and cat not in KNOWN_CATEGORIES:
            errors.append(f"{prefix} ({chk_id}): unknown category '{cat}' (known: {sorted(KNOWN_CATEGORIES)})")

        # tool_called / tool_not_called require 'tool' or 'tools'
        if chk_type in ("tool_called", "tool_not_called"):
            if "tool" not in chk and "tools" not in chk:
                errors.append(f"{prefix} ({chk_id}): type '{chk_type}' requires 'tool' or 'tools'")

        # Type-specific required fields
        for field in _TYPE_REQUIRED.get(chk_type, []):
            if field not in chk:
                errors.append(f"{prefix} ({chk_id}): type '{chk_type}' requires '{field}'")

        # Regex syntax validation for pattern fields
        if "pattern" in chk:
            try:
                re.compile(chk["pattern"])
            except re.error as e:
                errors.append(f"{prefix} ({chk_id}): invalid regex pattern: {e}")

    return errors
