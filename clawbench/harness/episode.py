"""
Episode runner - executes a scenario and collects results.
"""

import time
from pathlib import Path
from typing import Any

from rich.console import Console

from .client import OpenClawClient, MockToolsClient
from .scenario import Scenario, EpisodeResult
from .workspace import WorkspaceManager
from ..scoring import score_episode

console = Console()


class EpisodeRunner:
    """Runs a single episode (scenario + variant)."""

    def __init__(
        self,
        openclaw_url: str = "http://localhost:3000",
        mock_tools_url: str = "http://localhost:3001",
        workspace_path: str = "./workspace",
        fixtures_path: str = "./fixtures",
    ):
        self.openclaw = OpenClawClient(openclaw_url)
        self.mock_tools = MockToolsClient(mock_tools_url)
        self.workspace = WorkspaceManager(workspace_path)
        self.fixtures_path = Path(fixtures_path)

    def run(
        self,
        scenario: Scenario,
        variant: str = "baseline",
        seed: int = 42,
    ) -> EpisodeResult:
        """
        Run a single episode.
        
        Args:
            scenario: The scenario to run
            variant: "baseline" or "optimized"
            seed: Random seed for reproducibility
        """
        console.print(f"[bold]Running {scenario.id}[/bold] ({variant})")
        
        result = EpisodeResult(
            scenario_id=scenario.id,
            variant=variant,
            seed=seed,
        )
        
        # 1. Setup workspace
        fixtures_dir = self.fixtures_path / scenario.fixture_dir
        self.workspace.setup_from_scenario(
            fixtures_dir,
            scenario.workspace,
            variant,
        )
        console.print(f"  Workspace setup from {fixtures_dir}")
        
        # 2. Configure mock tools server
        self.mock_tools.set_scenario(scenario.fixture_dir)
        console.print(f"  Mock tools configured for {scenario.fixture_dir}")
        
        # 3. Build initial messages
        messages = []
        for turn in scenario.conversation:
            messages.append({"role": turn.role, "content": turn.content})
        
        # 4. Run conversation loop
        start_time = time.time()
        turn_count = 0
        total_tool_calls = 0
        
        while turn_count < scenario.budgets.max_turns:
            turn_count += 1
            console.print(f"  Turn {turn_count}...")
            
            try:
                # Send to OpenClaw
                response = self.openclaw.chat(messages)
                
                # Extract assistant message
                assistant_msg = response.get("choices", [{}])[0].get("message", {})
                messages.append(assistant_msg)
                result.messages = messages.copy()
                
                # Check for tool calls
                tool_calls = assistant_msg.get("tool_calls", [])
                if tool_calls:
                    total_tool_calls += len(tool_calls)
                    console.print(f"    Tool calls: {len(tool_calls)}")
                    
                    # OpenClaw handles tool execution, but we track it
                    for tc in tool_calls:
                        result.tool_calls.append({
                            "turn": turn_count,
                            "tool": tc.get("function", {}).get("name"),
                            "args": tc.get("function", {}).get("arguments"),
                        })
                
                # Check if conversation should end
                content = assistant_msg.get("content", "")
                if self._is_terminal(content, scenario):
                    console.print("  [green]Conversation ended naturally[/green]")
                    break
                
                # Check budget
                if total_tool_calls >= scenario.budgets.max_tool_calls:
                    console.print("  [yellow]Tool call budget exhausted[/yellow]")
                    break
                    
            except Exception as e:
                console.print(f"  [red]Error: {e}[/red]")
                result.success = False
                result.success_reason = f"Error: {e}"
                break
        
        elapsed_ms = int((time.time() - start_time) * 1000)
        
        # 5. Collect tool calls from mock server
        try:
            server_tool_calls = self.mock_tools.get_tool_calls()
            result.tool_calls = server_tool_calls
        except Exception:
            pass
        
        # 6. Compute metrics
        result.metrics = {
            "turns": turn_count,
            "tool_calls": len(result.tool_calls),
            "elapsed_ms": elapsed_ms,
        }
        
        # 7. Score using the consolidated scoring engine
        if scenario.scoring.get("checks"):
            # Build the result dict expected by score_episode
            response_parts = []
            for msg in result.messages:
                if msg.get("role") == "assistant":
                    response_parts.append(msg.get("content") or "")

            tool_counts: dict[str, int] = {}
            for tc in result.tool_calls:
                tool_name = tc.get("tool", "")
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

            scoring_input = {
                "response": "\n".join(response_parts),
                "tool_calls_raw": result.tool_calls,
                "tool_calls_by_type": tool_counts,
                "tool_calls_total": len(result.tool_calls),
            }

            score_result = score_episode(scoring_input, scenario.scoring)
            score_val = score_result.get("score")
            result.score = score_val if score_val is not None else 0.0
            result.success = score_result.get("failed", 0) == 0
            result.success_reason = (
                f"{score_result.get('passed', 0)}/{score_result.get('total_checks', 0)} checks passed"
            )
        else:
            result.success = True
            result.success_reason = "no scoring checks defined"

        console.print(f"  [bold]Score: {result.score:.0%}[/bold]")
        return result

    def _is_terminal(self, content: str, scenario: Scenario) -> bool:
        """Check if the conversation should end."""
        if not content:
            return False

        # Check for common termination patterns
        termination_phrases = [
            "HEARTBEAT_OK",
            "let me know if you need anything else",
            "is there anything else",
            "task complete",
        ]
        content_lower = content.lower()
        return any(phrase.lower() in content_lower for phrase in termination_phrases)


def run_comparison(
    scenario: Scenario,
    runner: EpisodeRunner,
    seeds: list[int] = [42, 123, 456],
) -> dict[str, Any]:
    """Run baseline vs optimized comparison across multiple seeds."""
    
    results = {"baseline": [], "optimized": []}
    
    for variant in ["baseline", "optimized"]:
        for seed in seeds:
            result = runner.run(scenario, variant=variant, seed=seed)
            results[variant].append(result)
    
    # Aggregate
    def avg_score(results_list):
        return sum(r.score for r in results_list) / len(results_list)
    
    def avg_tool_calls(results_list):
        return sum(r.metrics.get("tool_calls", 0) for r in results_list) / len(results_list)
    
    return {
        "scenario_id": scenario.id,
        "seeds": seeds,
        "baseline": {
            "avg_score": avg_score(results["baseline"]),
            "avg_tool_calls": avg_tool_calls(results["baseline"]),
            "success_rate": sum(1 for r in results["baseline"] if r.success) / len(results["baseline"]),
        },
        "optimized": {
            "avg_score": avg_score(results["optimized"]),
            "avg_tool_calls": avg_tool_calls(results["optimized"]),
            "success_rate": sum(1 for r in results["optimized"] if r.success) / len(results["optimized"]),
        },
        "improvement": {
            "score_delta": avg_score(results["optimized"]) - avg_score(results["baseline"]),
            "tool_calls_delta": avg_tool_calls(results["baseline"]) - avg_tool_calls(results["optimized"]),
        },
    }
