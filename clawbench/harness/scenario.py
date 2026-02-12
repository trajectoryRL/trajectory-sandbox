"""
Scenario loader and data models.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class ToolPolicy(BaseModel):
    allow: list[str] = []
    deny: list[str] = []


class Budgets(BaseModel):
    max_tool_calls: int = 10
    max_tokens: int = 4000
    max_turns: int = 8
    timeout_ms: int = 60000


class ConversationTurn(BaseModel):
    role: str
    content: str


class Scenario(BaseModel):
    id: str
    version: int = 1
    description: str = ""
    fixture_dir: str
    
    workspace: dict[str, str | None] = {}
    tool_policy: ToolPolicy = ToolPolicy()
    budgets: Budgets = Budgets()
    conversation: list[ConversationTurn] = []
    checks: list[str] = []  # legacy field kept for backward compat with old JSON scenarios
    scoring: dict[str, Any] = {}

    @classmethod
    def load(cls, path: str | Path) -> "Scenario":
        """Load scenario from JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls(**data)


class EpisodeResult(BaseModel):
    scenario_id: str
    variant: str  # "baseline" or "optimized"
    seed: int
    
    messages: list[dict] = []
    tool_calls: list[dict] = []
    
    success: bool = False
    success_reason: str = ""
    
    metrics: dict[str, Any] = {}
    score: float = 0.0  # normalized to [0, 1]


def load_all_scenarios(scenarios_dir: Path) -> list[Scenario]:
    """Load all scenarios from a directory."""
    scenarios = []
    for path in scenarios_dir.glob("*.json"):
        scenarios.append(Scenario.load(path))
    return scenarios
