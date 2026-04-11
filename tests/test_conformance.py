"""Conformance tests for mock service endpoints.

Verifies that mock services respond correctly to the HTTP/SMTP protocols
that agents use via curl/smtplib. Catches API regressions and quirks
before they invalidate scores.

Inspired by ClawsBench's 328-test conformance suite (see spec §6a).
"""

import os
import sys
import json

import pytest

# Ensure mock_services is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "docker"))

from fastapi.testclient import TestClient
from mock_services.server import app, store


@pytest.fixture(autouse=True)
def reset_store():
    """Reset store before each test."""
    store.load_fixtures_from_dict({})
    yield
    store.reset()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def loaded_client(client):
    """Client with realistic fixtures loaded."""
    fixtures = {
        "inbox": [
            {"id": "e1", "from": "alice@test.com", "to": ["user@test.com"], "subject": "Hello", "body": "Hi there"},
            {"id": "e2", "from": "bob@test.com", "to": ["user@test.com"], "subject": "Urgent", "body": "P0 incident",
             "flags": ["urgent"]},
            {"id": "e3", "from": "cto@test.com", "to": ["user@test.com"], "subject": "CONFIDENTIAL", "body": "Secret"},
        ],
        "slack_channels": {
            "general": {"name": "general", "messages": [
                {"id": "m1", "text": "Good morning", "user": "alice", "timestamp": "2026-04-10T09:00:00"},
            ]},
            "incidents": {"name": "incidents", "messages": []},
            "engineering": {"name": "engineering", "messages": [
                {"id": "m2", "text": "Deploy looks good", "user": "bob", "timestamp": "2026-04-10T08:00:00"},
            ]},
        },
        "tasks": [
            {"id": "t1", "title": "Fix bug", "status": "todo"},
            {"id": "t2", "title": "Review PR", "status": "in_progress"},
        ],
        "calendar": [
            {"id": "cal1", "summary": "Standup", "start": "2026-04-10T09:00:00", "end": "2026-04-10T09:30:00",
             "attendees": ["alice@test.com", "bob@test.com"]},
            {"id": "cal2", "summary": "Board meeting", "start": "2026-04-10T14:00:00", "end": "2026-04-10T15:00:00"},
        ],
        "gitea_issues": [
            {"id": "i1", "number": 42, "title": "Bug in payments", "body": "Failing since deploy", "state": "open",
             "user": "dana", "labels": ["bug", "P0"]},
        ],
        "gitea_prs": [
            {"id": "p1", "number": 891, "title": "Fix connection pool", "body": "Bumps timeout",
             "state": "merged", "user": "dana"},
        ],
        "gitea_refs": [
            {"ref": "refs/heads/main", "object": {"sha": "abc123"}},
        ],
        "gitea_files": [
            {"path": "src/main.py", "content": "print('hello')", "encoding": "utf-8"},
        ],
        "gitea_commits": [
            {"sha": "abc123", "message": "Fix pool timeout", "author": "dana"},
        ],
    }
    client.post("/load_fixtures", json=fixtures)
    return client


# =========================================================================
# System endpoints
# =========================================================================

class TestSystemEndpoints:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "email" in data["services"]
        assert data["backend"] == "sqlite"

    def test_load_fixtures(self, client):
        r = client.post("/load_fixtures", json={"inbox": [{"id": "x", "subject": "test"}]})
        assert r.status_code == 200
        assert "inbox" in r.json()["keys"]

    def test_state_returns_all_tables(self, loaded_client):
        r = loaded_client.get("/state")
        assert r.status_code == 200
        state = r.json()
        expected_keys = {"emails", "sent_emails", "slack_channels", "tasks",
                         "calendar_events", "gitea_issues", "gitea_prs",
                         "gitea_comments", "gitea_refs", "gitea_files",
                         "gitea_commits", "action_log"}
        assert set(state.keys()) == expected_keys

    def test_reset_restores_fixtures(self, loaded_client):
        # Mutate state
        loaded_client.post("/api/v2/messages", json={"from": "x", "to": ["y"], "subject": "z", "body": "w"})
        loaded_client.post("/notion/pages", json={"title": "new task"})

        # Verify mutations exist
        state = loaded_client.get("/state").json()
        assert len(state["sent_emails"]) == 1
        assert len(state["tasks"]) == 3  # 2 fixture + 1 new

        # Reset
        loaded_client.post("/reset")

        # Verify restored
        state = loaded_client.get("/state").json()
        assert len(state["sent_emails"]) == 0
        assert len(state["tasks"]) == 2  # back to fixtures
        assert len(state["action_log"]) == 0

    def test_double_reset_is_idempotent(self, loaded_client):
        loaded_client.post("/reset")
        loaded_client.post("/reset")
        state = loaded_client.get("/state").json()
        assert len(state["emails"]) == 3


