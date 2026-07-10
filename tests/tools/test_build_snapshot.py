from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from tools.review_snapshot import build_snapshot


def run_git(repo: Path, *args: str) -> None:
    proc = subprocess.run(["git", *args], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "review@example.com")
    run_git(repo, "config", "user.name", "Review Test")
    write(repo / "README.md", "hello\n")
    write(repo / "ARCHITECTURE.md", "arch\n")
    write(repo / "requirements.txt", "nvidia-cufile==1\nnvidia-curand==1\n")
    write(
        repo / ".env.example",
        'SILICONFLOW_API_KEY="sk-your-siliconflow-api-key-here"\n'
        'TAVILY_API_KEY="tvly-your-key-here"\n'
        "OPENAI_API_KEY=${SILICONFLOW_API_KEY}\n"
        "PUBLIC_URL=https://api.siliconflow.cn/v1\n"
        "LOCAL_URL=http://localhost:11434\n",
    )
    write(repo / "src" / "api" / "app.py", "BASE='https://api.siliconflow.cn/v1'\n")
    write(repo / "src" / "agents" / "llm_old.py", "legacy\n")
    write(repo / "src" / "prompts" / "meeting_old.md", "legacy\n")
    write(repo / "src" / "prompts" / "planner.md", "User deploy\nIdentityFile C:/Users/name/.ssh/id_rsa\n")
    write(repo / "src" / "folder.py", "ok\n")
    write(repo / "scripts" / "run_video_ui_workflow.py", "def main():\n    return 0\n")
    write(repo / "scripts" / "check_env.py", "print('manual')\n")
    write(repo / "tests" / "test_example.py", "def test_ok():\n    assert True\n")
    write(repo / "tests" / "test_real_data.py", "SECRET='nope'\n")
    write(repo / "data" / "input.txt", "private data\n")
    write(repo / "src" / "__pycache__" / "x.pyc", "compiled\n")
    write(repo / "image.jpg", "jpg\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "initial")
    return repo


def args_for(repo: Path, tmp_path: Path, **overrides: object) -> argparse.Namespace:
    values = {
        "source": str(repo),
        "output": str(tmp_path / "staging"),
        "commit": "HEAD",
        "policy": str(Path.cwd() / "tools" / "review_snapshot" / "policy.json"),
        "local_policy": None,
        "report_dir": str(tmp_path / "audit"),
        "gitleaks_path": None,
        "clean_output": True,
        "dry_run": False,
        "require_gitleaks": False,
        "max_file_size": None,
        "verbose": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_builds_from_commit_and_excludes_git_data_media_and_legacy(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    output = tmp_path / "staging"
    result = build_snapshot.build_snapshot(args_for(repo, tmp_path))

    assert (output / "README.md").exists()
    assert (output / "src" / "api" / "app.py").exists()
    assert (output / "scripts" / "run_video_ui_workflow.py").exists()
    assert not (output / ".git").exists()
    assert not (output / "data").exists()
    assert not (output / "image.jpg").exists()
    assert not (output / "src" / "agents" / "llm_old.py").exists()
    assert not (output / "src" / "prompts" / "meeting_old.md").exists()
    assert "src/folder.py" in result.included
    assert "src/agents/llm_old.py" in result.legacy
    assert "tests/test_real_data.py" in result.excluded


def test_uncommitted_files_do_not_enter_snapshot(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "src" / "uncommitted.py", "print('not archived')\n")

    with pytest.raises(build_snapshot.UsageError, match="working tree"):
        build_snapshot.build_snapshot(args_for(repo, tmp_path))


def test_dirty_worktree_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "README.md", "dirty\n")

    with pytest.raises(build_snapshot.UsageError, match="working tree"):
        build_snapshot.build_snapshot(args_for(repo, tmp_path))


def test_dangerous_output_paths_fail(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(build_snapshot.UsageError, match="output must not equal source"):
        build_snapshot.build_snapshot(args_for(repo, tmp_path, output=str(repo)))
    with pytest.raises(build_snapshot.UsageError, match="ancestor of source"):
        build_snapshot.build_snapshot(args_for(repo, tmp_path, output=str(repo.parent)))
    with pytest.raises(build_snapshot.UsageError, match="report-dir must not be inside output"):
        build_snapshot.build_snapshot(args_for(repo, tmp_path, report_dir=str(tmp_path / "staging" / "audit")))


def test_validate_paths_rejects_all_dangerous_relationships(tmp_path: Path) -> None:
    source = tmp_path / "source" / "deep" / "repo"
    source.mkdir(parents=True)
    safe_output = tmp_path / "output"
    safe_report = tmp_path / "report"

    unsafe = [
        (source, safe_report, None),
        (source / "nested" / "output", safe_report, None),
        (tmp_path / "source", safe_report, None),
        (Path(source.anchor), safe_report, None),
        (Path.home(), safe_report, None),
        (safe_output, safe_output, None),
        (safe_report / "nested" / "output", safe_report, None),
        (safe_output, safe_output / "nested" / "report", None),
        (safe_output, safe_report, safe_output / "policy" / "local.json"),
        (safe_output / "nested", safe_report, safe_output / "local.json"),
    ]
    for output, report, local_policy in unsafe:
        with pytest.raises(build_snapshot.UsageError):
            build_snapshot.validate_paths(source, output, report, local_policy)


def test_dotenv_sanitizer_replaces_fake_sk_and_keeps_source_unchanged(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    original = (repo / ".env.example").read_text(encoding="utf-8")
    build_snapshot.build_snapshot(args_for(repo, tmp_path))
    staged = (tmp_path / "staging" / ".env.example").read_text(encoding="utf-8")

    assert "sk-your-siliconflow-api-key-here" not in staged
    assert "SILICONFLOW_API_KEY=YOUR_SILICONFLOW_API_KEY" in staged
    assert "TAVILY_API_KEY=YOUR_TAVILY_API_KEY" in staged
    assert "OPENAI_API_KEY=${SILICONFLOW_API_KEY}" in staged
    assert "https://api.siliconflow.cn/v1" in staged
    assert "http://localhost:11434" in staged
    assert (repo / ".env.example").read_text(encoding="utf-8") == original


def test_real_credential_shape_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / ".env.example", "OPENAI_API_KEY=prodsecretvalue12345\n")
    run_git(repo, "add", ".env.example")
    run_git(repo, "commit", "-m", "real-looking")

    with pytest.raises(build_snapshot.SecurityError, match="credential"):
        build_snapshot.build_snapshot(args_for(repo, tmp_path))


def test_local_policy_replaces_paths(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "src" / "prompts" / "planner.md", "Path D:/agentworkspace/mavis-ui-agent and /wyw/meeting_agent_workspace/my_agent\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "paths")
    local_policy = tmp_path / "policy-dir" / "policy.local.json"
    local_policy.parent.mkdir()
    local_policy.write_text(
        json.dumps(
            {
                "literal_replacements": [
                    {"from": "D:\\agentworkspace\\mavis-ui-agent", "to": "<LOCAL_PROJECT_ROOT>"},
                    {"from": "/wyw/meeting_agent_workspace/my_agent", "to": "<REMOTE_PROJECT_ROOT>"},
                ],
                "forbidden_literals": ["FORBIDDEN_LITERAL"],
            }
        ),
        encoding="utf-8",
    )

    build_snapshot.build_snapshot(args_for(repo, tmp_path, local_policy=str(local_policy)))
    staged = (tmp_path / "staging" / "src" / "prompts" / "planner.md").read_text(encoding="utf-8")
    assert "<LOCAL_PROJECT_ROOT>" in staged
    assert "<REMOTE_PROJECT_ROOT>" in staged
    manifest = (tmp_path / "staging" / "SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8")
    assert "D:\\agentworkspace" not in manifest


def test_forbidden_literal_remaining_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "src" / "prompts" / "planner.md", "FORBIDDEN_LITERAL\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "forbidden")
    local_policy = tmp_path / "policy-dir" / "policy.local.json"
    local_policy.parent.mkdir()
    local_policy.write_text(json.dumps({"literal_replacements": [], "forbidden_literals": ["FORBIDDEN_LITERAL"]}), encoding="utf-8")

    with pytest.raises(build_snapshot.SecurityError, match="sensitive content"):
        build_snapshot.build_snapshot(args_for(repo, tmp_path, local_policy=str(local_policy)))


def test_prompt_sanitizer_replaces_ssh_user_and_identity_file(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "src" / "prompts" / "planner.md", "Host prod\n  User deploy\n  IdentityFile C:/Users/name/.ssh/id_rsa\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "ssh")

    build_snapshot.build_snapshot(args_for(repo, tmp_path))
    staged = (tmp_path / "staging" / "src" / "prompts" / "planner.md").read_text(encoding="utf-8")
    assert "<REMOTE_HOST>" in staged
    assert "<REMOTE_USER>" in staged
    assert "<SSH_KEY_PATH>" in staged
    assert "IdentityFile C:/Users" not in staged


def test_manifest_has_sorted_paths_and_no_absolute_paths(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    build_snapshot.build_snapshot(args_for(repo, tmp_path))
    manifest = json.loads((tmp_path / "staging" / "SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8"))
    paths = list(manifest["file_hashes"].keys())
    assert paths == sorted(paths)
    assert all("\\" not in path for path in paths)
    assert str(repo) not in json.dumps(manifest)


def test_same_commit_same_policy_produces_same_file_hashes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    build_snapshot.build_snapshot(args_for(repo, tmp_path, output=str(tmp_path / "one")))
    build_snapshot.build_snapshot(args_for(repo, tmp_path, output=str(tmp_path / "two")))
    one = json.loads((tmp_path / "one" / "SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8"))
    two = json.loads((tmp_path / "two" / "SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8"))
    assert one["file_hashes"] == two["file_hashes"]


def test_require_gitleaks_missing_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    with pytest.raises(build_snapshot.SecurityError, match="required gitleaks"):
        build_snapshot.build_snapshot(
            args_for(repo, tmp_path, require_gitleaks=True, gitleaks_path=str(tmp_path / "missing-gitleaks.exe"))
        )


def test_gitleaks_finding_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    def fake_gitleaks(*_args: object, **_kwargs: object) -> tuple[str, str]:
        raise build_snapshot.SecurityError("gitleaks found one or more findings in staging")

    monkeypatch.setattr(build_snapshot, "run_gitleaks_dir", fake_gitleaks)
    with pytest.raises(build_snapshot.SecurityError, match="gitleaks"):
        build_snapshot.build_snapshot(args_for(repo, tmp_path, gitleaks_path=sys.executable))
    assert not (tmp_path / "staging").exists()


def test_reports_are_not_written_to_staging(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    build_snapshot.build_snapshot(args_for(repo, tmp_path))
    staging_names = {path.name for path in (tmp_path / "staging").iterdir()}
    assert "snapshot-report.local.json" not in staging_names
    assert "gitleaks-staging-redacted.json" not in staging_names
    assert "SNAPSHOT_MANIFEST.json" in staging_names
    assert "REVIEW_SNAPSHOT_NOTICE.md" in staging_names


def test_notice_avoids_disallowed_tool_names(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    build_snapshot.build_snapshot(args_for(repo, tmp_path))
    notice = (tmp_path / "staging" / "REVIEW_SNAPSHOT_NOTICE.md").read_text(encoding="utf-8")
    assert "ChatGPT" not in notice
    assert "Codex" not in notice
    assert "OpenAI" not in notice
    assert "AI" not in notice


def test_public_host_matching_uses_parsed_hostname() -> None:
    policy = {"public_host_allowlist": ["api.openai.com", "api.siliconflow.cn", "localhost", "127.0.0.1"]}

    assert not build_snapshot.url_security_findings("x.py", 1, "url = 'https://api.openai.com/v1'", policy)
    assert build_snapshot.url_security_findings("x.py", 1, "url = 'https://api.openai.com.attacker.example/v1'", policy)
    assert build_snapshot.url_security_findings("x.py", 1, "url = 'https://attacker.example/?target=api.openai.com'", policy)
    assert build_snapshot.url_security_findings("x.py", 1, "url = 'https://user:password@example.com/v1'", policy)
    assert build_snapshot.url_security_findings("x.py", 1, "url = 'https://api.openai.com/v1?token=secret'", policy)


def test_final_manifest_and_notice_are_in_builtin_scan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    seen: list[set[str]] = []
    original_scan = build_snapshot.scan_snapshot

    def tracking_scan(output: Path, local_policy: dict[str, object], policy: dict[str, object] | None = None) -> list[build_snapshot.SecurityFinding]:
        seen.append({str(path.relative_to(output)).replace("\\", "/") for path in output.rglob("*") if path.is_file()})
        return original_scan(output, local_policy, policy)

    monkeypatch.setattr(build_snapshot, "scan_snapshot", tracking_scan)
    build_snapshot.build_snapshot(args_for(repo, tmp_path))

    assert len(seen) == 2
    assert "REVIEW_SNAPSHOT_NOTICE.md" in seen[0]
    assert "SNAPSHOT_MANIFEST.json" in seen[0]
    assert "REVIEW_SNAPSHOT_NOTICE.md" in seen[1]
    assert "SNAPSHOT_MANIFEST.json" in seen[1]


def test_reports_do_not_contain_local_policy_raw_values(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    private_value = "private-host.internal"
    write(repo / "src" / "prompts" / "planner.md", f"Host {private_value}\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "private-host")
    local_policy = tmp_path / "policy-dir" / "policy.local.json"
    local_policy.parent.mkdir()
    local_policy.write_text(
        json.dumps({"literal_replacements": [{"from": private_value, "to": "<REMOTE_HOST>"}], "forbidden_literals": []}),
        encoding="utf-8",
    )

    build_snapshot.build_snapshot(args_for(repo, tmp_path, local_policy=str(local_policy)))
    audit = tmp_path / "audit"
    report_text = "\n".join(path.read_text(encoding="utf-8") for path in audit.glob("*.json"))
    assert private_value not in report_text
    assert "literal_replacement:remote-host" in report_text


def test_legacy_filename_rule_is_semantic_not_substring(tmp_path: Path) -> None:
    policy = json.loads((Path.cwd() / "tools" / "review_snapshot" / "policy.json").read_text(encoding="utf-8"))

    assert build_snapshot.legacy_filename("src/agents/llm_old.py", policy)
    assert build_snapshot.legacy_filename("src/prompts/meeting-OLD.md", policy)
    assert build_snapshot.legacy_filename("scripts/旧脚本.py", policy)
    assert not build_snapshot.legacy_filename("src/folder.py", policy)
    assert not build_snapshot.legacy_filename("src/scolding.py", policy)
    assert not build_snapshot.legacy_filename("tests/golden_test.py", policy)


def test_safe_placeholder_requires_full_match() -> None:
    policy = json.loads((Path.cwd() / "tools" / "review_snapshot" / "policy.json").read_text(encoding="utf-8"))

    for value in ["", "YOUR_API_KEY", "<API_KEY>", "${API_KEY}", "placeholder", "placeholder_api_key", "example", "redacted", "changeme"]:
        assert build_snapshot.safe_placeholder(value, policy)
    for value in [
        "actual-example-secret",
        "production-placeholder-token",
        "real-redacted-password",
        "changeme-but-real-secret",
        "prefix-YOUR_API_KEY-suffix",
    ]:
        assert not build_snapshot.safe_placeholder(value, policy)


def test_private_ip_detection_uses_ipaddress_logic() -> None:
    disallowed = ["10.1.2.3", "172.16.0.1", "172.31.255.255", "192.168.1.1", "169.254.1.1", "100.64.0.1", "fc00::1", "fd00::1", "fe80::1", "::ffff:192.168.1.1"]
    allowed = ["127.0.0.1", "0.0.0.0", "::1"]

    for value in disallowed:
        parsed = build_snapshot.parse_ip_literal(value)
        assert parsed is not None
        assert build_snapshot.is_disallowed_private_address(parsed)
    for value in allowed:
        parsed = build_snapshot.parse_ip_literal(value)
        assert parsed is not None
        assert not build_snapshot.is_disallowed_private_address(parsed)


def test_prompt_sanitizer_replaces_plain_private_ip(tmp_path: Path) -> None:
    redactions: list[build_snapshot.RedactionRecord] = []

    changed = build_snapshot.sanitize_prompt_text("MODEL_API_BASE=http://10.1.2.3:8000/v1\n", "src/prompts/x.md", redactions)

    assert "10.1.2.3" not in changed
    assert "<PRIVATE_IP>" in changed
    assert redactions


def test_generic_text_sanitizes_paths_and_ips_but_preserves_requirement_versions(tmp_path: Path) -> None:
    policy = json.loads((Path.cwd() / "tools" / "review_snapshot" / "policy.json").read_text(encoding="utf-8"))
    redactions: list[build_snapshot.RedactionRecord] = []
    generic = tmp_path / "README.md"
    generic.write_text("Path /wyw/private/project host 10.1.2.3\n", encoding="utf-8")
    build_snapshot.sanitize_file(generic, "README.md", policy, {"literal_replacements": [], "forbidden_literals": []}, redactions)
    assert generic.read_text(encoding="utf-8") == "Path <REMOTE_PROJECT_ROOT> host <PRIVATE_IP>\n"

    requirements = tmp_path / "requirements.txt"
    requirements.write_text("nvidia-curand==10.4.0.35\n", encoding="utf-8")
    build_snapshot.sanitize_file(requirements, "requirements.txt", policy, {"literal_replacements": [], "forbidden_literals": []}, redactions)
    assert requirements.read_text(encoding="utf-8") == "nvidia-curand==10.4.0.35\n"
    assert not build_snapshot.scan_text("requirements.txt", requirements.read_text(encoding="utf-8"), {"forbidden_literals": []}, policy)


def test_dynamic_credential_assignments_are_not_hardcoded_secrets() -> None:
    assert not build_snapshot.suspicious_assignment('api_key = os.getenv("OPENAI_API_KEY")')
    assert not build_snapshot.suspicious_assignment('api_key=os.environ.get("OPENAI_API_KEY")')
    assert build_snapshot.suspicious_assignment("api_key=actual-secret-value")


def test_unknown_template_extensions_do_not_enter_snapshot(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "templates" / "valid.md", "ok\n")
    write(repo / "templates" / "private.blob", "blob\n")
    write(repo / "templates" / "raw", "raw\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "templates")

    result = build_snapshot.build_snapshot(args_for(repo, tmp_path))

    assert (tmp_path / "staging" / "templates" / "valid.md").exists()
    assert not (tmp_path / "staging" / "templates" / "private.blob").exists()
    assert not (tmp_path / "staging" / "templates" / "raw").exists()
    assert "templates/raw" in result.unknown


def test_non_utf8_allowed_file_fails_and_no_output_is_published(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    path = repo / "src" / "binary.py"
    path.write_bytes(b"\xff\xfe\x00")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "binary")

    with pytest.raises(build_snapshot.SecurityError, match="non-UTF-8"):
        build_snapshot.build_snapshot(args_for(repo, tmp_path))
    assert not (tmp_path / "staging").exists()


def test_scripts_selection_uses_classification_and_explicit_allowlist(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "scripts" / "unknown_script.py", "print('unknown')\n")
    write(repo / "scripts" / "download_dataset.py", "print('data')\n")
    write(repo / "scripts" / "machine_specific.py", "print('machine')\n")
    write(repo / "scripts" / "helper.py", "print('helper')\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "scripts")
    policy = json.loads((Path.cwd() / "tools" / "review_snapshot" / "policy.json").read_text(encoding="utf-8"))
    policy["allowed_script_paths"].append("scripts/helper.py")
    custom_policy = tmp_path / "policy.json"
    custom_policy.write_text(json.dumps(policy), encoding="utf-8")

    result = build_snapshot.build_snapshot(args_for(repo, tmp_path, policy=str(custom_policy)))
    staged_scripts = {str(path.relative_to(tmp_path / "staging")).replace("\\", "/") for path in (tmp_path / "staging" / "scripts").glob("*.py")}
    classifications = {item["path"]: item["classification"] for item in result.scripts_classification}

    assert "scripts/run_video_ui_workflow.py" in staged_scripts
    assert "scripts/helper.py" in staged_scripts
    assert "scripts/unknown_script.py" not in staged_scripts
    assert "scripts/download_dataset.py" not in staged_scripts
    assert classifications["scripts/run_video_ui_workflow.py"] == "CURRENT_ENTRYPOINT"
    assert classifications["scripts/helper.py"] == "CURRENT_HELPER"
    assert classifications["scripts/download_dataset.py"] == "DATA_OR_MACHINE_SPECIFIC"
    assert classifications["scripts/unknown_script.py"] == "UNKNOWN"


def test_gitleaks_runs_twice_and_manifest_records_final_scan_count(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    calls: list[Path] = []

    def fake_gitleaks(_path: Path, output: Path, report_path: Path, _require: bool) -> tuple[str, str]:
        calls.append(report_path)
        assert (output / "SNAPSHOT_MANIFEST.json").exists()
        if len(calls) == 2:
            scanned_manifest = json.loads((output / "SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8"))
            assert scanned_manifest["gitleaks_scan_count"] == 2
            assert scanned_manifest["final_tree_scanned"] is True
        return "PASS", "test-version"

    monkeypatch.setattr(build_snapshot, "run_gitleaks_dir", fake_gitleaks)
    build_snapshot.build_snapshot(args_for(repo, tmp_path, gitleaks_path=sys.executable, require_gitleaks=True))
    manifest = json.loads((tmp_path / "staging" / "SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8"))

    assert len(calls) == 2
    assert manifest["gitleaks_status"] == "PASS"
    assert manifest["gitleaks_scan_count"] == 2
    assert manifest["final_tree_scanned"] is True


def test_existing_output_remains_when_new_build_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    output = tmp_path / "staging"
    output.mkdir()
    (output / "old.txt").write_text("old\n", encoding="utf-8")

    def fail_sanitize(*_args: object, **_kwargs: object) -> None:
        raise build_snapshot.SecurityError("sanitize failed")

    monkeypatch.setattr(build_snapshot, "sanitize_file", fail_sanitize)
    with pytest.raises(build_snapshot.SecurityError, match="sanitize failed"):
        build_snapshot.build_snapshot(args_for(repo, tmp_path))

    assert (output / "old.txt").read_text(encoding="utf-8") == "old\n"
    assert not (output / "SNAPSHOT_MANIFEST.json").exists()


def test_success_replaces_old_output(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    output = tmp_path / "staging"
    output.mkdir()
    (output / "old.txt").write_text("old\n", encoding="utf-8")

    build_snapshot.build_snapshot(args_for(repo, tmp_path))

    assert not (output / "old.txt").exists()
    assert (output / "README.md").exists()


def test_publish_failure_restores_old_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    output = tmp_path / "staging"
    output.mkdir()
    (output / "old.txt").write_text("old\n", encoding="utf-8")
    original_rename = Path.rename

    def fail_new_output_rename(path: Path, target: Path) -> Path:
        if path.name.startswith(".staging.tmp-") and Path(target) == output:
            raise OSError("simulated publish failure")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_new_output_rename)
    with pytest.raises(OSError, match="simulated publish failure"):
        build_snapshot.build_snapshot(args_for(repo, tmp_path))

    assert (output / "old.txt").read_text(encoding="utf-8") == "old\n"
    assert not list(tmp_path.glob(".staging.tmp-*"))
    assert not list(tmp_path.glob(".staging.backup-*"))


def test_lfs_fallback_rejects_filter_lfs_when_git_lfs_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / ".gitattributes", "*.bin filter=lfs diff=lfs merge=lfs -text\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "lfs")
    original_run_command = build_snapshot.run_command

    def fake_run_command(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if args[:3] == ["git", "lfs", "ls-files"]:
            return subprocess.CompletedProcess(args, 1, b"", b"git lfs unavailable")
        return original_run_command(args, **kwargs)

    monkeypatch.setattr(build_snapshot, "run_command", fake_run_command)

    with pytest.raises(build_snapshot.UsageError, match="filter=lfs"):
        build_snapshot.build_snapshot(args_for(repo, tmp_path))


def test_lfs_fallback_rejects_when_attributes_cannot_be_determined(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    original_run_command = build_snapshot.run_command

    def fake_run_command(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if args[:3] == ["git", "lfs", "ls-files"] or args[:3] == ["git", "check-attr", "filter"]:
            return subprocess.CompletedProcess(args, 1, b"", b"unavailable")
        return original_run_command(args, **kwargs)

    monkeypatch.setattr(build_snapshot, "run_command", fake_run_command)
    with pytest.raises(build_snapshot.UsageError, match="unable to determine Git LFS attributes"):
        build_snapshot.build_snapshot(args_for(repo, tmp_path))


def test_lfs_fallback_allows_repository_without_lfs_attributes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    original_run_command = build_snapshot.run_command

    def fake_run_command(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if args[:3] == ["git", "lfs", "ls-files"]:
            return subprocess.CompletedProcess(args, 1, b"", b"git lfs unavailable")
        return original_run_command(args, **kwargs)

    monkeypatch.setattr(build_snapshot, "run_command", fake_run_command)
    build_snapshot.build_snapshot(args_for(repo, tmp_path))
    assert (tmp_path / "staging" / "README.md").exists()


def test_validate_tar_member_rejects_unsafe_members() -> None:
    for name, typeflag in [
        ("../escape.txt", tarfile.REGTYPE),
        ("C:/escape.txt", tarfile.REGTYPE),
        ("/escape.txt", tarfile.REGTYPE),
        ("//server/share/escape.txt", tarfile.REGTYPE),
        (r"\\server\share\escape.txt", tarfile.REGTYPE),
        ("link.txt", tarfile.SYMTYPE),
        ("hardlink.txt", tarfile.LNKTYPE),
        ("character-device", tarfile.CHRTYPE),
        ("block-device", tarfile.BLKTYPE),
        ("fifo", tarfile.FIFOTYPE),
    ]:
        member = tarfile.TarInfo(name)
        member.type = typeflag
        with pytest.raises(build_snapshot.SecurityError):
            build_snapshot.validate_tar_member(member)
