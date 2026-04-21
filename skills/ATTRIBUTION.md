# Attribution — committed skill packs

Flattened SKILL.md files in this directory are produced by
`python -m trajrl_bench.cli fetch-skill --zip <pack>.zip` from upstream skill
packs. They are committed so that bench runs are reproducible by anyone who
clones the repo, without external fetches or user-local caches.

Each row records: the pack, the version flattened, the sha256 of the flat
SKILL.md body (matches the `pin_sha256` in any `configs/bench_*.yaml` that
references it), the upstream source, and the license under which it is
redistributable.

| Pack | Version | sha256 (first 16) | Source | License |
|---|---|---|---|---|
| trajectoryrl/s1-assumptions-worth-challenging | 1.0 | `23c7d9b01d4a5f0a` | TrajectoryRL SN11 Season 1 winner, polished for publication (frontmatter + opening frame + closing checklist); 8 core principles verbatim from the winning submission | MIT-0 |
| pskoett/self-improving-agent | 3.0.16 | `2f0950338c556ea1` | clawhub: `pskoett/self-improving-agent@3.0.16` | MIT-0 |
| pskoett/self-improving-agent *(trajrl-adapted)* | 3.0.16 | `3ebede64c33bcc6c` | derivative of the row above — bench preamble prepended redirecting `.learnings/` → `/workspace/learned/` for this eval environment | MIT-0 |

## License notes

- **MIT-0** (MIT No Attribution) — permits unrestricted reuse including
  redistribution without attribution. We still attribute as a courtesy and
  for audit clarity.
- **Adapted variants** (e.g. the `-trajrl` suffix above) are derivative
  works permitted by MIT-0. Each adapted variant keeps the upstream
  license; the adaptation diff is visible in this repo's git history.
- **Subnet-mined packs** (`trajectoryrl/` prefix) originate as winning
  submissions on TrajectoryRL SN11's on-chain evaluation cycle. Per the
  2026-04-17 licensing decision, copyright for winning packs transfers
  to trajrl.com at the point of reward; we republish under MIT-0 so the
  bench stays fully open.

## Adding a new pack

1. `python -m trajrl_bench.cli fetch-skill --zip <path>/foo.zip --cache-dir skills/`
2. Verify the pack's LICENSE file inside the zip — confirm it permits
   redistribution under terms compatible with this repo.
3. Add a row above: name, version, first 16 chars of sha256, source, license.
4. Reference the new `skills/<flat>.md` from the relevant bench config with
   matching `pin_sha256`.
5. Open a PR so the contents are reviewable in the diff.

If a pack's license is ambiguous or non-redistributable, **do not commit the
flattened MD.** Either contact the author for permission, or keep the pack
out of the committed bench grid and reference it only from a developer's
local cache.