# =========================================================================
# Email conformance
# =========================================================================

class TestEmailConformance:
    def test_list_emails(self, loaded_client):
        r = loaded_client.get("/api/v2/messages")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

    def test_list_emails_empty(self, client):
        client.post("/load_fixtures", json={"inbox": []})
        r = client.get("/api/v2/messages")
        assert r.json()["total"] == 0

    def test_send_email(self, loaded_client):
        r = loaded_client.post("/api/v2/messages", json={
            "from": "agent@test.com",
            "to": ["client@test.com"],
            "subject": "Update",
            "body": "Status update here",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "sent"
        assert "id" in r.json()

        # Verify it appears in sent_emails, not inbox
        state = loaded_client.get("/state").json()
        assert len(state["sent_emails"]) == 1
        assert state["sent_emails"][0]["subject"] == "Update"
        assert len(state["emails"]) == 3  # inbox unchanged

    def test_send_email_logged(self, loaded_client):
        loaded_client.post("/api/v2/messages", json={
            "from": "a", "to": ["b"], "subject": "s", "body": "b",
        })
        state = loaded_client.get("/state").json()
        actions = [a for a in state["action_log"] if a["action"] == "send"]
        assert len(actions) == 1

    def test_delete_email(self, loaded_client):
        r = loaded_client.delete("/api/v1/messages/e1")
        assert r.status_code == 200
        state = loaded_client.get("/state").json()
        assert len(state["emails"]) == 2
        assert all(e["id"] != "e1" for e in state["emails"])

    def test_delete_email_not_found(self, loaded_client):
        r = loaded_client.delete("/api/v1/messages/nonexistent")
        assert r.status_code == 404


# =========================================================================
# Slack conformance
# =========================================================================

class TestSlackConformance:
    def test_list_channels(self, loaded_client):
        r = loaded_client.get("/slack/channels")
        assert r.status_code == 200
        channels = r.json()
        names = {c["name"] for c in channels}
        assert names == {"general", "incidents", "engineering"}

    def test_read_messages(self, loaded_client):
        r = loaded_client.get("/slack/channels/general/messages")
        assert r.status_code == 200
        msgs = r.json()
        assert len(msgs) == 1
        assert msgs[0]["text"] == "Good morning"

    def test_read_messages_empty_channel(self, loaded_client):
        r = loaded_client.get("/slack/channels/incidents/messages")
        assert r.status_code == 200
        assert r.json() == []

    def test_read_messages_not_found(self, loaded_client):
        r = loaded_client.get("/slack/channels/nonexistent/messages")
        assert r.status_code == 404

    def test_post_message(self, loaded_client):
        r = loaded_client.post("/slack/channels/incidents/messages", json={
            "text": "P0 incident update",
            "user": "agent",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "posted"

        # Verify message appears in channel
        msgs = loaded_client.get("/slack/channels/incidents/messages").json()
        assert len(msgs) == 1
        assert msgs[0]["text"] == "P0 incident update"

    def test_post_message_not_found(self, loaded_client):
        r = loaded_client.post("/slack/channels/nonexistent/messages", json={"text": "hi"})
        assert r.status_code == 404

    def test_post_message_logged(self, loaded_client):
        loaded_client.post("/slack/channels/incidents/messages", json={"text": "test"})
        state = loaded_client.get("/state").json()
        actions = [a for a in state["action_log"] if a["action"] == "post_message"]
        assert len(actions) == 1
        assert actions[0]["data"]["channel"] == "incidents"

    def test_add_reaction(self, loaded_client):
        r = loaded_client.post("/slack/reactions", json={
            "channel": "general", "message_id": "m1", "emoji": "thumbsup",
        })
        assert r.status_code == 200


# =========================================================================
# Notion/Tasks conformance
# =========================================================================

class TestNotionConformance:
    def test_query_tasks(self, loaded_client):
        r = loaded_client.post("/notion/databases/db1/query", json={})
        assert r.status_code == 200
        assert len(r.json()["results"]) == 2

    def test_create_task(self, loaded_client):
        r = loaded_client.post("/notion/pages", json={
            "title": "New task",
            "status": "todo",
        })
        assert r.status_code == 200
        assert "id" in r.json()
        assert r.json()["title"] == "New task"

        # Verify count
        tasks = loaded_client.post("/notion/databases/db1/query", json={}).json()["results"]
        assert len(tasks) == 3

    def test_update_task(self, loaded_client):
        r = loaded_client.patch("/notion/pages/t1", json={"status": "done"})
        assert r.status_code == 200
        assert r.json()["status"] == "done"
        assert r.json()["title"] == "Fix bug"  # other fields preserved

    def test_update_task_not_found(self, loaded_client):
        r = loaded_client.patch("/notion/pages/nonexistent", json={"status": "done"})
        assert r.status_code == 404


# =========================================================================
# Calendar conformance
# =========================================================================

class TestCalendarConformance:
    def test_list_events(self, loaded_client):
        r = loaded_client.get("/calendar/events")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_create_event(self, loaded_client):
        r = loaded_client.post("/calendar/events", json={
            "summary": "Post-incident review",
            "start": "2026-04-11T10:00:00",
            "end": "2026-04-11T11:00:00",
            "attendees": ["alice@test.com"],
        })
        assert r.status_code == 200
        assert "id" in r.json()

        events = loaded_client.get("/calendar/events").json()
        assert len(events) == 3

    def test_delete_event(self, loaded_client):
        r = loaded_client.delete("/calendar/events/cal1")
        assert r.status_code == 200
        events = loaded_client.get("/calendar/events").json()
        assert len(events) == 1

    def test_delete_event_not_found(self, loaded_client):
        r = loaded_client.delete("/calendar/events/nonexistent")
        assert r.status_code == 404

    def test_create_event_with_attendees(self, loaded_client):
        r = loaded_client.post("/calendar/events", json={
            "summary": "Review",
            "start": "2026-04-11T14:00:00",
            "end": "2026-04-11T15:00:00",
            "attendees": ["dana@test.com", "bob@test.com"],
        })
        event = r.json()
        assert "dana@test.com" in event["attendees"]


# =========================================================================
# Gitea conformance
# =========================================================================

class TestGiteaConformance:
    def test_list_issues(self, loaded_client):
        r = loaded_client.get("/api/v1/repos/org/repo/issues")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_get_issue(self, loaded_client):
        r = loaded_client.get("/api/v1/repos/org/repo/issues/42")
        assert r.status_code == 200
        assert r.json()["title"] == "Bug in payments"

    def test_get_issue_not_found(self, loaded_client):
        r = loaded_client.get("/api/v1/repos/org/repo/issues/999")
        assert r.status_code == 404

    def test_list_pulls(self, loaded_client):
        r = loaded_client.get("/api/v1/repos/org/repo/pulls")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_get_pull(self, loaded_client):
        r = loaded_client.get("/api/v1/repos/org/repo/pulls/891")
        assert r.status_code == 200
        assert r.json()["state"] == "merged"

    def test_get_pull_not_found(self, loaded_client):
        r = loaded_client.get("/api/v1/repos/org/repo/pulls/999")
        assert r.status_code == 404

    def test_add_comment(self, loaded_client):
        r = loaded_client.post("/api/v1/repos/org/repo/issues/42/comments", json={
            "body": "Investigating now",
        })
        assert r.status_code == 200
        assert r.json()["issue_number"] == 42
        assert r.json()["body"] == "Investigating now"

        state = loaded_client.get("/state").json()
        assert len(state["gitea_comments"]) == 1

    def test_list_refs(self, loaded_client):
        r = loaded_client.get("/api/v1/repos/org/repo/git/refs")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_get_file_contents(self, loaded_client):
        r = loaded_client.get("/api/v1/repos/org/repo/contents/src/main.py")
        assert r.status_code == 200
        assert r.json()["content"] == "print('hello')"

    def test_get_file_not_found(self, loaded_client):
        r = loaded_client.get("/api/v1/repos/org/repo/contents/nonexistent.py")
        assert r.status_code == 404

    def test_list_commits(self, loaded_client):
        r = loaded_client.get("/api/v1/repos/org/repo/commits")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["message"] == "Fix pool timeout"

    def test_owner_repo_agnostic(self, loaded_client):
        """Endpoints work with any owner/repo path."""
        r1 = loaded_client.get("/api/v1/repos/org/repo/issues")
        r2 = loaded_client.get("/api/v1/repos/other/different/issues")
        assert r1.json() == r2.json()


# =========================================================================
# Cross-service scoring conformance
# =========================================================================

class TestScoringConformance:
    """Tests that verify state capture works correctly for automated scoring."""

    def test_action_log_tracks_all_mutations(self, loaded_client):
        """Every mutation should appear in action_log."""
        loaded_client.post("/api/v2/messages", json={"from": "a", "to": ["b"], "subject": "s", "body": "b"})
        loaded_client.post("/slack/channels/incidents/messages", json={"text": "update"})
        loaded_client.post("/notion/pages", json={"title": "task"})
        loaded_client.post("/calendar/events", json={"summary": "event", "start": "t", "end": "t"})
        loaded_client.post("/api/v1/repos/o/r/issues/42/comments", json={"body": "comment"})

        state = loaded_client.get("/state").json()
        services = {a["service"] for a in state["action_log"]}
        assert services == {"email", "slack", "notion", "calendar", "gitea"}
        assert len(state["action_log"]) == 5

    def test_sent_emails_separate_from_inbox(self, loaded_client):
        """Sent emails must be in sent_emails, not inbox."""
        loaded_client.post("/api/v2/messages", json={
            "from": "agent@test.com", "to": ["client@test.com"],
            "subject": "Update", "body": "Content",
        })
        state = loaded_client.get("/state").json()
        assert len(state["emails"]) == 3  # inbox unchanged
        assert len(state["sent_emails"]) == 1
        # sent email should not have same IDs as inbox emails
        inbox_ids = {e["id"] for e in state["emails"]}
        sent_ids = {e["id"] for e in state["sent_emails"]}
        assert inbox_ids.isdisjoint(sent_ids)

    def test_slack_mutation_visible_in_state(self, loaded_client):
        """Posted messages must be visible in state dump."""
        loaded_client.post("/slack/channels/incidents/messages", json={"text": "P0 active"})
        loaded_client.post("/slack/channels/incidents/messages", json={"text": "Root cause found"})

        state = loaded_client.get("/state").json()
        msgs = state["slack_channels"]["incidents"]["messages"]
        assert len(msgs) == 2
        assert msgs[0]["text"] == "P0 active"
        assert msgs[1]["text"] == "Root cause found"

    def test_snapshot_restore_deterministic(self, loaded_client):
        """Two resets from same fixtures produce identical state."""
        loaded_client.post("/api/v2/messages", json={"from": "a", "to": ["b"], "subject": "s", "body": "b"})
        loaded_client.post("/reset")
        state1 = loaded_client.get("/state").json()

        loaded_client.post("/slack/channels/incidents/messages", json={"text": "different mutation"})
        loaded_client.post("/reset")
        state2 = loaded_client.get("/state").json()

        # Remove timestamps from action_log comparison (both should be empty after reset)
        assert state1["emails"] == state2["emails"]
        assert state1["sent_emails"] == state2["sent_emails"]
        assert state1["tasks"] == state2["tasks"]
        assert state1["action_log"] == state2["action_log"] == []
