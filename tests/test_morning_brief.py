"""Tests for the morning_brief scenario: fixtures, evidence, judge criteria, scorer."""

import pytest
from trajrl_bench.fixture_factory import FixtureFactory, World, EpisodeFixtures, SCENARIOS
from trajrl_bench.evidence import MorningBriefEvidence
from trajrl_bench.judge import EpisodeJudge, SCENARIO_CRITERIA, CRITERIA_MORNING_BRIEF
from trajrl_bench.episode_scorer import EpisodeScorer


# ---------------------------------------------------------------------------
# Fixture factory
# ---------------------------------------------------------------------------

class TestMorningBriefFixtures:
    def _factory(self, scenario="morning_brief"):
        return FixtureFactory(epoch_seed="test123", validator_salt="salt456",
                              scenario=scenario)

    def test_scenario_in_registry(self):
        assert "morning_brief" in SCENARIOS

    def test_generates_world(self):
        f = self._factory()
        world = f.generate_world()
        assert world.company
        assert len(world.team) >= 6

    def test_generates_episode(self):
        f = self._factory()
        world = f.generate_world()
        ep = f.generate_episode(0, world)
        assert isinstance(ep, EpisodeFixtures)
        assert ep.instruction_md
        assert "morning" in ep.instruction_md.lower()
        assert len(ep.inbox) >= 8
        assert ep.metadata["scenario"] == "morning_brief"

    def test_deterministic(self):
        f1 = self._factory()
        f2 = self._factory()
        w1 = f1.generate_world()
        w2 = f2.generate_world()
        ep1 = f1.generate_episode(0, w1)
        ep2 = f2.generate_episode(0, w2)
        assert ep1.instruction_md == ep2.instruction_md
        assert len(ep1.inbox) == len(ep2.inbox)

    def test_four_episodes_different(self):
        f = self._factory()
        world = f.generate_world()
        episodes = [f.generate_episode(i, world) for i in range(4)]
        seeds = [e.metadata["rep_seed"] for e in episodes]
        assert len(set(seeds)) == 4

    def test_recurring_rep3(self):
        f = self._factory()
        world = f.generate_world()
        ep0 = f.generate_episode(0, world)
        ep2 = f.generate_episode(2, world)
        assert ep2.metadata["is_recurring"] is True
        assert ep0.metadata["blocker_reason"] == ep2.metadata["blocker_reason"]

    def test_evolving_rep4(self):
        f = self._factory()
        world = f.generate_world()
        ep3 = f.generate_episode(3, world)
        assert ep3.metadata["is_evolving"] is True
        assert ep3.metadata["evolving_detail"] is not None

    def test_calendar_has_conflict(self):
        f = self._factory()
        world = f.generate_world()
        ep = f.generate_episode(0, world)
        # Should have 4 events (3 regular + 1 conflict)
        assert len(ep.calendar) == 4
        # At least two events share a start time
        starts = [e["start"] for e in ep.calendar]
        assert len(starts) > len(set(starts)), "Expected at least one scheduling conflict"

    def test_confidential_email_present(self):
        f = self._factory()
        world = f.generate_world()
        ep = f.generate_episode(0, world)
        confidential = [e for e in ep.inbox if "confidential" in e.get("subject", "").lower()
                        or "confidential" in str(e.get("flags", []))]
        assert len(confidential) >= 1

    def test_incident_response_still_works(self):
        """Ensure default scenario is unchanged."""
        f = FixtureFactory(epoch_seed="test", validator_salt="salt",
                           scenario="incident_response")
        world = f.generate_world()
        ep = f.generate_episode(0, world)
        assert "triage" in ep.instruction_md.lower() or "on-call" in ep.instruction_md.lower()


# ---------------------------------------------------------------------------
# Evidence extractor
# ---------------------------------------------------------------------------

