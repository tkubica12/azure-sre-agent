from __future__ import annotations

from pathlib import Path

from labctl.image import compute_image_tag, content_hash, git_commit_short


def _init_git_repo(repo_root: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_root, check=True)
    (repo_root / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo_root, check=True)


def _make_app_dir(tmp_path: Path) -> Path:
    app_dir = tmp_path / "app"
    (app_dir / "pulsemart").mkdir(parents=True)
    (app_dir / "requirements.txt").write_text("fastapi==1.0.0\n", encoding="utf-8")
    (app_dir / "pulsemart" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    return app_dir


def test_content_hash_is_stable_for_unchanged_files(tmp_path: Path) -> None:
    app_dir = _make_app_dir(tmp_path)

    assert content_hash(app_dir) == content_hash(app_dir)


def test_content_hash_changes_when_a_file_changes(tmp_path: Path) -> None:
    app_dir = _make_app_dir(tmp_path)
    before = content_hash(app_dir)

    (app_dir / "pulsemart" / "main.py").write_text("print('changed')\n", encoding="utf-8")

    assert content_hash(app_dir) != before


def test_content_hash_ignores_excluded_directories(tmp_path: Path) -> None:
    app_dir = _make_app_dir(tmp_path)
    before = content_hash(app_dir)

    cache_dir = app_dir / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "main.cpython-312.pyc").write_bytes(b"\x00\x01")

    assert content_hash(app_dir) == before


def test_git_commit_short_returns_sha_in_a_real_repo(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)

    commit = git_commit_short(tmp_path)

    assert commit != "nogit"
    assert len(commit) == 12
    assert all(c in "0123456789abcdef" for c in commit)


def test_git_commit_short_falls_back_when_not_a_repo(tmp_path: Path) -> None:
    assert git_commit_short(tmp_path) == "nogit"


def test_compute_image_tag_combines_commit_and_content_hash(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    app_dir = _make_app_dir(tmp_path)

    tag = compute_image_tag(tmp_path, app_dir)

    commit = git_commit_short(tmp_path)
    hash_part = content_hash(app_dir)
    assert tag == f"{commit}-{hash_part}"
