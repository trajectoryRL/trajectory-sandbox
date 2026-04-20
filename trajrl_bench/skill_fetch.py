"""Fetch and flatten skill packs into a single SKILL.md.

The trajrl-bench contract is that every miner/harness reads one file,
`/workspace/SKILL.md`. Real-world packs (pskoett/self-improving-agent,
etc.) ship as multi-file bundles with references, hooks, and scripts.
This module flattens such a bundle into one SKILL.md the agent can
consume regardless of which harness is running it.

Currently supports loading from a clawhub-style zip (produced by
`clawdhub download ...`). Future: fetch directly from clawhub.ai by
slug.

Output layout:

    # <slug> (pack v<version>)
    <README.md body>
    ---
    <SKILL.md body>        # the main instruction — keep this close to the top
    ---
    # Appendix — supporting files from the pack
    ## `references/examples.md`
    ...
    ## `scripts/extract-skill.sh`
    ```bash
    ...
    ```

Pinning: the flat output is SHA-256'd; the cache path embeds the first
16 hex chars so bench configs can reference a specific flattening and
detect drift if a pack is re-released under the same version.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_CACHE_DIR = Path.home() / ".trajrl-bench" / "skills"


# Files excluded from the flat SKILL.md — either not text, captured
# elsewhere (_meta.json → filename), or the originals we've already
# placed above the appendix.
_EXCLUDE_FROM_APPENDIX: frozenset[str] = frozenset({
    "SKILL.md",
    "README.md",
    "_meta.json",
})

# Extension → Markdown fence language. Unlisted text files are
# fenced as plain ``` blocks.
_FENCE_LANG: dict[str, str] = {
    ".sh":   "bash",
    ".bash": "bash",
    ".js":   "javascript",
    ".ts":   "typescript",
    ".py":   "python",
    ".yaml": "yaml",
    ".yml":  "yaml",
    ".json": "json",
    ".toml": "toml",
}

_TEXT_EXTS: frozenset[str] = frozenset({
    ".md", ".markdown", ".txt",
    ".sh", ".bash",
    ".js", ".ts", ".jsx", ".tsx",
    ".py",
    ".yaml", ".yml", ".json", ".toml",
})


@dataclass
class SkillBundle:
    """A skill pack unpacked into memory. Paths are relative to the pack root."""

    slug: str
    version: str
    source: str                          # e.g. "zip:self-improving-agent-3.0.16.zip"
    files: dict[str, str] = field(default_factory=dict)


def load_from_zip(zip_path: Path) -> SkillBundle:
    """Load a clawhub-style skill zip into memory.

    The zip is expected to contain a `_meta.json` with at least `slug` and
    `version` fields, matching what `clawdhub download <slug>` produces.
    Binary files are skipped silently; everything decodable as UTF-8 is
    captured under its in-archive path.
    """
    with zipfile.ZipFile(zip_path) as z:
        try:
            meta = json.loads(z.read("_meta.json").decode("utf-8"))
        except KeyError as e:
            raise ValueError(f"{zip_path}: missing _meta.json") from e

        slug = meta.get("slug") or "unknown-skill"
        version = meta.get("version") or "unversioned"

        files: dict[str, str] = {}
        for info in z.infolist():
            if info.is_dir():
                continue
            raw = z.read(info.filename)
            try:
                files[info.filename] = raw.decode("utf-8")
            except UnicodeDecodeError:
                # Binary file in a skill pack is rare and not useful to the
                # text-only SKILL.md output. Skip silently.
                continue

    return SkillBundle(
        slug=slug,
        version=version,
        source=f"zip:{zip_path.name}",
        files=files,
    )


def to_flat_skill_md(bundle: SkillBundle) -> str:
    """Flatten a bundle into a single SKILL.md suitable for /workspace/SKILL.md."""
    parts: list[str] = []

    parts.append(f"# {bundle.slug} (pack v{bundle.version})")
    parts.append(f"<!-- source: {bundle.source} — flattened by trajrl_bench.skill_fetch -->")
    parts.append("")

    if readme := bundle.files.get("README.md", "").strip():
        parts.append(readme)
        parts.append("")

    if main := bundle.files.get("SKILL.md", "").strip():
        parts.append("---")
        parts.append("")
        parts.append(main)
        parts.append("")

    appendix_files = sorted(
        rel for rel in bundle.files
        if rel not in _EXCLUDE_FROM_APPENDIX
        and Path(rel).suffix.lower() in _TEXT_EXTS
        and bundle.files[rel].strip()
    )
    if appendix_files:
        parts.append("---")
        parts.append("")
        parts.append("# Appendix — supporting files from the pack")
        parts.append("")
        for rel in appendix_files:
            ext = Path(rel).suffix.lower()
            body = bundle.files[rel].strip()
            parts.append(f"## `{rel}`")
            parts.append("")
            if ext in {".md", ".markdown", ".txt"}:
                parts.append(body)
            else:
                lang = _FENCE_LANG.get(ext, "")
                parts.append(f"```{lang}")
                parts.append(body)
                parts.append("```")
            parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pin(bundle: SkillBundle, flat_md: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> tuple[Path, str]:
    """Write the flat SKILL.md to a content-addressed cache path.

    Returns (path, full-hex-digest). The filename embeds the first 16 hex
    chars for a stable human-readable reference; the caller gets the full
    digest for integrity pinning in bench configs.
    """
    digest = _digest(flat_md)
    name = f"{bundle.slug}@{bundle.version}@sha256-{digest[:16]}.md"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / name
    # Idempotent: write only if content differs (avoids touch-time churn
    # on repeated calls with the same input).
    if not path.exists() or path.read_text() != flat_md:
        path.write_text(flat_md)
    return path, digest


def fetch_from_zip(zip_path: Path, cache_dir: Path = DEFAULT_CACHE_DIR) -> tuple[Path, str, SkillBundle]:
    """Load a zip, flatten it, pin it. Returns (cache_path, digest, bundle)."""
    bundle = load_from_zip(zip_path)
    flat = to_flat_skill_md(bundle)
    path, digest = pin(bundle, flat, cache_dir)
    return path, digest, bundle
