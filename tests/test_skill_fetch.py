"""Unit tests for trajrl_bench.skill_fetch."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from trajrl_bench.skill_fetch import (
    SkillBundle,
    fetch_from_zip,
    load_from_zip,
    pin,
    to_flat_skill_md,
)


def _make_zip(tmp_path: Path, files: dict[str, str | bytes]) -> Path:
    z = tmp_path / "pack.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            zf.writestr(name, data)
    return z


def test_load_minimal_zip(tmp_path: Path):
    meta = {"slug": "demo-skill", "version": "1.2.3"}
    zpath = _make_zip(tmp_path, {
        "_meta.json": json.dumps(meta),
        "SKILL.md":   "# Demo\n\nDo the thing.",
    })

    bundle = load_from_zip(zpath)

    assert bundle.slug == "demo-skill"
    assert bundle.version == "1.2.3"
    assert bundle.source == f"zip:{zpath.name}"
    assert bundle.files["SKILL.md"].startswith("# Demo")


def test_load_skips_binary(tmp_path: Path):
    meta = {"slug": "bin-skill", "version": "0.1"}
    zpath = _make_zip(tmp_path, {
        "_meta.json": json.dumps(meta),
        "SKILL.md":   "# x",
        "assets/blob.bin": b"\xff\xfe\xfd\x00\x01\x02",
    })

    bundle = load_from_zip(zpath)

    assert "SKILL.md" in bundle.files
    assert "assets/blob.bin" not in bundle.files


def test_load_missing_meta_raises(tmp_path: Path):
    zpath = _make_zip(tmp_path, {"SKILL.md": "# x"})
    with pytest.raises(ValueError, match="missing _meta.json"):
        load_from_zip(zpath)


def test_flat_md_structure(tmp_path: Path):
    meta = {"slug": "my-skill", "version": "0.5"}
    zpath = _make_zip(tmp_path, {
        "_meta.json":              json.dumps(meta),
        "README.md":               "# my-skill\n\nAttribution here.",
        "SKILL.md":                "# my-skill instruction\n\nFollow the rules.",
        "references/examples.md":  "# Examples\n\n- example 1",
        "scripts/activator.sh":    "#!/bin/sh\necho hi",
        "assets/notes.txt":        "plain note",
    })

    path, digest, bundle = fetch_from_zip(zpath, cache_dir=tmp_path / "cache")

    text = path.read_text()

    # Header + source comment
    assert text.startswith("# my-skill (pack v0.5)\n")
    assert f"source: zip:{zpath.name}" in text

    # README above the main skill, main above appendix
    assert text.index("Attribution here.") < text.index("# my-skill instruction")
    assert text.index("# my-skill instruction") < text.index("Appendix")

    # Main skill body present
    assert "Follow the rules." in text

    # Appendix files included + fenced appropriately
    assert "## `references/examples.md`" in text
    assert "## `scripts/activator.sh`" in text
    assert "```bash" in text        # sh → bash fence
    assert "#!/bin/sh\necho hi" in text
    assert "## `assets/notes.txt`" in text

    # _meta.json excluded, README excluded from appendix
    assert "## `_meta.json`" not in text
    assert "## `README.md`" not in text

    # Pinning: path name embeds slug + version + 16-char hash
    assert path.name.startswith("my-skill@0.5@sha256-")
    assert path.name.endswith(".md")
    assert len(digest) == 64        # full sha256 hex


def test_flat_md_no_readme(tmp_path: Path):
    meta = {"slug": "barebones", "version": "1.0"}
    zpath = _make_zip(tmp_path, {
        "_meta.json": json.dumps(meta),
        "SKILL.md":   "# instruction",
    })

    path, _, _ = fetch_from_zip(zpath, cache_dir=tmp_path / "cache")
    text = path.read_text()
    # No appendix (nothing to append), no README section.
    assert "# barebones (pack v1.0)" in text
    assert "# instruction" in text
    assert "Appendix" not in text


def test_pin_is_idempotent(tmp_path: Path):
    bundle = SkillBundle(slug="x", version="1", source="test", files={})
    flat = "# x\n"
    cache = tmp_path / "cache"

    p1, d1 = pin(bundle, flat, cache_dir=cache)
    mtime_1 = p1.stat().st_mtime_ns

    # Same input → same output path + same hash.
    p2, d2 = pin(bundle, flat, cache_dir=cache)
    assert p1 == p2
    assert d1 == d2

    # Second call must not rewrite the file (mtime preserved).
    assert p2.stat().st_mtime_ns == mtime_1


def test_pin_different_content_different_path(tmp_path: Path):
    bundle = SkillBundle(slug="x", version="1", source="test", files={})
    p1, _ = pin(bundle, "# one\n",   cache_dir=tmp_path / "cache")
    p2, _ = pin(bundle, "# two!!\n", cache_dir=tmp_path / "cache")
    assert p1 != p2
    assert p1.exists() and p2.exists()
