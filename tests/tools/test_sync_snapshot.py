from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.review_snapshot import sync_snapshot


EXPECTED = "YiweiWang1203/mavis-ui-agent-review"


def run_git(repo: Path, *args: str) -> None:
    proc = subprocess.run(["git", *args], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def make_staging(tmp_path: Path, status: str = "PASS") -> Path:
    staging = tmp_path / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    (staging / "README.md").write_text("snapshot\n", encoding="utf-8")
    (staging / "REVIEW_SNAPSHOT_NOTICE.md").write_text("notice\n", encoding="utf-8")
    file_hashes = {
        "README.md": hashlib.sha256((staging / "README.md").read_bytes()).hexdigest(),
        "REVIEW_SNAPSHOT_NOTICE.md": hashlib.sha256((staging / "REVIEW_SNAPSHOT_NOTICE.md").read_bytes()).hexdigest(),
    }
    manifest = {
        "schema_version": 1,
        "source_commit": "abc123",
        "policy_version": "test",
        "gitleaks_status": status,
        "file_hashes": file_hashes,
    }
    (staging / "SNAPSHOT_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    return staging


def make_target(tmp_path: Path, branch: str = "review") -> Path:
    target = tmp_path / "target"
    target.mkdir()
    run_git(target, "init")
    run_git(target, "config", "user.email", "review@example.com")
    run_git(target, "config", "user.name", "Review Test")
    run_git(target, "remote", "add", "origin", f"https://github.com/{EXPECTED}.git")
    (target / "old.txt").write_text("old\n", encoding="utf-8")
    run_git(target, "add", ".")
    run_git(target, "commit", "-m", "initial")
    run_git(target, "checkout", "-b", branch)
    return target


def test_sync_copies_staging_removes_old_files_and_preserves_git(tmp_path: Path) -> None:
    staging = make_staging(tmp_path)
    target = make_target(tmp_path)

    sync_snapshot.sync_snapshot(staging, target, EXPECTED)

    assert (target / ".git").exists()
    assert (target / "README.md").read_text(encoding="utf-8") == "snapshot\n"
    assert not (target / "old.txt").exists()


def test_sync_rejects_missing_manifest(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    target = make_target(tmp_path)

    with pytest.raises(sync_snapshot.SyncUsageError, match="SNAPSHOT_MANIFEST"):
        sync_snapshot.sync_snapshot(staging, target, EXPECTED)


def test_sync_rejects_nonpassing_gitleaks_status(tmp_path: Path) -> None:
    staging = make_staging(tmp_path, status="FAIL")
    target = make_target(tmp_path)

    with pytest.raises(sync_snapshot.SyncUsageError, match="gitleaks_status"):
        sync_snapshot.sync_snapshot(staging, target, EXPECTED)


def test_sync_rejects_main_and_master(tmp_path: Path) -> None:
    staging = make_staging(tmp_path)
    target = make_target(tmp_path, branch="review")
    run_git(target, "checkout", "-b", "main")

    with pytest.raises(sync_snapshot.SyncUsageError, match="main or master"):
        sync_snapshot.sync_snapshot(staging, target, EXPECTED)


def test_sync_rejects_remote_mismatch(tmp_path: Path) -> None:
    staging = make_staging(tmp_path)
    target = make_target(tmp_path)

    with pytest.raises(sync_snapshot.SyncUsageError, match="remote"):
        sync_snapshot.sync_snapshot(staging, target, "other/repo")


def test_remote_normalization_accepts_supported_github_forms() -> None:
    remotes = "\n".join(
        [
            "origin\thttps://github.com/YiweiWang1203/mavis-ui-agent-review.git (fetch)",
            "ssh\tgit@github.com:YiweiWang1203/mavis-ui-agent-review.git (push)",
            "sshurl\tssh://git@github.com/YiweiWang1203/mavis-ui-agent-review.git (push)",
        ]
    )

    assert sync_snapshot.remote_matches(remotes, EXPECTED)
    assert sync_snapshot.normalize_github_remote("https://github.com/YiweiWang1203/mavis-ui-agent-review.git") == EXPECTED
    assert sync_snapshot.normalize_github_remote("git@github.com:YiweiWang1203/mavis-ui-agent-review.git") == EXPECTED
    assert sync_snapshot.normalize_github_remote("ssh://git@github.com/YiweiWang1203/mavis-ui-agent-review.git") == EXPECTED


def test_remote_normalization_rejects_malicious_or_credential_urls() -> None:
    assert sync_snapshot.normalize_github_remote("https://github.com/YiweiWang1203/mavis-ui-agent-review-malicious.git") != EXPECTED
    assert sync_snapshot.normalize_github_remote("https://github.com/OtherOwner/mavis-ui-agent-review.git") != EXPECTED
    assert sync_snapshot.normalize_github_remote("https://example.com/YiweiWang1203/mavis-ui-agent-review.git") is None
    assert sync_snapshot.normalize_github_remote("https://git@github.com/YiweiWang1203/mavis-ui-agent-review.git") is None
    assert sync_snapshot.normalize_github_remote("https://user@github.com/YiweiWang1203/mavis-ui-agent-review.git") is None
    assert sync_snapshot.normalize_github_remote("https://user:pass@github.com/YiweiWang1203/mavis-ui-agent-review.git") is None


def test_sync_rejects_dirty_target(tmp_path: Path) -> None:
    staging = make_staging(tmp_path)
    target = make_target(tmp_path)
    (target / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(sync_snapshot.SyncUsageError, match="clean"):
        sync_snapshot.sync_snapshot(staging, target, EXPECTED)


def test_sync_rejects_symbolic_links(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    staging = make_staging(tmp_path)
    target = make_target(tmp_path)
    link = staging / "link.txt"
    try:
        link.symlink_to(staging / "README.md")
    except OSError:
        link.write_text("not a real link\n", encoding="utf-8")
        original_is_symlink = Path.is_symlink

        def fake_is_symlink(path: Path) -> bool:
            if path == link:
                return True
            return original_is_symlink(path)

        monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)

    with pytest.raises(sync_snapshot.SyncUsageError, match="symbolic link"):
        sync_snapshot.sync_snapshot(staging, target, EXPECTED)


def test_safe_remove_rejects_path_escape(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(sync_snapshot.SyncError, match="outside target"):
        sync_snapshot.safe_remove(outside, target)


def test_sync_rejects_modified_added_deleted_and_invalid_manifest_files(tmp_path: Path) -> None:
    target = make_target(tmp_path)

    staging = make_staging(tmp_path)
    (staging / "README.md").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(sync_snapshot.SyncUsageError, match="hash"):
        sync_snapshot.sync_snapshot(staging, target, EXPECTED)

    staging = make_staging(tmp_path)
    (staging / "extra.txt").write_text("extra\n", encoding="utf-8")
    with pytest.raises(sync_snapshot.SyncUsageError, match="file set"):
        sync_snapshot.sync_snapshot(staging, target, EXPECTED)

    staging = make_staging(tmp_path)
    (staging / "README.md").unlink()
    with pytest.raises(sync_snapshot.SyncUsageError, match="file set"):
        sync_snapshot.sync_snapshot(staging, target, EXPECTED)

    staging = make_staging(tmp_path)
    manifest = json.loads((staging / "SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8"))
    manifest["file_hashes"]["README.md"] = "abc"
    (staging / "SNAPSHOT_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(sync_snapshot.SyncUsageError, match="invalid sha256"):
        sync_snapshot.sync_snapshot(staging, target, EXPECTED)


def test_sync_rejects_forged_status_missing_notice_and_staging_git(tmp_path: Path) -> None:
    target = make_target(tmp_path)

    staging = make_staging(tmp_path)
    manifest = json.loads((staging / "SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8"))
    manifest["gitleaks_status"] = "PASS"
    manifest["file_hashes"]["README.md"] = hashlib.sha256(b"forged").hexdigest()
    (staging / "SNAPSHOT_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(sync_snapshot.SyncUsageError, match="hash"):
        sync_snapshot.sync_snapshot(staging, target, EXPECTED)

    staging = make_staging(tmp_path)
    (staging / "REVIEW_SNAPSHOT_NOTICE.md").unlink()
    with pytest.raises(sync_snapshot.SyncUsageError, match="NOTICE"):
        sync_snapshot.sync_snapshot(staging, target, EXPECTED)

    staging = make_staging(tmp_path)
    (staging / ".git").mkdir()
    (staging / ".git" / "config").write_text("git\n", encoding="utf-8")
    with pytest.raises(sync_snapshot.SyncUsageError, match=".git"):
        sync_snapshot.sync_snapshot(staging, target, EXPECTED)


def test_sync_rejects_dangerous_path_relationships(tmp_path: Path) -> None:
    staging = make_staging(tmp_path)
    target = make_target(tmp_path)

    with pytest.raises(sync_snapshot.SyncUsageError, match="equal"):
        sync_snapshot.validate_path_relationships(staging, staging)
    with pytest.raises(sync_snapshot.SyncUsageError, match="inside target"):
        sync_snapshot.validate_path_relationships(target / "nested", target)
    with pytest.raises(sync_snapshot.SyncUsageError, match="inside staging"):
        sync_snapshot.validate_path_relationships(staging, staging / "nested")


def test_sync_rejects_roots_homes_and_multilevel_nesting(tmp_path: Path) -> None:
    staging = tmp_path / "staging" / "deep" / "snapshot"
    target = tmp_path / "target" / "deep" / "repo"

    unsafe = [
        (target / "several" / "levels" / "staging", target),
        (staging, staging / "several" / "levels" / "target"),
        (Path(staging.anchor), target),
        (staging, Path(target.anchor)),
        (Path.home(), target),
        (staging, Path.home()),
    ]
    for unsafe_staging, unsafe_target in unsafe:
        with pytest.raises(sync_snapshot.SyncUsageError):
            sync_snapshot.validate_path_relationships(unsafe_staging, unsafe_target)
