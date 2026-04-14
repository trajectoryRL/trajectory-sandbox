#!/usr/bin/env python3
"""Live LLM judge test that saves full results to results/ folder.

Generates a 4-episode evaluation with fixture factory, scores each episode
via LLM judge, computes split-half delta, and writes everything to disk.

Usage:
    source /data2/trajectory_rl/trajectoryRL/.env.validator
    export LLM_MODEL=z-ai/glm-5.1
    python tests/test_judge_save.py

Output:
    results/{timestamp}/
    ├── world.json           # generated world context
    ├── episode_0/
    │   ├── instruction.md   # task prompt
    │   ├── fixtures.json    # episode fixtures
    │   ├── state.json       # simulated mock state after agent
    │   ├── evidence.txt     # grounding evidence for judge
    │   ├── prompts.json     # system + user prompts sent to LLM
    │   ├── judge_result.json# full judge response
    │   └── summary.txt      # human-readable summary
    ├── episode_1/ ...
    ├── episode_2/ ...
    ├── episode_3/ ...
    └── final_result.json    # split-half delta + final_score
"""

import json
import os
import sys
import time
from datetime import datetime


def main():
    print("=== Live 4-Episode Judge Test (with save) ===\n")

    # Load env
    try:
        from dotenv import load_dotenv
        for env_path in [".env", "../.env", "../../trajectoryRL/.env.validator"]:
            if os.path.exists(env_path):
                load_dotenv(env_path)
                break
    except ImportError:
        pass

    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("CLAWBENCH_LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL") or os.environ.get("CLAWBENCH_DEFAULT_MODEL", "")
    if not api_key:
        print("SKIP: No LLM_API_KEY set")
        sys.exit(0)

    print(f"  Model: {model}")
    print(f"  Key:   {api_key[:12]}...{api_key[-4:]}\n")

    from trajrl_bench.fixture_factory import FixtureFactory
    from trajrl_bench.episode_scorer import EpisodeScorer
    from trajrl_bench.judge import EpisodeJudge
    from trajrl_bench.types import EvalSessionResult, EpisodeResult

    # Create output dir
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(os.path.dirname(__file__), "..", "results", ts)
    os.makedirs(out_dir, exist_ok=True)

    # Generate world + 4 episodes
    factory = FixtureFactory(epoch_seed="save_test_001", validator_salt="save_salt")
    world = factory.generate_world()
    episodes = factory.generate_all_episodes(world)

    # Save world
    world_data = {
        "company": world.company, "domain": world.domain, "product": world.product,
        "user": {"name": world.user.full_name, "email": world.user.email, "role": world.user.role},
        "client": {"name": world.client.full_name, "email": world.client.email, "company": world.client_company},
        "cto": {"name": world.cto.full_name, "email": world.cto.email},
        "confidential_topic": world.confidential_topic,
        "team": [{"name": p.full_name, "email": p.email, "role": p.role} for p in world.team],
        "standup_time": world.standup_time,
    }
    _write_json(os.path.join(out_dir, "world.json"), world_data)

    print(f"  World: {world.company}, product={world.product}")
    print(f"  Client: {world.client.full_name} ({world.client.email})")
    print(f"  Confidential: {world.confidential_topic}")
    print(f"  Output: {out_dir}\n")

    # Score each episode
    judge = EpisodeJudge()
    result = EvalSessionResult()
    total_t0 = time.time()

    for i, ep in enumerate(episodes):
        ep_dir = os.path.join(out_dir, f"episode_{i}")
        os.makedirs(ep_dir, exist_ok=True)

        # Save fixtures + instruction
        _write_json(os.path.join(ep_dir, "fixtures.json"), ep.to_dict())
        _write(os.path.join(ep_dir, "instruction.md"), ep.instruction_md)
        _write_json(os.path.join(ep_dir, "metadata.json"), ep.metadata)

        # Simulate agent state (progressively better across episodes)
        state = _simulate_agent_state(world, ep, episode_index=i)
        transcript = _simulate_transcript(world, ep, episode_index=i)
        _write_json(os.path.join(ep_dir, "state.json"), state)
        _write(os.path.join(ep_dir, "transcript.txt"), transcript)

        # Score
        scorer = EpisodeScorer.for_incident_response(world, ep, judge=judge)

        # Save evidence
        evidence_text = scorer.evidence_extractor.format_for_judge(state)
        _write(os.path.join(ep_dir, "evidence.txt"), evidence_text)

        # Save prompts (dry run)
        prompts = scorer.score_dry_run(transcript, state)
        _write_json(os.path.join(ep_dir, "prompts.json"), prompts)

        # Call LLM judge
        print(f"  Episode {i} (recurring={ep.metadata['is_recurring']}, "
              f"evolving={ep.metadata['is_evolving']})...")
        t0 = time.time()
        scored = scorer.score_detailed(transcript, state)
        elapsed = time.time() - t0

        # Save judge result
        judge_data = {
            "quality": scored.quality,
            "summary": scored.judge_result.summary,
            "error": scored.judge_result.error,
            "criteria": [
                {"id": c.id, "score": c.score, "reason": c.reason}
                for c in scored.judge_result.criteria
            ],
            "elapsed_s": elapsed,
        }
        _write_json(os.path.join(ep_dir, "judge_result.json"), judge_data)

        # Human-readable summary
        summary_lines = [
            f"Episode {i} — quality: {scored.quality:.3f} ({elapsed:.1f}s)",
            f"Recurring: {ep.metadata['is_recurring']}, Evolving: {ep.metadata['is_evolving']}",
            f"Bug type: {ep.metadata['bug_type']}",
            f"PR author: {ep.metadata['pr_author']}",
            "",
            f"Summary: {scored.judge_result.summary}",
            "",
            "Criteria:",
        ]
        for c in scored.judge_result.criteria:
            icon = "PASS" if c.score == 1 else "FAIL"
            summary_lines.append(f"  [{icon}] {c.id}: {c.reason}")

        passed = sum(c.score for c in scored.judge_result.criteria)
        total = len(scored.judge_result.criteria)
        summary_lines.append(f"\nScore: {passed}/{total} criteria, quality={scored.quality:.3f}")
        _write(os.path.join(ep_dir, "summary.txt"), "\n".join(summary_lines))

        # Print
        print(f"    quality={scored.quality:.3f} ({passed}/{total} criteria) [{elapsed:.1f}s]")
        if scored.judge_result.error:
            print(f"    ERROR: {scored.judge_result.error}")

        result.episodes.append(EpisodeResult(episode_index=i, quality=scored.quality))

    # Compute final scores
    result.compute_scores()
    total_elapsed = time.time() - total_t0

    # Save final result
    final = {
        "episodes": [
            {"rep": ep.episode_index + 1, "quality": ep.quality}
            for ep in result.episodes
        ],
        "early_mean": result.early_mean,
        "late_mean": result.late_mean,
        "delta": result.delta,
        "mean_quality": result.mean_quality,
        "learning_bonus": result.learning_bonus,
        "final_score": result.final_score,
        "total_elapsed_s": total_elapsed,
        "model": model,
    }
    _write_json(os.path.join(out_dir, "final_result.json"), final)

    print(f"\n  --- Final Result ---")
    print(f"  early_mean:     {result.early_mean:.3f}")
    print(f"  late_mean:      {result.late_mean:.3f}")
    print(f"  delta:          {result.delta:.3f}")
    print(f"  mean_quality:   {result.mean_quality:.3f}")
    print(f"  learning_bonus: {result.learning_bonus:.3f}")
    print(f"  final_score:    {result.final_score:.3f}")
    print(f"  total_time:     {total_elapsed:.1f}s")
    print(f"\n  Results saved to: {out_dir}")
    print(f"\n=== DONE ===")


