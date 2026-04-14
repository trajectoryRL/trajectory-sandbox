"""Episode scorer: connects evidence extraction + LLM judge into a single call.

Decoupled from EvalSession — can score episodes without re-running them.
Different scenarios can plug in different scorers.

Usage:
    scorer = EpisodeScorer.for_incident_response(world, episode)
    quality = scorer.score(transcript, mock_state)
    # quality = 0.0–1.0

    # Or get the full judge result:
    result = scorer.score_detailed(transcript, mock_state)
    # result.quality, result.judge_result.criteria, result.judge_result.summary
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from trajrl_bench.evidence import IncidentResponseEvidence, MorningBriefEvidence, EvidenceItem
from trajrl_bench.judge import EpisodeJudge, JudgeResult
from trajrl_bench.fixture_factory import World, EpisodeFixtures

logger = logging.getLogger(__name__)


@dataclass
class ScoredEpisode:
    """Full scoring output for one episode."""
    quality: float
    judge_result: JudgeResult
    evidence: list[EvidenceItem]
    evidence_text: str


class EpisodeScorer:
    """Scores an episode: transcript + mock state → quality 0.0–1.0.

    Connects evidence extraction (grounding from service state) with the
    LLM judge (criteria → quality score). The evidence extractor is
    scenario-specific; the judge is generic.
    """

    def __init__(
        self,
        judge: EpisodeJudge,
        evidence_extractor: IncidentResponseEvidence | MorningBriefEvidence,
        world: World,
        episode: EpisodeFixtures,
        scenario: str = "incident_response",
    ):
        self.judge = judge
        self.evidence_extractor = evidence_extractor
        self.world = world
        self.episode = episode
        self.scenario = scenario

    @classmethod
    def for_incident_response(
        cls,
        world: World,
        episode: EpisodeFixtures,
        judge: EpisodeJudge | None = None,
    ) -> EpisodeScorer:
        """Create a scorer for the incident_response scenario."""
        if judge is None:
            judge = EpisodeJudge()
        evidence_extractor = IncidentResponseEvidence(world, episode)
        return cls(judge=judge, evidence_extractor=evidence_extractor,
                   world=world, episode=episode, scenario="incident_response")

    @classmethod
    def for_morning_brief(
        cls,
        world: World,
        episode: EpisodeFixtures,
        judge: EpisodeJudge | None = None,
    ) -> EpisodeScorer:
        """Create a scorer for the morning_brief scenario."""
        if judge is None:
            judge = EpisodeJudge()
        evidence_extractor = MorningBriefEvidence(world, episode)
        return cls(judge=judge, evidence_extractor=evidence_extractor,
                   world=world, episode=episode, scenario="morning_brief")

    @classmethod
    def for_scenario(
        cls,
        scenario: str,
        world: World,
        episode: EpisodeFixtures,
        judge: EpisodeJudge | None = None,
    ) -> EpisodeScorer:
        """Create a scorer by scenario name."""
        factories = {
            "incident_response": cls.for_incident_response,
            "morning_brief": cls.for_morning_brief,
        }
        factory = factories.get(scenario)
        if factory is None:
            raise ValueError(f"Unknown scenario: {scenario}. Available: {list(factories)}")
        return factory(world, episode, judge)

    def score(self, transcript: str, mock_state: dict[str, Any]) -> float:
        """Score an episode. Returns quality 0.0–1.0."""
        result = self.score_detailed(transcript, mock_state)
        return result.quality

    def score_detailed(self, transcript: str, mock_state: dict[str, Any]) -> ScoredEpisode:
        """Score an episode with full details."""
        # Extract evidence from mock service state
        evidence = self.evidence_extractor.extract(mock_state)
        evidence_text = self.evidence_extractor.format_for_judge(mock_state)
        world_context = EpisodeJudge.format_world(self.world)

        # Call LLM judge
        judge_result = self.judge.score_episode(
            instruction_md=self.episode.instruction_md,
            transcript=transcript,
            evidence_text=evidence_text,
            world_context=world_context,
            scenario=self.scenario,
        )

        if judge_result.error:
            logger.error("Judge error for episode: %s", judge_result.error)

        return ScoredEpisode(
            quality=judge_result.quality,
            judge_result=judge_result,
            evidence=evidence,
            evidence_text=evidence_text,
        )

    def score_dry_run(self, transcript: str, mock_state: dict[str, Any]) -> dict[str, str]:
        """Return the prompts that would be sent to the LLM (no API call)."""
        evidence_text = self.evidence_extractor.format_for_judge(mock_state)
        world_context = EpisodeJudge.format_world(self.world)
        return self.judge.score_episode_dry_run(
            instruction_md=self.episode.instruction_md,
            transcript=transcript,
            evidence_text=evidence_text,
            world_context=world_context,
            scenario=self.scenario,
        )
