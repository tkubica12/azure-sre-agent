"""Deterministic, reproducible image tagging for the PulseMart workload
(see SPEC.md section 7: "The image tag is derived from the Git commit plus a
content hash so deployments are reproducible and inspectable.").
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from labctl.procutil import run_command

#: Files under app/ that do not affect the built image and must not perturb
#: the content hash (build artifacts, caches, local virtual environments).
_EXCLUDED_DIR_NAMES = frozenset(
    {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".git"}
)


def _iter_build_relevant_files(app_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(app_dir.rglob("*")):
        if path.is_dir():
            continue
        if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        if path.suffix in {".pyc"}:
            continue
        files.append(path)
    return files


def content_hash(app_dir: Path) -> str:
    """A short, stable hash over every file that affects the built image
    (source, Dockerfile, pinned requirements), independent of git history.
    Rerunning against unchanged files always produces the same hash, so
    `labctl deploy` can detect "nothing changed" and skip a redundant build.
    """

    digest = hashlib.sha256()
    for path in _iter_build_relevant_files(app_dir):
        relative = path.relative_to(app_dir).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def git_commit_short(repo_root: Path) -> str:
    """Short commit SHA for traceability, or ``"nogit"`` if the directory is
    not a git repository or has no commits yet (fresh clones between the
    first commit and the first `labctl deploy` are still deployable).
    """

    result = run_command(
        ["git", "rev-parse", "--short=12", "HEAD"], cwd=repo_root, timeout=15.0, retries=0
    )
    if not result.ok:
        return "nogit"
    return result.stdout.strip() or "nogit"


def compute_image_tag(repo_root: Path, app_dir: Path) -> str:
    """Return the deterministic image tag: ``<git-commit>-<content-hash>``."""

    return f"{git_commit_short(repo_root)}-{content_hash(app_dir)}"


__all__ = ["content_hash", "git_commit_short", "compute_image_tag"]
