"""
CLI for ClawBench.
"""

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .harness.scenario import Scenario
from .harness.episode import EpisodeRunner, run_comparison

app = typer.Typer(help="ClawBench - Evaluate AGENTS.md policies")
console = Console()


@app.command()
def run(
    scenario_path: str = typer.Argument(..., help="Path to scenario JSON file"),
    variant: str = typer.Option("baseline", help="AGENTS.md variant: baseline or optimized"),
    seed: int = typer.Option(42, help="Random seed"),
    openclaw_url: str = typer.Option("http://localhost:3000", help="OpenClaw Gateway URL"),
    mock_tools_url: str = typer.Option("http://localhost:3001", help="Mock tools server URL"),
    workspace: str = typer.Option("./workspace", help="Workspace directory"),
    fixtures: str = typer.Option("./fixtures", help="Fixtures directory"),
):
    """Run a single scenario."""
    console.print(f"[bold blue]Loading scenario:[/bold blue] {scenario_path}")
    
    scenario = Scenario.load(scenario_path)
    runner = EpisodeRunner(
        openclaw_url=openclaw_url,
        mock_tools_url=mock_tools_url,
        workspace_path=workspace,
        fixtures_path=fixtures,
    )
    
    result = runner.run(scenario, variant=variant, seed=seed)
    
    # Print result
    console.print("\n[bold]Result:[/bold]")
    console.print(f"  Success: {result.success}")
    console.print(f"  Score: {result.score:.0%}")
    console.print(f"  Tool calls: {result.metrics.get('tool_calls', 0)}")
    console.print(f"  Turns: {result.metrics.get('turns', 0)}")


@app.command()
def compare(
    scenario_path: str = typer.Argument(..., help="Path to scenario JSON file"),
    seeds: str = typer.Option("42,123,456", help="Comma-separated seeds"),
    openclaw_url: str = typer.Option("http://localhost:3000", help="OpenClaw Gateway URL"),
    mock_tools_url: str = typer.Option("http://localhost:3001", help="Mock tools server URL"),
    workspace: str = typer.Option("./workspace", help="Workspace directory"),
    fixtures: str = typer.Option("./fixtures", help="Fixtures directory"),
    output: str = typer.Option(None, help="Output JSON file for results"),
):
    """Compare baseline vs optimized AGENTS.md."""
    console.print(f"[bold blue]Comparing policies for:[/bold blue] {scenario_path}")
    
    scenario = Scenario.load(scenario_path)
    runner = EpisodeRunner(
        openclaw_url=openclaw_url,
        mock_tools_url=mock_tools_url,
        workspace_path=workspace,
        fixtures_path=fixtures,
    )
    
    seed_list = [int(s) for s in seeds.split(",")]
    comparison = run_comparison(scenario, runner, seeds=seed_list)
    
    # Print comparison table
    table = Table(title=f"Comparison: {scenario.id}")
    table.add_column("Metric", style="cyan")
    table.add_column("Baseline", style="yellow")
    table.add_column("Optimized", style="green")
    table.add_column("Delta", style="magenta")
    
    bl = comparison["baseline"]
    op = comparison["optimized"]
    imp = comparison["improvement"]
    
    table.add_row(
        "Avg Score",
        f"{bl['avg_score']:.0%}",
        f"{op['avg_score']:.0%}",
        f"{imp['score_delta']:+.0%}",
    )
    table.add_row(
        "Avg Tool Calls",
        f"{bl['avg_tool_calls']:.1f}",
        f"{op['avg_tool_calls']:.1f}",
        f"{imp['tool_calls_delta']:+.1f}",
    )
    table.add_row(
        "Success Rate",
        f"{bl['success_rate']:.0%}",
        f"{op['success_rate']:.0%}",
        "",
    )
    
    console.print(table)
    
    if output:
        Path(output).write_text(json.dumps(comparison, indent=2))
        console.print(f"\nResults saved to: {output}")


@app.command()
def check_health(
    openclaw_url: str = typer.Option("http://localhost:3000", help="OpenClaw Gateway URL"),
    mock_tools_url: str = typer.Option("http://localhost:3001", help="Mock tools server URL"),
):
    """Check if services are running."""
    from .harness.client import OpenClawClient, MockToolsClient
    
    oc = OpenClawClient(openclaw_url)
    mt = MockToolsClient(mock_tools_url)
    
    console.print("[bold]Health Check[/bold]")
    
    oc_health = oc.health()
    console.print(f"  OpenClaw ({openclaw_url}): {'[green]OK[/green]' if oc_health else '[red]FAILED[/red]'}")
    
    mt_health = mt.health()
    console.print(f"  Mock Tools ({mock_tools_url}): {'[green]OK[/green]' if mt_health else '[red]FAILED[/red]'}")


@app.command()
def test_mock_tools(
    mock_tools_url: str = typer.Option("http://localhost:3001", help="Mock tools server URL"),
    scenario: str = typer.Option("inbox_triage", help="Scenario name"),
):
    """Test mock tools server directly."""
    from .harness.client import MockToolsClient
    
    mt = MockToolsClient(mock_tools_url)
    
    console.print(f"[bold]Testing mock tools for scenario:[/bold] {scenario}")
    
    # Set scenario
    mt.set_scenario(scenario)
    console.print("  Scenario set")
    
    # Test inbox.list
    result = mt.call_tool("inbox.list", {})
    console.print(f"  inbox.list: {len(result.get('messages', []))} messages")
    
    for msg in result.get("messages", [])[:3]:
        console.print(f"    - {msg['sender']}: {msg['subject'][:40]}...")


if __name__ == "__main__":
    app()
