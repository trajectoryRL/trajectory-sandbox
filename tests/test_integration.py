"""Integration test for the full sandbox lifecycle.

Requires Docker. Run with:
    cd sandbox && pytest tests/test_integration.py -v -s

To skip if Docker is not available:
    pytest tests/ -v  (Docker tests auto-skip)
"""

import os
import sys

import pytest
import docker

from trajrl_bench import SandboxConfig, EvalSession


def docker_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


def sandbox_image_available() -> bool:
    try:
        client = docker.from_env()
        client.images.get("ghcr.io/trajectoryrl/trajrl-bench:latest")
        return True
    except Exception:
        return False


skip_no_docker = pytest.mark.skipif(
    not docker_available(), reason="Docker not available"
)
skip_no_image = pytest.mark.skipif(
    not sandbox_image_available(), reason="Sandbox image not built"
)


@skip_no_docker
class TestNetworkManager:
    """Test Docker network creation and teardown."""

    def test_create_and_destroy(self):
        from trajrl_bench.network import NetworkManager

        client = docker.from_env()
        mgr = NetworkManager(client, prefix="test_eval")

        net = mgr.create("test123")
        try:
            assert net.name == "test_eval_test123"
            # Verify network exists
            found = client.networks.get(net.id)
            assert found.attrs["Internal"] is True
            assert found.attrs["Labels"]["trajectoryrl.role"] == "eval_net"
        finally:
            mgr.destroy(net)

        # Verify it's gone
        with pytest.raises(docker.errors.NotFound):
            client.networks.get(net.id)


@skip_no_docker
@skip_no_image
class TestEvalSession:
    """Full lifecycle test — requires sandbox image to be built."""

    def test_session_lifecycle(self):
        config = SandboxConfig(
            sandbox_image="ghcr.io/trajectoryrl/trajrl-bench:latest",
            harness_image="nousresearch/hermes-agent:latest",
            harness_timeout_s=30,
        )

        with EvalSession(config) as session:
            # Load SKILL.md
            session.load_skill("# Test SKILL\n\nJust echo hello.\n")

            # Run one episode
            result = session.run_episode(
                episode_index=0,
                instruction_md="# Task\n\nRun `echo hello` in the sandbox.\n",
            )

            assert result.episode_index == 0
            assert result.error is None or result.error == ""


@skip_no_docker
class TestMockServicesLocal:
    """Test mock services server without Docker (direct FastAPI test client)."""

    def test_email_flow(self):
        from fastapi.testclient import TestClient
        # Import from the docker context
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "docker"))
        from mock_services.server import app, store

        client = TestClient(app)

        # Health check
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        # Load fixtures
        fixtures = {
            "inbox": [
                {"id": "email-1", "from": "alice@test.com", "subject": "P0 incident"},
                {"id": "email-2", "from": "bob@test.com", "subject": "Lunch?"},
            ],
            "slack_channels": {
                "incidents": {"name": "incidents", "messages": []},
                "general": {"name": "general", "messages": [{"text": "Good morning"}]},
            },
        }
        r = client.post("/load_fixtures", json=fixtures)
        assert r.status_code == 200

        # List emails
        r = client.get("/api/v2/messages")
        assert r.json()["total"] == 2

        # Send email
        r = client.post("/api/v2/messages", json={
            "from": "agent@test.com",
            "to": ["client@test.com"],
            "subject": "Status update",
            "body": "We are investigating the incident.",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "sent"

        # Post to Slack
        r = client.post("/slack/channels/incidents/messages", json={
            "text": "Incident update: investigating payment failures",
        })
        assert r.status_code == 200

        # Capture state for scoring
        r = client.get("/state")
        s = r.json()
        assert len(s["sent_emails"]) == 1
        assert len(s["slack_channels"]["incidents"]["messages"]) == 1
        assert len(s["action_log"]) == 2  # send_email + post_message

        # Reset
        r = client.post("/reset")
        assert r.status_code == 200

        # After reset, sent_emails gone, inbox back to fixtures
        r = client.get("/state")
        s = r.json()
        assert len(s["sent_emails"]) == 0
        assert len(s["emails"]) == 2

    def test_notion_flow(self):
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "docker"))
        from mock_services.server import app, store

        client = TestClient(app)

        # Load fixtures
        client.post("/load_fixtures", json={
            "tasks": [{"id": "t1", "title": "Existing task"}],
        })

        # Create tasks
        r = client.post("/notion/pages", json={"title": "Investigate root cause"})
        assert r.status_code == 200
        r = client.post("/notion/pages", json={"title": "Client communication"})
        assert r.status_code == 200
        r = client.post("/notion/pages", json={"title": "Post-incident review"})
        assert r.status_code == 200

        # Query — should have 4 (1 fixture + 3 created)
        r = client.post("/notion/databases/db1/query", json={})
        assert len(r.json()["results"]) == 4

    def test_calendar_flow(self):
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "docker"))
        from mock_services.server import app, store

        client = TestClient(app)
        client.post("/load_fixtures", json={"calendar": []})

        # Create event
        r = client.post("/calendar/events", json={
            "summary": "Post-incident review",
            "start": "2026-04-11T14:00:00",
            "end": "2026-04-11T15:00:00",
            "attendees": ["alice@test.com", "bob@test.com"],
        })
        assert r.status_code == 200
        event_id = r.json()["id"]

        # List events
        r = client.get("/calendar/events")
        assert len(r.json()) == 1

        # Delete event
        r = client.delete(f"/calendar/events/{event_id}")
        assert r.status_code == 200

        # Verify deletion
        r = client.get("/calendar/events")
        assert len(r.json()) == 0
