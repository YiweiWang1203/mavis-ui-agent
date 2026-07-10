from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 3


class SyncError(Exception):
    exit_code = EXIT_FAILURE


class SyncUsageError(SyncError):
    exit_code = EXIT_USAGE


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        check=False,
    )


def require_git(args: list[str], cwd: Path, stage: str) -> str:
    proc = run_git(args, cwd)
    if proc.returncode != 0:
        raise SyncUsageError(f"{stage} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def is_same_or_within(child: Path, parent: Path) -> bool:
    return child.resolve() == parent.resolve() or is_within(child, parent)


def is_root_path(path: Path) -> bool:
    resolved = path.resolve()
    return resolved.parent == resolved


def is_user_home(path: Path) -> bool:
    try:
        return path.resolve() == Path.home().resolve()
    except Exception:
        return False


def validate_path_relationships(staging: Path, target: Path) -> None:
    staging_resolved = staging.resolve()
    target_resolved = target.resolve()
    if staging_resolved == target_resolved:
        raise SyncUsageError("staging must not equal target")
    if is_same_or_within(staging_resolved, target_resolved):
        raise SyncUsageError("staging must not be inside target")
    if is_same_or_within(target_resolved, staging_resolved):
        raise SyncUsageError("target must not be inside staging")
    if is_root_path(staging_resolved) or is_root_path(target_resolved):
        raise SyncUsageError("staging and target must not be filesystem roots")
    if is_user_home(staging_resolved) or is_user_home(target_resolved):
        raise SyncUsageError("staging and target must not be the user home directory")


def normalize_github_remote(value: str) -> str | None:
    raw = value.strip()
    if raw.startswith("git@github.com:"):
        repo = raw.removeprefix("git@github.com:")
    else:
        parsed = urlparse(raw)
        if parsed.scheme == "https" and (parsed.username or parsed.password):
            return None
        if parsed.scheme not in {"https", "ssh"}:
            return None
        if parsed.scheme == "ssh" and parsed.username != "git":
            return None
        if parsed.password:
            return None
        if parsed.hostname != "github.com":
            return None
        repo = parsed.path.lstrip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    parts = [part for part in repo.split("/") if part]
    if len(parts) != 2:
        return None
    return f"{parts[0]}/{parts[1]}"


def remote_matches(remotes_output: str, expected_remote: str) -> bool:
    expected = normalize_github_remote(expected_remote) or expected_remote.strip().removesuffix(".git")
    for line in remotes_output.splitlines():
        pieces = line.split()
        if len(pieces) < 2:
            continue
        normalized = normalize_github_remote(pieces[1])
        if normalized == expected:
            return True
    return False


def load_manifest(staging: Path) -> dict[str, object]:
    manifest_path = staging / "SNAPSHOT_MANIFEST.json"
    if not manifest_path.exists():
        raise SyncUsageError("staging is missing SNAPSHOT_MANIFEST.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SyncUsageError(f"staging manifest is invalid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SyncUsageError("staging manifest must be a JSON object")
    return manifest


def validate_manifest_schema(manifest: dict[str, object]) -> None:
    required = {"schema_version", "source_commit", "policy_version", "gitleaks_status", "file_hashes"}
    missing = sorted(required - set(manifest))
    if missing:
        raise SyncUsageError(f"staging manifest missing required fields: {', '.join(missing)}")
    if manifest.get("gitleaks_status") != "PASS":
        raise SyncUsageError("staging manifest gitleaks_status must be PASS")
    file_hashes = manifest.get("file_hashes")
    if not isinstance(file_hashes, dict):
        raise SyncUsageError("staging manifest file_hashes must be an object")
    for rel, digest in file_hashes.items():
        if not isinstance(rel, str) or not isinstance(digest, str):
            raise SyncUsageError("staging manifest file_hashes must map strings to strings")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SyncUsageError(f"staging manifest has invalid sha256 for {rel}")


def calculate_staging_hashes(staging: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(p for p in staging.rglob("*") if p.is_file()):
        rel = path.relative_to(staging)
        rel_text = str(rel).replace("\\", "/")
        if rel_text == "SNAPSHOT_MANIFEST.json":
            continue
        if ".git" in rel.parts:
            raise SyncUsageError("staging must not contain .git content")
        if path.is_symlink():
            raise SyncUsageError(f"staging contains a symbolic link: {rel_text}")
        hashes[rel_text] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def verify_staging_integrity(staging: Path, manifest: dict[str, object]) -> None:
    for path in staging.rglob("*"):
        rel = path.relative_to(staging)
        if ".git" in rel.parts:
            raise SyncUsageError("staging must not contain .git content")
        if path.is_symlink():
            rel_text = str(rel).replace("\\", "/")
            raise SyncUsageError(f"staging contains a symbolic link: {rel_text}")
    validate_manifest_schema(manifest)
    recorded = manifest["file_hashes"]
    assert isinstance(recorded, dict)
    if "SNAPSHOT_MANIFEST.json" in recorded:
        raise SyncUsageError("staging manifest must not hash itself")
    if "REVIEW_SNAPSHOT_NOTICE.md" not in recorded:
        raise SyncUsageError("staging manifest must include REVIEW_SNAPSHOT_NOTICE.md")
    if not (staging / "REVIEW_SNAPSHOT_NOTICE.md").exists():
        raise SyncUsageError("staging is missing REVIEW_SNAPSHOT_NOTICE.md")
    actual = calculate_staging_hashes(staging)
    if set(actual) != set(recorded):
        raise SyncUsageError("staging file set does not match manifest")
    for rel, digest in actual.items():
        if recorded[rel] != digest:
            raise SyncUsageError(f"staging file hash does not match manifest: {rel}")


def validate_inputs(staging: Path, target: Path, expected_remote: str) -> dict[str, object]:
    validate_path_relationships(staging, target)
    if not staging.exists() or not staging.is_dir():
        raise SyncUsageError("staging directory does not exist")
    manifest = load_manifest(staging)
    verify_staging_integrity(staging, manifest)
    if not target.exists() or not (target / ".git").exists():
        raise SyncUsageError("target must be a Git repository with .git")
    branch = require_git(["branch", "--show-current"], target, "target branch check")
    if branch in {"main", "master"}:
        raise SyncUsageError("refusing to sync on main or master")
    status = require_git(["status", "--short"], target, "target status check")
    if status:
        raise SyncUsageError("target working tree must be clean")
    remotes = require_git(["remote", "-v"], target, "target remote check")
    if not remote_matches(remotes, expected_remote):
        raise SyncUsageError("target remote does not match expected remote")
    for path in target.rglob("*"):
        if ".git" in path.relative_to(target).parts:
            continue
        if path.is_symlink():
            raise SyncUsageError(f"target contains a symbolic link: {path.relative_to(target)}")
    return manifest


def safe_remove(path: Path, target: Path) -> None:
    resolved = path.resolve()
    if not is_within(resolved, target.resolve()):
        raise SyncError(f"refusing to remove path outside target: {path}")
    if ".git" in path.relative_to(target).parts:
        raise SyncError("refusing to remove target .git content")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def sync_snapshot(staging: Path, target: Path, expected_remote: str) -> None:
    validate_inputs(staging, target, expected_remote)
    staging_files = {path.relative_to(staging) for path in staging.rglob("*") if path.is_file()}
    target_files = {
        path.relative_to(target)
        for path in target.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(target).parts
    }
    for rel in sorted(target_files - staging_files, reverse=True):
        safe_remove(target / rel, target)
    for rel in sorted(staging_files):
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staging / rel, destination)
    for directory in sorted((p for p in target.rglob("*") if p.is_dir() and ".git" not in p.relative_to(target).parts), reverse=True):
        if directory == target:
            continue
        try:
            directory.rmdir()
        except OSError:
            pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync a sanitized review snapshot into a local review repository.")
    parser.add_argument("--staging", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--expected-remote", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        sync_snapshot(Path(args.staging), Path(args.target), args.expected_remote)
        print("Suggested verification commands:")
        print("git status --short")
        print("git diff --stat")
        return EXIT_OK
    except SyncUsageError as exc:
        print(f"sync validation failed: {exc}", file=sys.stderr)
        return exc.exit_code
    except SyncError as exc:
        print(f"sync failed: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
