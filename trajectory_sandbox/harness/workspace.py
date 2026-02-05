"""
Workspace manager - handles AGENTS.md swapping and file setup.
"""

import shutil
from pathlib import Path


class WorkspaceManager:
    """Manages the workspace directory that OpenClaw reads from."""

    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path)
        self.workspace_path.mkdir(parents=True, exist_ok=True)

    def clear(self):
        """Clear all files in workspace."""
        for f in self.workspace_path.iterdir():
            if f.is_file():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f)

    def swap_agents_md(self, fixtures_dir: Path, variant_filename: str):
        """
        Copy the specified AGENTS.md variant into the workspace.
        
        Args:
            fixtures_dir: Path to fixture directory
            variant_filename: e.g., "AGENTS.md.baseline" or "AGENTS.md.optimized"
        """
        source = fixtures_dir / variant_filename
        dest = self.workspace_path / "AGENTS.md"
        
        if source.exists():
            shutil.copy(source, dest)
        else:
            # Create empty if not found
            dest.write_text("# AGENTS.md\n\nNo specific instructions.\n")

    def copy_file(self, source: Path, dest_name: str | None = None):
        """Copy a file into the workspace."""
        dest_name = dest_name or source.name
        dest = self.workspace_path / dest_name
        if source.exists():
            shutil.copy(source, dest)

    def setup_from_scenario(self, fixtures_dir: Path, workspace_config: dict, variant: str):
        """
        Setup workspace from scenario configuration.
        
        Args:
            fixtures_dir: Path to fixture directory
            workspace_config: Scenario's workspace config (file mappings)
            variant: "baseline" or "optimized"
        """
        self.clear()
        
        for target_name, source_pattern in workspace_config.items():
            if source_pattern is None:
                continue
            
            # Handle ${variant} placeholder
            if "${variant}" in source_pattern:
                source_pattern = source_pattern.replace("${variant}", variant)
            
            source = fixtures_dir / source_pattern
            if source.exists():
                self.copy_file(source, target_name)

    def read_file(self, filename: str) -> str | None:
        """Read a file from workspace."""
        path = self.workspace_path / filename
        if path.exists():
            return path.read_text()
        return None

    def write_file(self, filename: str, content: str):
        """Write a file to workspace."""
        path = self.workspace_path / filename
        path.write_text(content)
