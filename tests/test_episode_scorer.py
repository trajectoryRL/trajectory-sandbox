"""Tests for EpisodeScorer — dry run, mock judge, full pipeline.

No API key needed — tests use dry_run mode or mock the judge response.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from trajrl_bench.episode_scorer import EpisodeScorer, ScoredEpisode
from trajrl_bench.judge import EpisodeJudge, JudgeResult, CriterionResult
from trajrl_bench.evidence import IncidentResponseEvidence
from trajrl_bench.fixture_factory import FixtureFactory


@pytest.fixture
def world():
    factory = FixtureFactory(epoch_seed="test_scorer", validator_salt="salt")
    return factory.generate_world()


@pytest.fixture
def episode(world):
    factory = FixtureFactory(epoch_seed="test_scorer", validator_salt="salt")
    return factory.generate_episode(0, world)


@pytest.fixture
def good_state(world, episode):
    """State simulating a competent agent."""
    pr_author = episode.metadata["pr_author"]
    pr_email = None
    for p in world.team:
        if p.full_name == pr_author:
            pr_email = p.email
            break
    pr_email = pr_email or f"unknown@{world.domain}"

    return {
        "emails": episode.to_dict()["inbox"],
        "sent_emails": [
            {"to": [world.client.email], "subject": "Status update",
             "body": f"Hi {world.client.first_name}, we're investigating. ETA: 2 hours."},
        ],
        "slack_channels": {
            "incidents": {"name": "incidents", "messages": [
                {"user": "agent", "text": "P0: Service disruption, investigating"},
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
             "data": {"summary": "PIR", "attendees": [world.user.email, pr_email]}},
        ],
        "gitea_issues": [], "gitea_prs": [], "gitea_comments": [],
        "gitea_refs": [], "gitea_files": [], "gitea_commits": [],
    }


def _mock_judge_result(quality=0.85):
    """Create a mock JudgeResult."""
    return JudgeResult(
        quality=quality,
        criteria=[
            CriterionResult(id=f"C{i}", score=1 if i <= 19 else 0, reason=f"reason {i}")
            for i in range(1, 23)
        ],
        summary="Good performance overall",
    )


class TestEpisodeScorerConstruction:
    def test_for_incident_response(self, world, episode):
        scorer = EpisodeScorer.for_incident_response(world, episode)
        assert scorer.world is world
        assert scorer.episode is episode
        assert isinstance(scorer.judge, EpisodeJudge)
        assert isinstance(scorer.evidence_extractor, IncidentResponseEvidence)

    def test_custom_judge(self, world, episode):
        judge = EpisodeJudge(api_key="custom", api_base="http://local", model="test")
        scorer = EpisodeScorer.for_incident_response(world, episode, judge=judge)
        assert scorer.judge.api_key == "custom"


class TestDryRun:
    def test_dry_run_returns_prompts(self, world, episode, good_state):
        scorer = EpisodeScorer.for_incident_response(world, episode)
        prompts = scorer.score_dry_run(
            transcript="agent did things",
            mock_state=good_state,
        )
        assert "system" in prompts
        assert "user" in prompts
        assert "C22" in prompts["system"]
        assert "Grounding Evidence" in prompts["user"]
        assert world.company in prompts["user"]

    def test_dry_run_includes_evidence(self, world, episode, good_state):
        scorer = EpisodeScorer.for_incident_response(world, episode)
        prompts = scorer.score_dry_run("transcript", good_state)
        # Evidence should show observed items
        assert "OBSERVED" in prompts["user"]


class TestScoringWithMockJudge:
    def test_score_returns_float(self, world, episode, good_state):
        scorer = EpisodeScorer.for_incident_response(world, episode)
        scorer.judge.score_episode = MagicMock(return_value=_mock_judge_result(0.85))

        quality = scorer.score("transcript", good_state)
        assert quality == 0.85

    def test_score_detailed_returns_full_result(self, world, episode, good_state):
        scorer = EpisodeScorer.for_incident_response(world, episode)
        scorer.judge.score_episode = MagicMock(return_value=_mock_judge_result(0.91))

        result = scorer.score_detailed("transcript", good_state)
        assert isinstance(result, ScoredEpisode)
        assert result.quality == 0.91
        assert len(result.judge_result.criteria) == 22
        assert len(result.evidence) == 10  # A1-A10
        assert len(result.evidence_text) > 0

    def test_score_passes_correct_args_to_judge(self, world, episode, good_state):
        scorer = EpisodeScorer.for_incident_response(world, episode)
        mock_score = MagicMock(return_value=_mock_judge_result())
        scorer.judge.score_episode = mock_score

        scorer.score("my transcript", good_state)

        # Verify judge was called with correct args
        call_args = mock_score.call_args
        assert call_args.kwargs["instruction_md"] == episode.instruction_md
        assert call_args.kwargs["transcript"] == "my transcript"
        assert "Grounding Evidence" in call_args.kwargs["evidence_text"]
        assert world.company in call_args.kwargs["world_context"]

    def test_score_handles_judge_error(self, world, episode, good_state):
        scorer = EpisodeScorer.for_incident_response(world, episode)
        scorer.judge.score_episode = MagicMock(
            return_value=JudgeResult(quality=0.0, error="API timeout")
        )

        result = scorer.score_detailed("transcript", good_state)
        assert result.quality == 0.0
        assert result.judge_result.error == "API timeout"

    def test_empty_state_still_works(self, world, episode):
        scorer = EpisodeScorer.for_incident_response(world, episode)
        scorer.judge.score_episode = MagicMock(return_value=_mock_judge_result(0.2))

        empty_state = {
            "emails": [], "sent_emails": [], "slack_channels": {},
            "tasks": [], "calendar_events": [], "action_log": [],
            "gitea_issues": [], "gitea_prs": [], "gitea_comments": [],
            "gitea_refs": [], "gitea_files": [], "gitea_commits": [],
        }
        quality = scorer.score("nothing happened", empty_state)
        assert quality == 0.2


class TestFullPipelineWithMockJudge:
    """Test the complete flow: fixtures → evidence → scorer → quality."""

    def test_four_episodes_with_scoring(self, world):
        """Simulate 4 episodes with mock judge, verify split-half delta."""
        factory = FixtureFactory(epoch_seed="test_scorer", validator_salt="salt")
        episodes = factory.generate_all_episodes(world)
        qualities = [0.45, 0.55, 0.72, 0.68]

        from trajrl_bench.types import EvalSessionResult, EpisodeResult

        result = EvalSessionResult()
        for i, (ep, q) in enumerate(zip(episodes, qualities)):
            scorer = EpisodeScorer.for_incident_response(world, ep)
            scorer.judge.score_episode = MagicMock(return_value=_mock_judge_result(q))

            # Simulate scoring with empty state (mock judge returns predetermined score)
            state = {"emails": [], "sent_emails": [], "slack_channels": {},
                     "tasks": [], "calendar_events": [], "action_log": [],
                     "gitea_issues": [], "gitea_prs": [], "gitea_comments": [],
                     "gitea_refs": [], "gitea_files": [], "gitea_commits": []}
            quality = scorer.score("transcript", state)

            result.episodes.append(EpisodeResult(episode_index=i, quality=quality))

        result.compute_scores()

        # Verify split-half delta matches spec example
        assert abs(result.early_mean - 0.50) < 1e-6
        assert abs(result.late_mean - 0.70) < 1e-6
        assert abs(result.delta - 0.20) < 1e-6
        assert abs(result.final_score - 0.66) < 0.01

    def test_scorer_per_episode_has_correct_metadata(self, world):
        """Each episode scorer has the right world + episode context."""
        factory = FixtureFactory(epoch_seed="test_scorer", validator_salt="salt")
        episodes = factory.generate_all_episodes(world)

        for i, ep in enumerate(episodes):
            scorer = EpisodeScorer.for_incident_response(world, ep)
            assert scorer.episode.metadata["rep_index"] == i
            if i == 2:
                assert scorer.episode.metadata["is_recurring"] is True
            if i == 3:
                assert scorer.episode.metadata["is_evolving"] is True