def _simulate_agent_state(world, episode, episode_index):
    """Simulate progressively better agent state across 4 episodes."""
    pr_author = episode.metadata["pr_author"]
    pr_email = None
    for p in world.team:
        if p.full_name == pr_author:
            pr_email = p.email
            break
    pr_email = pr_email or f"unknown@{world.domain}"

    base_state = {
        "emails": episode.to_dict()["inbox"],
        "sent_emails": [],
        "slack_channels": {
            ch: {"name": ch, "messages": []}
            for ch in world.slack_channels
        },
        "tasks": episode.to_dict().get("tasks", []),
        "calendar_events": episode.to_dict().get("calendar", []),
        "action_log": [],
        "gitea_issues": episode.to_dict().get("gitea_issues", []),
        "gitea_prs": episode.to_dict().get("gitea_prs", []),
        "gitea_comments": [], "gitea_refs": [], "gitea_files": [], "gitea_commits": [],
    }

    # Episode 0: mediocre — misses some things
    if episode_index == 0:
        base_state["slack_channels"]["incidents"]["messages"].append(
            {"user": "agent", "text": f"There's an issue with {world.product}. Looking into it."}
        )
        base_state["sent_emails"].append({
            "to": [world.client.email], "subject": "Issue update",
            "body": f"Hi, we're looking into the {world.product} issue. Will update soon.",
        })
        base_state["action_log"] = [
            {"service": "slack", "action": "post_message",
             "data": {"channel": "incidents", "text": "There's an issue"}},
            {"service": "email", "action": "send",
             "data": {"to": [world.client.email], "subject": "Issue update"}},
            {"service": "notion", "action": "create_page", "data": {"title": "Look into issue"}},
            {"service": "notion", "action": "create_page", "data": {"title": "Update client"}},
        ]

    # Episode 1: better — more structured but still misses calendar
    elif episode_index == 1:
        base_state["slack_channels"]["incidents"]["messages"].append(
            {"user": "agent", "text": (
                f"**Incident: {world.product}**\n"
                f"Impact: Service disruption\n"
                f"Status: Investigating\n"
                f"Root cause: Likely related to recent deploy"
            )}
        )
        base_state["sent_emails"].append({
            "to": [world.client.email], "subject": "RE: Service disruption — update",
            "body": (f"Hi {world.client.first_name},\n\nWe've identified an issue and are "
                     f"working on it. ETA: ~2 hours.\n\nApologies for the inconvenience.\n"
                     f"{world.user.first_name}"),
        })
        base_state["action_log"] = [
            {"service": "slack", "action": "post_message",
             "data": {"channel": "incidents", "text": "Incident update with structure"}},
            {"service": "email", "action": "send",
             "data": {"to": [world.client.email], "subject": "Service disruption update"}},
            {"service": "notion", "action": "create_page",
             "data": {"title": f"Investigate: {episode.metadata['bug_type']}"}},
            {"service": "notion", "action": "create_page",
             "data": {"title": "Send client update"}},
            {"service": "notion", "action": "create_page",
             "data": {"title": "Schedule post-incident review"}},
        ]

    # Episode 2-3: strong — full workflow
    else:
        issue_num = episode.to_dict()["gitea_issues"][0].get("number", "?")
        pr_num = episode.to_dict()["gitea_prs"][0].get("number", "?")
        base_state["slack_channels"]["incidents"]["messages"].append(
            {"user": "agent", "text": (
                f"🔴 **P0 Incident: {world.product}**\n\n"
                f"**Impact:** Service disruption affecting {world.client_company}\n"
                f"**Root cause:** {episode.metadata['bug_type']} "
                f"(introduced in PR #{pr_num}, see issue #{issue_num})\n"
                f"**Status:** Fix deployed, monitoring\n"
                f"**Next steps:**\n"
                f"1. Monitor error rates 30 min\n"
                f"2. Client update sent\n"
                f"3. PIR scheduled"
            )}
        )
        base_state["sent_emails"].append({
            "to": [world.client.email],
            "subject": f"RE: Service disruption — resolution update",
            "body": (f"Hi {world.client.first_name},\n\n"
                     f"We've identified and resolved the root cause of the service disruption. "
                     f"Our team deployed a fix and we're monitoring recovery.\n\n"
                     f"ETA for full resolution: 1 hour.\n\n"
                     f"I sincerely apologize for the inconvenience and will send a final "
                     f"confirmation once everything is stable.\n\n"
                     f"Best regards,\n{world.user.first_name} {world.user.last_name}\n"
                     f"{world.user.role}, {world.company}"),
        })
        base_state["action_log"] = [
            {"service": "slack", "action": "post_message",
             "data": {"channel": "incidents",
                      "text": f"P0 Incident: {world.product} — structured update"}},
            {"service": "email", "action": "send",
             "data": {"to": [world.client.email], "subject": "Resolution update"}},
            {"service": "notion", "action": "create_page",
             "data": {"title": f"Investigate root cause: {episode.metadata['bug_type']}"}},
            {"service": "notion", "action": "create_page",
             "data": {"title": f"Client communication: {world.client_company}"}},
            {"service": "notion", "action": "create_page",
             "data": {"title": "Post-incident review meeting"}},
            {"service": "calendar", "action": "create_event",
             "data": {"summary": f"PIR: {world.product} incident",
                      "attendees": [world.user.email, pr_email]}},
        ]

    return base_state


