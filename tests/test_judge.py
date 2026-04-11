"""Tests for the LLM judge — prompt construction, response parsing, dry run.

No API key needed — tests use dry_run mode and mock LLM responses.
"""

import json
import pytest

from trajectory_sandbox.judge import (
    EpisodeJudge, JudgeResult, CriterionResult,
    SYSTEM_PROMPT, CRITERIA_INCIDENT_RESPONSE,
)
from trajectory_sandbox.evidence import IncidentResponseEvidence
from trajectory_sandbox.fixture_factory import FixtureFactory


@pytest.fixture
def world():
    factory = FixtureFactory(epoch_seed="test_judge", validator_salt="salt")
    return factory.generate_world()


@pytest.fixture
def episode(world):
    factory = FixtureFactory(epoch_seed="test_judge", validator_salt="salt")
    return factory.generate_episode(0, world)


@pytest.fixture
def judge():
    return EpisodeJudge(api_key="test", model="test-model")


class TestPromptConstruction:
    def test_dry_run_returns_system_and_user(self, judge, world, episode):
        evidence_ext = IncidentResponseEvidence(world, episode)
        state = {
            "emails": [], "sent_emails": [], "slack_channels": {},
            "tasks": [], "calendar_events": [], "action_log": [],
            "gitea_issues": [], "gitea_prs": [], "gitea_comments": [],
            "gitea_refs": [], "gitea_files": [], "gitea_commits": [],
        }
        prompts = judge.score_episode_dry_run(
            instruction_md="Triage your inbox.",
            transcript="$ curl http://localhost:8090/health\n{ok}",
            evidence_text=evidence_ext.format_for_judge(state),
            world_context=judge.format_world(world),
        )
        assert "system" in prompts
        assert "user" in prompts
        assert "C1" in prompts["system"]
        assert "C22" in prompts["system"]

    def test_system_prompt_has_all_22_criteria(self):
        full = SYSTEM_PROMPT + CRITERIA_INCIDENT_RESPONSE
        for i in range(1, 23):
            assert f"C{i}" in full, f"Missing criterion C{i}"

    def test_world_context_includes_confidential_topic(self, judge, world):
        ctx = judge.format_world(world)
        assert "CONFIDENTIAL" in ctx
        assert world.confidential_topic in ctx
        assert world.client.email in ctx
        assert world.company in ctx

    def test_evidence_text_includes_observations(self, world, episode):
        evidence_ext = IncidentResponseEvidence(world, episode)
        state = {
            "emails": [], "sent_emails": [
                {"to": [world.client.email], "subject": "Update", "body": "Working on it"},
            ],
            "slack_channels": {
                "incidents": {"name": "incidents", "messages": [
                    {"user": "agent", "text": "P0 update"},
                ]},
            },
            "tasks": [], "calendar_events": [],
            "action_log": [
                {"service": "slack", "action": "post_message",
                 "data": {"channel": "incidents", "text": "P0 update"}},
                {"service": "email", "action": "send",
                 "data": {"to": [world.client.email], "subject": "Update"}},
            ],
            "gitea_issues": [], "gitea_prs": [], "gitea_comments": [],
            "gitea_refs": [], "gitea_files": [], "gitea_commits": [],
        }
        text = evidence_ext.format_for_judge(state)
        assert "OBSERVED" in text
        assert "Grounding Evidence" in text
        assert "Sent Emails" in text
        assert "Slack Messages" in text

    def test_user_prompt_includes_all_sections(self, judge, world, episode):
        evidence_ext = IncidentResponseEvidence(world, episode)
        state = {
            "emails": [], "sent_emails": [], "slack_channels": {},
            "tasks": [], "calendar_events": [], "action_log": [],
            "gitea_issues": [], "gitea_prs": [], "gitea_comments": [],
            "gitea_refs": [], "gitea_files": [], "gitea_commits": [],
        }
        prompts = judge.score_episode_dry_run(
            instruction_md="Do the task.",
            transcript="transcript here",
            evidence_text=evidence_ext.format_for_judge(state),
            world_context=judge.format_world(world),
        )
        user = prompts["user"]
        assert "## Task" in user
        assert "## World Context" in user
        assert "## Agent Transcript" in user
        assert "## Grounding Evidence" in user

    def test_transcript_truncation(self, judge, world):
        long_transcript = "x" * 20000
        prompts = judge.score_episode_dry_run(
            instruction_md="task",
            transcript=long_transcript,
            evidence_text="evidence",
            world_context="context",
        )
        # Should be truncated to 10000 chars
        assert len(long_transcript) > 10000
        assert "x" * 10000 in prompts["user"]
        assert "x" * 10001 not in prompts["user"]


