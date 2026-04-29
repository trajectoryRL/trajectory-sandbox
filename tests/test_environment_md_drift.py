"""Drift check: every endpoint in the mock services FastAPI app must be
referenced in ENVIRONMENT.md, and vice versa.

Keeps the shared environment contract in sync with the real service surface
so miners never see stale docs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent
SERVER = REPO_ROOT / "docker" / "mock_services" / "server.py"
SCENARIOS_DIR = REPO_ROOT / "scenarios"

# Endpoints that exist but are internal / not for agent consumption.
INTERNAL_PATHS = {
    "/health",
    "/state",
    "/reset",
    "/load_fixtures",
}


def _server_endpoints() -> set[str]:
    """Extract (METHOD, path) pairs from the FastAPI server, normalized."""
    text = SERVER.read_text()
    # e.g. @app.get("/api/v2/messages")
    pattern = re.compile(r'@app\.(get|post|patch|delete|put)\("([^"]+)"\)')
    return {_normalize(m.group(2)) for m in pattern.finditer(text)}


def _normalize(path: str) -> str:
    """Strip variability: FastAPI path params {x} → {} for matching."""
    return re.sub(r"\{[^}]+\}", "{}", path)


def _doc_paths(doc: str) -> set[str]:
    """Every bare absolute path mentioned in a markdown ENVIRONMENT.md."""
    # Grab http://host:port/path fragments
    urls = re.findall(r"http://localhost:8090(/[A-Za-z0-9_/{}\-.:]*)", doc)
    return {_normalize(u.rstrip("/")) if u != "/" else "/" for u in urls}


def _uses_mock_services(env_text: str) -> bool:
    """Scenario uses mock services iff its ENVIRONMENT.md documents real endpoints.

    A passing mention of `localhost:8090` (e.g. codebase_fix's "the server is
    running for framework uniformity, you don't need to touch it") doesn't
    count — only documented endpoint paths beyond /health and /state.
    """
    documented = _doc_paths(env_text)
    return bool(documented - {"/health", "/state"})


@pytest.mark.parametrize("scenario_dir", sorted(SCENARIOS_DIR.iterdir()))
def test_environment_md_covers_every_agent_endpoint(scenario_dir):
    env_path = scenario_dir / "ENVIRONMENT.md"
    if not env_path.exists():
        pytest.skip(f"{scenario_dir.name} has no ENVIRONMENT.md")
    env_text = env_path.read_text()
    if not _uses_mock_services(env_text):
        pytest.skip(f"{scenario_dir.name} doesn't use mock services")

    documented = _doc_paths(env_text)
    implemented = _server_endpoints() - {_normalize(p) for p in INTERNAL_PATHS}

    missing = implemented - documented
    # /health is documented even though it's "internal-ish" — allow that.
    missing.discard(_normalize("/health"))

    assert not missing, (
        f"ENVIRONMENT.md for {scenario_dir.name} is missing endpoints: {sorted(missing)}"
    )


@pytest.mark.parametrize("scenario_dir", sorted(SCENARIOS_DIR.iterdir()))
def test_environment_md_does_not_reference_nonexistent_endpoints(scenario_dir):
    env_path = scenario_dir / "ENVIRONMENT.md"
    if not env_path.exists():
        pytest.skip(f"{scenario_dir.name} has no ENVIRONMENT.md")
    env_text = env_path.read_text()
    if not _uses_mock_services(env_text):
        pytest.skip(f"{scenario_dir.name} doesn't use mock services")

    documented = _doc_paths(env_text)
    implemented = _server_endpoints()

    # /health and /state are real endpoints. Everything else in ENVIRONMENT.md
    # must also exist in server.py.
    bogus = documented - implemented
    assert not bogus, (
        f"ENVIRONMENT.md for {scenario_dir.name} references endpoints not in "
        f"server.py: {sorted(bogus)}"
    )