def _simulate_transcript(world, episode, episode_index):
    """Simulate progressively better agent transcripts."""
    issue = episode.to_dict()["gitea_issues"][0] if episode.to_dict()["gitea_issues"] else {}
    pr = episode.to_dict()["gitea_prs"][0] if episode.to_dict()["gitea_prs"] else {}

    if episode_index == 0:
        return (
            f"$ curl -s http://localhost:8090/api/v2/messages | jq '.total'\n12\n\n"
            f"Reading emails... found alert about {world.product}.\n"
            f"Posting to Slack #incidents.\n"
            f"Sending email to client.\n"
            f"Creating tasks.\n"
            f"Done."
        )
    elif episode_index == 1:
        return (
            f"$ curl -s http://localhost:8090/api/v2/messages | jq '.items[].subject'\n"
            f"Identified P0 items: monitoring alert, client complaint, CTO escalation.\n"
            f"Flagged confidential email about {world.confidential_topic} — will NOT share.\n\n"
            f"$ curl -s http://localhost:8090/api/v1/repos/org/{world.repo_name}/issues\n"
            f"Issue #{issue.get('number', '?')}: {episode.metadata['bug_type']}\n\n"
            f"Posting structured update to #incidents.\n"
            f"Sending professional email to {world.client.first_name}.\n"
            f"Creating 3 follow-up tasks.\n"
        )
    else:
        learned = ""
        if episode_index >= 2:
            learned = (
                f"\n$ cat /workspace/learned/patterns.md\n"
                f"- Always check Gitea issues before posting Slack status\n"
                f"- {world.product} outages often related to recent deploys\n"
                f"- Include specific ETA in client emails\n\n"
            )
        return (
            f"$ cat /workspace/learned/patterns.md\n{learned}"
            f"$ curl -s http://localhost:8090/api/v2/messages | jq '.items[].subject'\n"
            f"Triaging inbox: 3 P0 items identified.\n"
            f"Confidential email flagged — NOT sharing publicly.\n\n"
            f"$ curl -s http://localhost:8090/api/v1/repos/org/{world.repo_name}/issues\n"
            f"Issue #{issue.get('number', '?')}: {episode.metadata['bug_type']}\n\n"
            f"$ curl -s http://localhost:8090/api/v1/repos/org/{world.repo_name}/pulls\n"
            f"PR #{pr.get('number', '?')}: {pr.get('title', '?')} — merged recently\n\n"
            f"Correlating: alert + issue + client complaint + PR → same incident.\n\n"
            f"Posting structured incident update to #incidents.\n"
            f"Sending professional client email with ETA.\n"
            f"Creating 3 actionable tasks.\n"
            f"Scheduling PIR with {episode.metadata['pr_author']} invited.\n"
            f"\n$ echo 'Pattern: {episode.metadata['bug_type']} linked to recent deploy' "
            f">> /workspace/learned/patterns.md\n"
        )


def _write(path, content):
    with open(path, "w") as f:
        f.write(content)


def _write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


if __name__ == "__main__":
    main()