class TestResponseParsing:
    def _make_response(self, criteria_scores, quality=None, summary="Good"):
        criteria = [
            {"id": f"C{i+1}", "score": s, "reason": f"Reason for C{i+1}"}
            for i, s in enumerate(criteria_scores)
        ]
        if quality is None:
            quality = sum(criteria_scores) / len(criteria_scores)
        return json.dumps({
            "criteria": criteria,
            "quality": quality,
            "summary": summary,
        })

    def test_parse_perfect_response(self, judge):
        raw = self._make_response([1] * 22, quality=1.0)
        result = judge._parse_response(raw)
        assert result.quality == 1.0
        assert len(result.criteria) == 22
        assert all(c.score == 1 for c in result.criteria)
        assert result.error is None

    def test_parse_mixed_response(self, judge):
        scores = [1, 1, 0, 1, 1, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 1]
        raw = self._make_response(scores)
        result = judge._parse_response(raw)
        assert len(result.criteria) == 22
        assert result.criteria[2].score == 0
        assert result.criteria[2].id == "C3"

    def test_parse_markdown_wrapped(self, judge):
        """Response wrapped in ```json ... ```"""
        inner = self._make_response([1] * 5, quality=0.8)
        raw = f"```json\n{inner}\n```"
        result = judge._parse_response(raw)
        assert result.quality == 0.8
        assert len(result.criteria) == 5

    def test_parse_invalid_json(self, judge):
        result = judge._parse_response("This is not JSON")
        assert result.error is not None
        assert result.quality == 0.0

    def test_parse_empty_criteria(self, judge):
        raw = json.dumps({"criteria": [], "quality": 0.0, "summary": "Nothing done"})
        result = judge._parse_response(raw)
        assert result.quality == 0.0
        assert len(result.criteria) == 0

    def test_quality_preserved(self, judge):
        """Quality can be adjusted by judge beyond simple fraction."""
        raw = self._make_response([1, 1, 0], quality=0.72)
        result = judge._parse_response(raw)
        assert result.quality == 0.72  # judge's adjusted score, not 0.67

    def test_summary_preserved(self, judge):
        raw = self._make_response([1], quality=1.0, summary="Excellent work")
        result = judge._parse_response(raw)
        assert result.summary == "Excellent work"


class TestEndToEnd:
    """Test the full flow without an API call."""

    def test_full_dry_run_pipeline(self, world, episode):
        """Full pipeline: fixtures → evidence → prompts → (would score)."""
        # Generate fixtures
        factory = FixtureFactory(epoch_seed="test_judge", validator_salt="salt")
        world = factory.generate_world()
        ep = factory.generate_episode(0, world)

        # Simulate state after "good" agent
        state = {
            "emails": ep.to_dict()["inbox"],
            "sent_emails": [
                {"to": [world.client.email], "subject": "Status update",
                 "body": "We've identified the issue. ETA: 2 hours."},
            ],
            "slack_channels": {
                "incidents": {"name": "incidents", "messages": [
                    {"user": "agent", "text": "P0: Investigating service disruption"},
                ]},
                "general": {"name": "general", "messages": []},
                **{ch: {"name": ch, "messages": []}
                   for ch in world.slack_channels if ch not in ("incidents", "general")},
            },
            "tasks": [],
            "calendar_events": [],
            "action_log": [
                {"service": "slack", "action": "post_message",
                 "data": {"channel": "incidents", "text": "P0 update"}},
                {"service": "email", "action": "send",
                 "data": {"to": [world.client.email]}},
                {"service": "notion", "action": "create_page", "data": {"title": "Investigate"}},
                {"service": "notion", "action": "create_page", "data": {"title": "Client comm"}},
                {"service": "notion", "action": "create_page", "data": {"title": "PIR"}},
                {"service": "calendar", "action": "create_event",
                 "data": {"summary": "PIR", "attendees": [world.user.email]}},
            ],
            "gitea_issues": [], "gitea_prs": [], "gitea_comments": [],
            "gitea_refs": [], "gitea_files": [], "gitea_commits": [],
        }

        # Extract evidence
        evidence_ext = IncidentResponseEvidence(world, ep)
        evidence_text = evidence_ext.format_for_judge(state)

        # Build prompts (dry run)
        judge = EpisodeJudge()
        prompts = judge.score_episode_dry_run(
            instruction_md=ep.instruction_md,
            transcript="[simulated transcript]",
            evidence_text=evidence_text,
            world_context=judge.format_world(world),
        )

        # Verify prompts are well-formed
        assert len(prompts["system"]) > 1000  # substantial system prompt
        assert len(prompts["user"]) > 500     # substantial user prompt
        assert world.company in prompts["user"]
        assert "C22" in prompts["system"]
        assert "OBSERVED" in prompts["user"] or "NOT OBSERVED" in prompts["user"]