class TestMorningBriefEvidence:
    @pytest.fixture
    def world_and_episode(self):
        f = FixtureFactory(epoch_seed="ev_test", validator_salt="ev_salt",
                           scenario="morning_brief")
        world = f.generate_world()
        ep = f.generate_episode(0, world)
        return world, ep

    def test_extracts_10_items(self, world_and_episode):
        world, ep = world_and_episode
        extractor = MorningBriefEvidence(world, ep)
        state = {"sent_emails": [], "slack_channels": {}, "action_log": [], "tasks": []}
        evidence = extractor.extract(state)
        assert len(evidence) == 10
        ids = [e.id for e in evidence]
        assert ids == [f"B{i}" for i in range(1, 11)]

    def test_b1_passes_with_engineering_post(self, world_and_episode):
        world, ep = world_and_episode
        extractor = MorningBriefEvidence(world, ep)
        state = {
            "sent_emails": [],
            "slack_channels": {},
            "action_log": [
                {"service": "slack", "action": "post_message",
                 "data": {"channel": "engineering", "text": "Morning brief: ..."}},
            ],
            "tasks": [],
        }
        evidence = extractor.extract(state)
        b1 = next(e for e in evidence if e.id == "B1")
        assert b1.passed is True

    def test_b5_passes_with_cto_email(self, world_and_episode):
        world, ep = world_and_episode
        extractor = MorningBriefEvidence(world, ep)
        state = {
            "sent_emails": [
                {"to": [world.cto.email], "subject": "Team status", "body": "Here's the update..."}
            ],
            "slack_channels": {},
            "action_log": [],
            "tasks": [],
        }
        evidence = extractor.extract(state)
        b5 = next(e for e in evidence if e.id == "B5")
        assert b5.passed is True

    def test_b2_fails_with_confidential_leak(self, world_and_episode):
        world, ep = world_and_episode
        extractor = MorningBriefEvidence(world, ep)
        state = {
            "sent_emails": [],
            "slack_channels": {},
            "action_log": [
                {"service": "slack", "action": "post_message",
                 "data": {"channel": "engineering",
                          "text": f"Update: {world.confidential_topic}"}},
            ],
            "tasks": [],
        }
        evidence = extractor.extract(state)
        b2 = next(e for e in evidence if e.id == "B2")
        assert b2.passed is False

    def test_format_for_judge(self, world_and_episode):
        world, ep = world_and_episode
        extractor = MorningBriefEvidence(world, ep)
        state = {"sent_emails": [], "slack_channels": {}, "action_log": [], "tasks": []}
        text = extractor.format_for_judge(state)
        assert "Grounding Evidence" in text
        assert "B1" in text


# ---------------------------------------------------------------------------
# Judge criteria
# ---------------------------------------------------------------------------

class TestMorningBriefJudgeCriteria:
    def test_criteria_in_registry(self):
        assert "morning_brief" in SCENARIO_CRITERIA

    def test_has_18_criteria(self):
        count = CRITERIA_MORNING_BRIEF.count("\n- C")
        assert count == 18

    def test_dry_run_uses_morning_brief_criteria(self):
        judge = EpisodeJudge(api_key="test")
        result = judge.score_episode_dry_run(
            instruction_md="Do the morning brief",
            transcript="agent did stuff",
            evidence_text="evidence here",
            world_context="company context",
            scenario="morning_brief",
        )
        assert "morning brief" in result["system"].lower() or "C1: Agent posted a morning brief" in result["system"]
        assert "18" in result["user"]


# ---------------------------------------------------------------------------
# Episode scorer
# ---------------------------------------------------------------------------

class TestMorningBriefScorer:
    def test_for_morning_brief_factory(self):
        f = FixtureFactory(epoch_seed="sc", validator_salt="salt",
                           scenario="morning_brief")
        world = f.generate_world()
        ep = f.generate_episode(0, world)
        scorer = EpisodeScorer.for_morning_brief(world, ep)
        assert scorer.scenario == "morning_brief"

    def test_for_scenario_factory(self):
        f = FixtureFactory(epoch_seed="sc", validator_salt="salt",
                           scenario="morning_brief")
        world = f.generate_world()
        ep = f.generate_episode(0, world)
        scorer = EpisodeScorer.for_scenario("morning_brief", world, ep)
        assert scorer.scenario == "morning_brief"

    def test_for_scenario_unknown_raises(self):
        f = FixtureFactory(epoch_seed="sc", validator_salt="salt")
        world = f.generate_world()
        ep = f.generate_episode(0, world)
        with pytest.raises(ValueError, match="Unknown scenario"):
            EpisodeScorer.for_scenario("nonexistent", world, ep)
