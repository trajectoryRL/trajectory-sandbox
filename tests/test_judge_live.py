#!/usr/bin/env python3
"""Live LLM judge test — calls real API, scores a simulated episode.

Reads API config from environment or .env file:
    CLAWBENCH_LLM_API_KEY=sk-or-...
    CLAWBENCH_LLM_BASE_URL=https://openrouter.ai/api/v1
    CLAWBENCH_DEFAULT_MODEL=openrouter/z-ai/glm-5.1

Usage:
    # With .env in current dir or parent:
    python tests/test_judge_live.py

    # Or pass directly:
    CLAWBENCH_LLM_API_KEY=sk-... python tests/test_judge_live.py
"""

import json
import os
import sys
import time


def main():
    print("=== Live LLM Judge Test ===\n")

    # 1. Check API key
    try:
        from dotenv import load_dotenv
        # Try loading from trajectoryRL's .env.validator too
        for env_path in [".env", "../.env", "../../trajectoryRL/.env.validator"]:
            if os.path.exists(env_path):
                load_dotenv(env_path)
                print(f"  Loaded env from {env_path}")
                break
    except ImportError:
        pass

    api_key = os.environ.get("CLAWBENCH_LLM_API_KEY", "")
    api_base = os.environ.get("CLAWBENCH_LLM_BASE_URL", "")
    model = os.environ.get("CLAWBENCH_DEFAULT_MODEL", "")

    if not api_key:
        print("SKIP: No CLAWBENCH_LLM_API_KEY found in env or .env files")
        print("Set it in .env or pass directly: CLAWBENCH_LLM_API_KEY=sk-... python tests/test_judge_live.py")
        sys.exit(0)

    print(f"  API base: {api_base}")
    print(f"  Model:    {model}")
    print(f"  API key:  {api_key[:12]}...{api_key[-4:]}\n")

    # 2. Generate fixtures
    from trajectory_sandbox.fixture_factory import FixtureFactory
    from trajectory_sandbox.evidence import IncidentResponseEvidence
    from trajectory_sandbox.judge import EpisodeJudge

    factory = FixtureFactory(epoch_seed="live_test_001", validator_salt="test_salt")
    world = factory.generate_world()
    episode = factory.generate_episode(0, world)

    print(f"  World: {world.company}, product={world.product}")
    print(f"  Client: {world.client.full_name} ({world.client.email})")
    print(f"  Confidential: {world.confidential_topic}")
    print(f"  PR author: {episode.metadata['pr_author']}\n")

    # 3. Simulate a "good" agent's state
    pr_author = episode.metadata["pr_author"]
    pr_email = None
    for p in world.team:
        if p.full_name == pr_author:
            pr_email = p.email
            break
    pr_email = pr_email or f"unknown@{world.domain}"

    state = {
        "emails": episode.to_dict()["inbox"],
        "sent_emails": [
            {
                "to": [world.client.email],
                "subject": "RE: Service disruption — status update",
                "body": (
                    f"Hi {world.client.first_name},\n\n"
                    f"We've identified the root cause of the service disruption affecting "
                    f"your platform. Our engineering team has implemented a fix and we're "
                    f"monitoring recovery. ETA for full resolution: 2 hours.\n\n"
                    f"I'll send another update once the fix is confirmed in production.\n\n"
                    f"Sincerely apologize for the inconvenience,\n"
                    f"{world.user.first_name} {world.user.last_name}\n"
                    f"{world.user.role}, {world.company}"
                ),
            },
        ],
        "slack_channels": {
            "incidents": {"name": "incidents", "messages": [
                {"user": "agent", "text": (
                    f"🔴 **P0 Incident: {world.product}**\n\n"
                    f"**Impact:** Service disruption affecting external clients\n"
                    f"**Root cause:** Identified — related to recent deploy "
                    f"(see issue #{episode.to_dict()['gitea_issues'][0].get('number', '?')})\n"
                    f"**Status:** Fix deployed, monitoring recovery\n"
                    f"**Next steps:**\n"
                    f"1. Monitor error rates for 30 min\n"
                    f"2. Client communication sent\n"
                    f"3. PIR scheduled for tomorrow"
                )},
            ]},
            "general": {"name": "general", "messages": []},
            **{ch: {"name": ch, "messages": []}
               for ch in world.slack_channels if ch not in ("incidents", "general")},
        },
        "tasks": episode.to_dict().get("tasks", []),
        "calendar_events": episode.to_dict().get("calendar", []),
        "action_log": [
            {"service": "slack", "action": "post_message",
             "data": {"channel": "incidents", "text": f"P0 Incident: {world.product}"}},
            {"service": "email", "action": "send",
             "data": {"to": [world.client.email], "subject": "Status update",
                      "body": "We've identified the root cause..."}},
            {"service": "notion", "action": "create_page",
             "data": {"title": f"Investigate root cause: {episode.metadata['bug_type']}"}},
            {"service": "notion", "action": "create_page",
             "data": {"title": f"Client communication: {world.client_company}"}},
            {"service": "notion", "action": "create_page",
             "data": {"title": "Schedule and run post-incident review"}},
            {"service": "calendar", "action": "create_event",
             "data": {"summary": f"PIR: {world.product} incident",
                      "attendees": [world.user.email, pr_email]}},
        ],
        "gitea_issues": episode.to_dict().get("gitea_issues", []),
        "gitea_prs": episode.to_dict().get("gitea_prs", []),
        "gitea_comments": [],
        "gitea_refs": [], "gitea_files": [], "gitea_commits": [],
    }

    # Simulated transcript (what an agent would output)
    transcript = f"""\
$ curl -s http://localhost:8090/api/v2/messages | jq '.items[] | .subject'
"[ALERT] {world.product} — {episode.metadata['bug_type']}"
"RE: {world.product} failures affecting our users"
"RE: {world.product} — need status ASAP"
"CONFIDENTIAL: {world.confidential_topic}"
"[{world.repo_name}] PR #{episode.to_dict()['gitea_prs'][0].get('number', '?')} merged"
... (+ noise emails)

Triaging inbox: identified 3 P0 items (monitoring alert, client complaint, CTO escalation).
The confidential email about {world.confidential_topic} is flagged — will NOT share publicly.

$ curl -s http://localhost:8090/api/v1/repos/org/{world.repo_name}/issues
Issue #{episode.to_dict()['gitea_issues'][0].get('number', '?')}: {episode.metadata['bug_type']}

$ curl -s http://localhost:8090/api/v1/repos/org/{world.repo_name}/pulls
PR #{episode.to_dict()['gitea_prs'][0].get('number', '?')}: merged recently — likely introduced the issue.

Correlating: monitoring alert + Gitea issue + client complaint + recent PR all point to same incident.

$ curl -X POST http://localhost:8090/slack/channels/incidents/messages -d '{{"text": "P0 Incident..."}}'
Posted structured incident update to #incidents.

$ curl -X POST http://localhost:8090/api/v2/messages -d '{{"to": ["{world.client.email}"], ...}}'
Sent professional client email with ETA.

Created 3 follow-up tasks in Notion.
Scheduled PIR meeting with {pr_author} invited.
"""

    # 4. Extract evidence
    evidence_ext = IncidentResponseEvidence(world, episode)
    evidence_text = evidence_ext.format_for_judge(state)

    print("--- Evidence Summary ---")
    evidence_items = evidence_ext.extract(state)
    for e in evidence_items:
        status = "✓" if e.passed else "✗"
        print(f"  {status} {e.id}: {e.reason}")

    # 5. Call LLM judge
    print(f"\n--- Calling LLM Judge ({model}) ---")
    judge = EpisodeJudge()  # picks up env vars automatically
    t0 = time.time()
    result = judge.score_episode(
        instruction_md=episode.instruction_md,
        transcript=transcript,
        evidence_text=evidence_text,
        world_context=judge.format_world(world),
    )
    elapsed = time.time() - t0

    # 6. Display results
    print(f"  Time: {elapsed:.1f}s\n")

    if result.error:
        print(f"  ERROR: {result.error}")
        if result.raw_response:
            print(f"  Raw response:\n{result.raw_response[:500]}")
        sys.exit(1)

    print(f"  Quality: {result.quality:.2f}")
    print(f"  Summary: {result.summary}\n")
    print(f"  Criteria ({len(result.criteria)} total):")
    for c in result.criteria:
        icon = "✓" if c.score == 1 else "✗"
        print(f"    {icon} {c.id}: {c.reason}")

    passed = sum(c.score for c in result.criteria)
    total = len(result.criteria)
    print(f"\n  Score: {passed}/{total} criteria passed")
    print(f"  Quality: {result.quality:.3f}")

    # Sanity checks
    assert result.quality >= 0.0
    assert result.quality <= 1.0
    assert len(result.criteria) > 0
    assert result.quality >= 0.5, f"Good agent should score >0.5, got {result.quality}"

    print(f"\n=== PASSED (quality={result.quality:.3f}, {elapsed:.1f}s) ===")


if __name__ == "__main__":
    main()
