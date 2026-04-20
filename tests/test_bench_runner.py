"""Unit tests for trajrl_bench.bench — config loading, skill resolution,
cell id shaping. Docker-driven integration is covered by a live smoke."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from trajrl_bench.bench import (
    BenchConfig,
    HarnessConfig,
    ModelConfig,
    SkillConfig,
    _cell_id,
    _slug,
)


# ---------------------------------------------------------------------------
# SkillConfig.resolve
# ---------------------------------------------------------------------------

class TestSkillResolve:
    def test_inline_content(self):
        s = SkillConfig(name="vanilla", content="do your best\n")
        assert s.resolve() == "do your best\n"

    def test_flat_md_path(self, tmp_path: Path):
        md = tmp_path / "skill.md"
        body = "# Skill\nfollow rules\n"
        md.write_text(body)
        s = SkillConfig(name="x", flat_md_path=str(md))
        assert s.resolve() == body

    def test_flat_md_path_with_valid_pin(self, tmp_path: Path):
        md = tmp_path / "pinned.md"
        body = "# Pinned skill body\n"
        md.write_text(body)
        digest = hashlib.sha256(body.encode()).hexdigest()
        s = SkillConfig(name="p", flat_md_path=str(md), pin_sha256=digest)
        assert s.resolve() == body

    def test_pin_mismatch_raises(self, tmp_path: Path):
        md = tmp_path / "drift.md"
        md.write_text("original body\n")
        bad_pin = "0" * 64
        s = SkillConfig(name="d", flat_md_path=str(md), pin_sha256=bad_pin)
        with pytest.raises(ValueError, match="pin mismatch"):
            s.resolve()

    def test_missing_file_raises(self, tmp_path: Path):
        s = SkillConfig(name="m", flat_md_path=str(tmp_path / "nope.md"))
        with pytest.raises(FileNotFoundError):
            s.resolve()

    def test_no_source_raises(self):
        s = SkillConfig(name="empty")
        with pytest.raises(ValueError, match="need either content or flat_md_path"):
            s.resolve()

    def test_expands_user_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        md = tmp_path / "home.md"
        md.write_text("x")
        monkeypatch.setenv("HOME", str(tmp_path))
        s = SkillConfig(name="h", flat_md_path="~/home.md")
        assert s.resolve() == "x"


# ---------------------------------------------------------------------------
# BenchConfig.load
# ---------------------------------------------------------------------------

class TestBenchConfigLoad:
    def _yaml(self, tmp_path: Path, body: str) -> Path:
        p = tmp_path / "bench.yaml"
        p.write_text(body)
        return p

    def test_minimal(self, tmp_path: Path):
        p = self._yaml(tmp_path, """
run_name: test-run
model:
  name: claude-sonnet-4-6
  base_url: https://api.anthropic.com
  api_key_env: ANTHROPIC_API_KEY
scenarios: [incident_response]
skills:
  - name: vanilla
    content: "one line\\n"
harnesses:
  - name: hermes
    image: ghcr.io/trajectoryrl/hermes-agent:latest
""")
        cfg = BenchConfig.load(p)
        assert cfg.run_name == "test-run"
        assert cfg.model.name == "claude-sonnet-4-6"
        assert cfg.scenarios == ["incident_response"]
        assert len(cfg.skills) == 1 and cfg.skills[0].content == "one line\n"
        assert len(cfg.harnesses) == 1 and cfg.harnesses[0].name == "hermes"
        assert cfg.episodes_per_cell == 4
        assert cfg.run_dir == "results"

    def test_full(self, tmp_path: Path):
        p = self._yaml(tmp_path, """
run_name: full
model:
  name: claude-sonnet-4-6
  base_url: https://api.anthropic.com
  api_key_env: K
scenarios: [a, b]
skills:
  - name: inline
    content: "x"
  - name: org/pack
    flat_md_path: /tmp/flat.md
    pin_sha256: abc
harnesses:
  - {name: h1, image: img1}
  - {name: h2, image: img2}
episodes_per_cell: 2
run_dir: /tmp/out
sandbox_image: ghcr.io/custom:tag
testee_timeout_s: 120
judge_timeout_s: 60
""")
        cfg = BenchConfig.load(p)
        assert cfg.scenarios == ["a", "b"]
        assert len(cfg.skills) == 2
        assert cfg.skills[1].pin_sha256 == "abc"
        assert len(cfg.harnesses) == 2
        assert cfg.episodes_per_cell == 2
        assert cfg.run_dir == "/tmp/out"
        assert cfg.sandbox_image == "ghcr.io/custom:tag"
        assert cfg.testee_timeout_s == 120
        assert cfg.judge_timeout_s == 60


# ---------------------------------------------------------------------------
# cell id / slug
# ---------------------------------------------------------------------------

class TestCellId:
    def test_simple(self):
        assert _cell_id("hermes", "vanilla", "incident_response") == \
            "hermes__vanilla__incident_response"

    def test_slug_replaces_slashes(self):
        assert _slug("pskoett/self-improving-agent") == "pskoett_self-improving-agent"

    def test_slug_replaces_spaces(self):
        assert _slug("my skill") == "my_skill"

    def test_slug_replaces_colons(self):
        assert _slug("ghcr.io/org/img:tag") == "ghcr.io_org_img_tag"

    def test_cell_id_with_complex_names(self):
        cid = _cell_id("hermes", "pskoett/self-improving-agent", "incident_response")
        assert "/" not in cid
        assert cid.count("__") == 2
