# large-scale-text-editing

The agent writes a single Vim script `/app/apply_macros.vim` that
transforms a baked 1-million-row `/app/input.csv` (messy, space-padded,
comma-delimited triples) into `/app/expected.csv` (fields reversed,
uppercased, `;`-delimited, `;OK`-suffixed) using exactly three macros in
registers a/b/c under a < 200 total-keystroke budget. It must run
headlessly (`vim -Nu NONE -n -Es`) and contain only a whitelisted set of
commands — `call setreg('[abc]', ...)`, `:%normal! @[abc]`, and `:wq`/`:x`
— with no Vimscript functions, shell escapes, file-reading Ex commands, or
scripting.

## Why this scenario discriminates

5 pytest cells grade separable properties:

- `test_apply_macros_exists` — the deliverable is present.
- `test_apply_macros_well_formed` — every line passes the allowed-command
  whitelist (`_is_valid_keystroke_sequence` blocks `:read`/`:source`/`:e`,
  `system(`, `:!`, `:py`/`:lua`, `let`, etc.), all three registers are
  defined and executed, and an exit command is present. This is the
  anti-cheat that stops the agent from having a macro *read* the answer.
- `test_apply_macros_runs` — vim exits 0 on the fresh 1M-row input, then
  `expected.csv` is generated (from the `/tests` generator) **only after**
  vim has finished, so the script can never open the target.
- `test_input_equiv_expected` — sha256 byte-for-byte equality of the
  transformed input against the freshly generated expected over 1M rows.
  This is the discriminator; it cannot be gamed.
- `test_macros_nonempty_and_efficient` — a/b/c are non-empty, pairwise
  distinct, and total keystrokes (via `keytrans`) < 200.

Null floor is 0/5 (verified): with no `/app/apply_macros.vim` every cell
fails. A planted, already-transformed `input.csv` plus a no-op macro
reaches at most 4/5 (verified — only `test_input_equiv_expected` fails),
because `test.sh` discards the planted CSVs and regenerates a sanitary
`input.csv` from the `/tests`-held generator before grading, and
`expected.csv` is generated only after the agent's vim run.

## Provenance

- **Upstream task:** `original-tasks/large-scale-text-editing` in
  `harbor-framework/terminal-bench`
  (https://github.com/harbor-framework/terminal-bench/tree/1a6ffa9674b571da0ed040c470cb40c4d85f9b9b/original-tasks/large-scale-text-editing)
- **Upstream commit pin:** `1a6ffa9674b571da0ed040c470cb40c4d85f9b9b`
  (mirrored under `THIRD_PARTY_LICENSES/terminal-bench/`)
- **Original author:** Robert Zhang <robertz@cs.utexas.edu>
- **Upstream license:** Apache-2.0

### Modifications during adaptation

- **`environment/Dockerfile`** `FROM ghcr.io/trajectoryrl/sandbox-agent:latest`
  (vs. the upstream `ghcr.io/laude-institute/t-bench/ubuntu-24-04` base),
  so the agent runs in this image directly. `apt-get install -y vim`
  matches upstream's only extra package. `gen_large_csv.py` is COPY'd from
  `environment/` (the scenario image's build context) and run with
  `both` to bake `/app/input.csv` + `/app/expected.csv` (~74 MB layer),
  then removed from `/app` so the agent cannot read the generator; `/app`
  is chowned to `hermes:hermes`.
- **Generator placement.** The build context restriction means the COPY
  source must live under `environment/`, so `gen_large_csv.py` is
  duplicated there. A byte-identical copy also lives under `tests/`,
  mounted at `/tests` at grade time: `tests/test.sh` calls it to
  regenerate a fresh sanitary `input.csv`, and the unmodified
  `test_outputs.py` calls `/tests/gen_large_csv.py expected` after the
  agent's vim run. The generator carries no upstream canary.
- **Deliverable is a single file** `/app/apply_macros.vim`;
  `agent_output_path` names it directly (no tarball, no directory — a
  directory-shaped `agent_output_path` never crosses the validator's
  `_extract_file` boundary).
- **`tests/test.sh`** is the audio-synth-stft-peaks uvx `test.sh` shape
  (`uvx -p 3.13 -w pytest==8.4.1 -w pytest-json-ctrf==0.3.5 pytest --ctrf`),
  preceded by the upstream `run-tests.sh` anti-cheat block:
  `rm -f /app/*.csv` then `python3 /tests/gen_large_csv.py input` — INPUT
  ONLY; `expected.csv` is generated during the pytest run, after vim.
- **`tests/test_outputs.py`** reused verbatim except the terminal-bench
  canary comment was removed; the allowed-command whitelist and the
  post-vim `expected.csv` generation are unchanged. The `total < 200`
  keystroke bound was NOT relaxed: the reference macros total well under
  200 and the measured 1M-row vim run is ~122 s under the 2-CPU / 4-GB
  eval sandbox, comfortably inside the `[verifier].timeout_sec = 600`.
- **`solution/solve.sh`** writes `/app/apply_macros.vim` (upstream
  `solution.sh` with the canary removed and `cd /app` added). The three
  reference macros are upstream verbatim.
- **`instruction.md`** is upstream `task.yaml`'s `instruction:` block
  verbatim, plus one appended paragraph naming the single-file deliverable
  and the verifier's fresh-`input.csv` regen sequence.
- **`task.toml`** keeps upstream metadata (author, difficulty medium,
  category file-operations, tags, 40/90 estimates). `[agent].timeout_sec`
  = 1200 mirrors upstream `max_agent_timeout_sec`; `[verifier].timeout_sec`
  = 600 covers uv setup + the 1M-row vim run + regen + sha256 diff.
- No copyleft is bundled: vim is an apt system package; the baked CSVs are
  deterministically generated text.

## Deliverable

`agent_output_path = /app/apply_macros.vim` (a single Vim script). The
validator extracts it from the agent container and injects it into a fresh
verifier container of the same image; `tests/test.sh` regenerates a fresh
`input.csv`, then runs the 5-cell pytest suite (which runs vim headlessly
and generates `expected.csv` only after vim finishes).

## Resource envelope

~74 MB baked image layer (the two 1M-row CSVs generated at build, ~37 MB
each); ~110 MB one-shot sequential I/O per eval (test-time `input.csv`
regen + vim's in-place rewrite + `expected.csv` regen + sha256 read of
both). vim holds ~55 MB resident in RAM — well inside the sandbox's 4 GB /
2 CPU quota. Measured vim wall-clock on the 1M-row input: ~122 s. No
disk-rate limiting is applied by the harness; the figures are modest,
deterministic, and inside the storage quota.
