from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import ipaddress
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlparse


EXIT_OK = 0
EXIT_BUILD_FAILURE = 1
EXIT_SECURITY_FAILURE = 2
EXIT_USAGE_FAILURE = 3

NOTICE_TEXT = """# Review Snapshot Notice

This is an automatically generated sanitized code review snapshot.

It is not the formal development repository.

It does not contain original Git history.

It does not contain data files, media files, model files, or runtime outputs.

It does not contain real credentials.

Some paths, hosts, SSH information, and prompt examples have been replaced with placeholders.

Do not perform formal business development in this sanitized review repository.

Formal changes must be made on a feature branch in the source repository.

The source commit for this review snapshot is recorded in SNAPSHOT_MANIFEST.json.
"""


class SnapshotError(Exception):
    exit_code = EXIT_BUILD_FAILURE


class UsageError(SnapshotError):
    exit_code = EXIT_USAGE_FAILURE


class SecurityError(SnapshotError):
    exit_code = EXIT_SECURITY_FAILURE


@dataclass
class RedactionRecord:
    path: str
    line: int
    kind: str
    changed: bool
    variable: str | None = None


@dataclass
class SecurityFinding:
    path: str
    line: int
    rule: str
    severity: str
    summary: str


@dataclass
class BuildResult:
    included: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    legacy: list[str] = field(default_factory=list)
    redactions: list[RedactionRecord] = field(default_factory=list)
    findings: list[SecurityFinding] = field(default_factory=list)
    scripts_classification: list[dict[str, Any]] = field(default_factory=list)
    gitleaks_status: str = "NOT_RUN"
    gitleaks_version: str | None = None
    gitleaks_scan_count: int = 0
    final_tree_scanned: bool = False


def normalize_rel(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def run_command(args: list[str], cwd: Path | None = None, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )
    return proc


def require_success(proc: subprocess.CompletedProcess[bytes], stage: str) -> None:
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise SnapshotError(f"{stage} failed with exit code {proc.returncode}: {stderr}")


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise UsageError(f"failed to parse JSON policy {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise UsageError(f"policy must be a JSON object: {path}")
    return data


def validate_policy(policy: dict[str, Any]) -> None:
    required = [
        "schema_version",
        "policy_version",
        "allowed_script_paths",
        "allowed_paths",
        "allowed_extensions",
        "denied_paths",
        "denied_extensions",
        "legacy_filename_rules",
        "credential_field_patterns",
        "credential_value_prefixes",
        "safe_placeholder_patterns",
        "public_host_allowlist",
        "special_sanitizers",
        "max_file_size_bytes",
    ]
    missing = [key for key in required if key not in policy]
    if missing:
        raise UsageError(f"policy missing required fields: {', '.join(missing)}")


def load_local_policy(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"literal_replacements": [], "forbidden_literals": []}
    if not path.exists():
        raise UsageError(f"local policy does not exist: {path}")
    data = load_json(path)
    replacements = data.get("literal_replacements", [])
    forbidden = data.get("forbidden_literals", [])
    if not isinstance(replacements, list) or not isinstance(forbidden, list):
        raise UsageError("local policy must contain list fields literal_replacements and forbidden_literals")
    for item in replacements:
        if not isinstance(item, dict) or "from" not in item or "to" not in item:
            raise UsageError("each literal replacement must contain from and to")
        if looks_like_secret(str(item["from"])) or looks_like_secret(str(item["to"])):
            raise UsageError("local policy must not contain API keys or credential-looking values")
    return data


def resolve_commit(source: Path, commit: str) -> str:
    proc = run_command(["git", "rev-parse", "--verify", f"{commit}^{{commit}}"], cwd=source)
    require_success(proc, "commit validation")
    return proc.stdout.decode("utf-8", errors="replace").strip()


def git_root(path: Path) -> Path:
    proc = run_command(["git", "rev-parse", "--show-toplevel"], cwd=path)
    require_success(proc, "git root validation")
    return Path(proc.stdout.decode("utf-8", errors="replace").strip()).resolve()


def git_branch(source: Path) -> str:
    proc = run_command(["git", "branch", "--show-current"], cwd=source)
    require_success(proc, "git branch")
    return proc.stdout.decode("utf-8", errors="replace").strip()


def git_status_clean(source: Path) -> bool:
    proc = run_command(["git", "status", "--short"], cwd=source)
    require_success(proc, "git status")
    return proc.stdout.decode("utf-8", errors="replace").strip() == ""


def has_submodules(source: Path) -> bool:
    return (source / ".gitmodules").exists()


def lfs_tracked_files(source: Path) -> list[str]:
    proc = run_command(["git", "lfs", "ls-files"], cwd=source)
    if proc.returncode == 0:
        return [line.strip() for line in proc.stdout.decode("utf-8", errors="replace").splitlines() if line.strip()]

    gitattributes = source / ".gitattributes"
    if gitattributes.exists() and "filter=lfs" in gitattributes.read_text(encoding="utf-8", errors="replace"):
        raise UsageError("Git LFS command failed and .gitattributes contains filter=lfs")

    files_proc = run_command(["git", "ls-files"], cwd=source)
    if files_proc.returncode != 0:
        raise UsageError("unable to determine tracked files for Git LFS fallback")
    tracked = [line.strip() for line in files_proc.stdout.decode("utf-8", errors="replace").splitlines() if line.strip()]
    if not tracked:
        return []
    attr_proc = run_command(["git", "check-attr", "filter", "--", *tracked], cwd=source)
    if attr_proc.returncode != 0:
        raise UsageError("unable to determine Git LFS attributes")
    lfs_files = []
    for line in attr_proc.stdout.decode("utf-8", errors="replace").splitlines():
        if line.endswith(": filter: lfs"):
            lfs_files.append(line.split(": filter: ", 1)[0])
    return lfs_files


def is_root_path(path: Path) -> bool:
    resolved = path.resolve()
    return resolved.parent == resolved


def is_user_home(path: Path) -> bool:
    try:
        return path.resolve() == Path.home().resolve()
    except Exception:
        return False


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def is_same_or_within(child: Path, parent: Path) -> bool:
    return child.resolve() == parent.resolve() or is_within(child, parent)


def validate_paths(source: Path, output: Path, report_dir: Path, local_policy: Path | None) -> None:
    source_resolved = source.resolve()
    output_resolved = output.resolve()
    report_resolved = report_dir.resolve()
    if output_resolved == source_resolved:
        raise UsageError("output must not equal source")
    if is_within(output_resolved, source_resolved):
        raise UsageError("output must not be inside source")
    if is_within(source_resolved, output_resolved):
        raise UsageError("output must not be an ancestor of source")
    if is_root_path(output_resolved):
        raise UsageError("output must not be a filesystem root")
    if is_user_home(output_resolved):
        raise UsageError("output must not be the user home directory")
    if is_same_or_within(report_resolved, output_resolved):
        raise UsageError("report-dir must not be inside output")
    if is_same_or_within(output_resolved, report_resolved):
        raise UsageError("output must not be inside report-dir")
    if local_policy:
        local_dir = local_policy.resolve().parent
        if is_same_or_within(local_policy.resolve(), output_resolved):
            raise UsageError("local policy must not be inside output")
        if is_same_or_within(output_resolved, local_dir) or is_same_or_within(local_dir, output_resolved):
            raise UsageError("output must not be nested with local-policy directory")


def preflight(source: Path, output: Path, commit: str, policy_path: Path, report_dir: Path, local_policy: Path | None) -> str:
    if not source.exists():
        raise UsageError(f"source does not exist: {source}")
    root = git_root(source)
    if root != source.resolve():
        raise UsageError(f"source must be the git root: {source}")
    resolved_commit = resolve_commit(source, commit)
    if not git_status_clean(source):
        raise UsageError("source working tree must be clean")
    if has_submodules(source):
        raise UsageError("submodules are not allowed in review snapshots")
    if lfs_tracked_files(source):
        raise UsageError("Git LFS tracked files are not allowed in review snapshots")
    if not policy_path.exists():
        raise UsageError(f"policy does not exist: {policy_path}")
    validate_paths(source, output, report_dir, local_policy)
    return resolved_commit


def git_archive_extract(source: Path, commit: str, destination: Path) -> None:
    proc = run_command(["git", "archive", "--format=tar", commit], cwd=source)
    require_success(proc, "git archive")
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            validate_tar_member(member)
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if not is_same_or_within(target, destination):
                raise SecurityError(f"archive path escapes destination: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source_file = archive.extractfile(member)
                if source_file is None:
                    raise SecurityError(f"archive member could not be read: {member.name}")
                with source_file, target.open("wb") as target_file:
                    shutil.copyfileobj(source_file, target_file)


def validate_tar_member(member: tarfile.TarInfo) -> None:
    name = member.name.replace("\\", "/")
    if name.startswith("/") or name.startswith("//") or name.startswith("\\\\"):
        raise SecurityError(f"archive contains absolute path: {member.name}")
    if re.match(r"^[A-Za-z]:", name):
        raise SecurityError(f"archive contains Windows drive path: {member.name}")
    parts = [part for part in name.split("/") if part]
    if any(part == ".." for part in parts):
        raise SecurityError(f"archive contains parent traversal: {member.name}")
    if not (member.isfile() or member.isdir()):
        raise SecurityError(f"archive contains unsupported member type: {member.name}")


def match_any(path: str, patterns: Iterable[str]) -> bool:
    rel = normalize_rel(path)
    return any(fnmatch.fnmatchcase(rel, normalize_rel(pattern)) for pattern in patterns)


def allowed_by_policy(path: str, policy: dict[str, Any]) -> bool:
    rel = normalize_rel(path)
    allowed_extensions = set(policy["allowed_extensions"])
    allowed_scripts = {normalize_rel(item) for item in policy.get("allowed_script_paths", [])}
    if rel in allowed_scripts:
        return True
    suffix = Path(rel).suffix
    for pattern in policy["allowed_paths"]:
        normalized_pattern = normalize_rel(pattern)
        has_glob = any(char in normalized_pattern for char in "*?[")
        if has_glob:
            if fnmatch.fnmatchcase(rel, normalized_pattern) and suffix in allowed_extensions:
                return True
        elif rel == normalized_pattern:
            return True
    return False


def legacy_filename(path: str, policy: dict[str, Any]) -> bool:
    name = Path(path).name
    rules = policy["legacy_filename_rules"]
    if legacy_name_only(name):
        return True
    return any(token in name for token in rules.get("unicode_tokens", []))


def denied_by_policy(path: str, policy: dict[str, Any]) -> bool:
    rel = normalize_rel(path)
    if match_any(rel, policy["denied_paths"]):
        return True
    if Path(rel).suffix.lower() in set(policy["denied_extensions"]):
        return True
    return legacy_filename(rel, policy)


def list_commit_files(source: Path, commit: str) -> list[str]:
    proc = run_command(["git", "ls-tree", "-r", "--name-only", commit], cwd=source)
    require_success(proc, "git ls-tree")
    return sorted(normalize_rel(line) for line in proc.stdout.decode("utf-8", errors="replace").splitlines() if line.strip())


def safe_clean_directory(path: Path) -> None:
    resolved = path.resolve()
    if is_root_path(resolved) or is_user_home(resolved):
        raise UsageError("refusing to clean unsafe output path")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def make_work_output_path(output: Path) -> Path:
    return output.resolve().parent / f".{output.name}.tmp-{uuid.uuid4().hex}"


def publish_output(work_output: Path, output: Path) -> None:
    output_resolved = output.resolve()
    backup = output_resolved.parent / f".{output_resolved.name}.backup-{uuid.uuid4().hex}"
    if output_resolved.exists():
        output_resolved.rename(backup)
        try:
            work_output.rename(output_resolved)
        except Exception:
            if output_resolved.exists():
                shutil.rmtree(output_resolved)
            backup.rename(output_resolved)
            raise
        shutil.rmtree(backup)
    else:
        work_output.rename(output_resolved)


def copy_selected_files(extracted: Path, output: Path, selected: list[str]) -> None:
    for rel in selected:
        source_path = extracted / rel
        target_path = output / rel
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_symlink():
            raise SecurityError(f"symbolic links are not allowed in snapshots: {rel}")
        shutil.copy2(source_path, target_path)


def replacement_variants(value: str, replacement: str) -> list[tuple[str, str]]:
    variants = [(value, replacement)]
    if "\\" in value:
        variants.append((value.replace("\\", "/"), replacement))
    if "/" in value and re.match(r"^[A-Za-z]:/", value):
        variants.append((value.replace("/", "\\"), replacement))
    return variants


def safe_redaction_id(old: str, new: str) -> str:
    label = new.strip("<>").lower().replace("_", "-")
    if label:
        return label
    digest = hashlib.sha256(old.encode("utf-8")).hexdigest()[:12]
    return f"literal-{digest}"


def apply_literal_replacements(text: str, local_policy: dict[str, Any], path: str, redactions: list[RedactionRecord]) -> str:
    replacements: list[tuple[str, str]] = []
    for item in local_policy.get("literal_replacements", []):
        raw_from = str(item["from"])
        raw_to = str(item["to"])
        replacements.extend(replacement_variants(raw_from, raw_to))
    replacements.sort(key=lambda pair: len(pair[0]), reverse=True)
    changed_text = text
    for old, new in replacements:
        if not old or old.startswith("<") and old.endswith(">"):
            continue
        flags = re.IGNORECASE if re.match(r"^[A-Za-z]:[\\/]", old) else 0
        pattern = re.escape(old)
        changed_text, count = re.subn(pattern, new, changed_text, flags=flags)
        if count:
            redactions.append(RedactionRecord(path=path, line=0, kind=f"literal_replacement:{safe_redaction_id(old, new)}", changed=True))
    return changed_text


def credential_field(name: str, policy: dict[str, Any]) -> bool:
    upper = name.upper()
    return any(pattern.upper() in upper for pattern in policy["credential_field_patterns"])


def safe_placeholder(value: str, policy: dict[str, Any]) -> bool:
    stripped = value.strip().strip('"').strip("'")
    return any(re.fullmatch(pattern, stripped, flags=re.IGNORECASE) for pattern in policy["safe_placeholder_patterns"])


def credential_prefix(value: str, policy: dict[str, Any]) -> bool:
    stripped = value.strip().strip('"').strip("'")
    return any(stripped.startswith(prefix) for prefix in policy["credential_value_prefixes"])


def dotenv_placeholder(name: str) -> str:
    return f"YOUR_{name.upper()}"


def sanitize_dotenv(text: str, path: str, policy: dict[str, Any], redactions: list[RedactionRecord]) -> str:
    output: list[str] = []
    for index, line in enumerate(text.splitlines(keepends=True), start=1):
        newline = "\n" if line.endswith("\n") else ""
        body = line[:-1] if newline else line
        match = re.match(r"^(\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*)(.*?)(\s*(?:#.*)?)$", body)
        if not match:
            output.append(line)
            continue
        prefix, name, value, comment = match.groups()
        changed = False
        replacement_type = "none"
        if credential_field(name, policy):
            raw_value = value.strip()
            if raw_value == "":
                new_value = ""
            elif credential_prefix(raw_value, policy):
                new_value = dotenv_placeholder(name)
                changed = True
                replacement_type = "credential_prefix_placeholder"
            elif safe_placeholder(raw_value, policy):
                new_value = raw_value.strip('"').strip("'")
            else:
                raise SecurityError(f"real-looking credential value in {path}:{index} for {name}")
            body = f"{prefix}{new_value}{comment}"
        if changed:
            redactions.append(RedactionRecord(path=path, line=index, variable=name, kind=replacement_type, changed=True))
        output.append(body + newline)
    return "".join(output)


def sanitize_path_text(text: str, path: str, redactions: list[RedactionRecord]) -> str:
    rules = [
        (r"(?<![A-Za-z])[A-Za-z]:[\\/](?![\\/])[^\s\"'`]+", "<LOCAL_PROJECT_ROOT>", "windows_absolute_path"),
        (r"/(?:home|root|wyw|mnt)/[^\s\"'`]+", "<REMOTE_PROJECT_ROOT>", "ubuntu_absolute_path"),
    ]
    changed = text
    for pattern, repl, kind in rules:
        changed, count = re.subn(pattern, repl, changed)
        if count:
            redactions.append(RedactionRecord(path=path, line=0, kind=kind, changed=True))
    return changed


def sanitize_prompt_text(text: str, path: str, redactions: list[RedactionRecord]) -> str:
    rules = [
        (r"(?im)^(\s*HostName\s+)\S+", r"\1<REMOTE_HOST>", "ssh_hostname"),
        (r"(?im)^(\s*Host\s+)(?!\*)(\S+)", r"\1<REMOTE_HOST>", "ssh_host"),
        (r"(?im)^(\s*User\s+)\S+", r"\1<REMOTE_USER>", "ssh_user"),
        (r"(?im)^(\s*IdentityFile\s+).+", r"\1<SSH_KEY_PATH>", "ssh_identity_file"),
    ]
    changed = text
    for pattern, repl, kind in rules:
        changed, count = re.subn(pattern, repl, changed)
        if count:
            redactions.append(RedactionRecord(path=path, line=0, kind=kind, changed=True))
    changed = sanitize_path_text(changed, path, redactions)
    changed = sanitize_private_addresses(changed, path, redactions)
    return changed


def sanitizer_for(path: str, policy: dict[str, Any]) -> str | None:
    special = policy.get("special_sanitizers", {})
    for pattern, name in special.items():
        if fnmatch.fnmatchcase(path, normalize_rel(pattern)):
            return str(name)
    return None


def sanitize_file(path: Path, rel: str, policy: dict[str, Any], local_policy: dict[str, Any], redactions: list[RedactionRecord]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SecurityError(f"non-UTF-8 file is not allowed in snapshots: {rel}") from exc
    text = apply_literal_replacements(text, local_policy, rel, redactions)
    sanitizer = sanitizer_for(rel, policy)
    if sanitizer == "prompt_text":
        text = sanitize_prompt_text(text, rel, redactions)
    else:
        text = sanitize_path_text(text, rel, redactions)
        if not fnmatch.fnmatchcase(rel, "requirements*.txt"):
            text = sanitize_private_addresses(text, rel, redactions)
    if sanitizer == "dotenv":
        text = sanitize_dotenv(text, rel, policy, redactions)
    path.write_text(text, encoding="utf-8", newline="")


def looks_like_secret(text: str) -> bool:
    patterns = [
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"ghp_[A-Za-z0-9_]{20,}",
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"sk-[A-Za-z0-9_-]{12,}",
        r"AKIA[0-9A-Z]{16}",
        r"xoxb-[A-Za-z0-9-]{20,}",
        r"hf_[A-Za-z0-9]{20,}",
        r"https?://[^/\s:@]+:[^/\s@]+@",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def is_allowed_public_host(hostname: str, policy: dict[str, Any] | None = None) -> bool:
    allowed = set((policy or {}).get("public_host_allowlist", []))
    if not allowed:
        allowed = {"api.openai.com", "api.siliconflow.cn", "localhost", "127.0.0.1", "0.0.0.0", "example.com", "example.org"}
    normalized_host = hostname.lower().strip(".")
    normalized_allowed = {item.lower().strip(".") for item in allowed}
    return normalized_host in normalized_allowed


def parse_ip_literal(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    candidate = value.strip().strip("[]")
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        return parsed.ipv4_mapped
    return parsed


def is_disallowed_private_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if address.is_loopback or address.is_unspecified:
        return False
    if isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("100.64.0.0/10"):
        return True
    return address.is_private or address.is_link_local


def private_ip_findings_in_line(path: str, line_number: int, line: str) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    patterns = [
        r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])",
        r"\[[0-9A-Fa-f:]+\]",
        r"(?<![0-9A-Fa-f:])(?:[Ff][CcDd][0-9A-Fa-f]{2}|[Ff][Ee]80):[0-9A-Fa-f:]+",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, line):
            parsed = parse_ip_literal(match.group(0))
            if parsed and is_disallowed_private_address(parsed):
                findings.append(SecurityFinding(path=path, line=line_number, rule="private-ip", severity="BLOCKER", summary="private IP after sanitization"))
    return findings


def sanitize_private_addresses(text: str, path: str, redactions: list[RedactionRecord]) -> str:
    changed = text
    patterns = [
        r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])",
        r"\[[0-9A-Fa-f:]+\]",
        r"(?<![0-9A-Fa-f:])(?:[Ff][CcDd][0-9A-Fa-f]{2}|[Ff][Ee]80):[0-9A-Fa-f:]+",
    ]

    def replace(match: re.Match[str]) -> str:
        parsed = parse_ip_literal(match.group(0))
        if parsed and is_disallowed_private_address(parsed):
            return "<PRIVATE_IP>"
        return match.group(0)

    for pattern in patterns:
        changed, count = re.subn(pattern, replace, changed)
        if count and changed != text:
            redactions.append(RedactionRecord(path=path, line=0, kind="private_ip", changed=True))
    return changed


def url_security_findings(path: str, line_number: int, line: str, policy: dict[str, Any] | None = None) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    for match in re.finditer(r"https?://[^\s\"'`<>]+", line):
        raw_url = match.group(0).rstrip(").,;]")
        parsed = urlparse(raw_url)
        hostname = (parsed.hostname or "").lower()
        if parsed.username or parsed.password:
            findings.append(SecurityFinding(path=path, line=line_number, rule="authenticated-url", severity="BLOCKER", summary="URL contains embedded credentials"))
            continue
        query_keys = {key.lower() for key, _value in parse_qsl(parsed.query, keep_blank_values=True)}
        if query_keys & {"token", "access_token", "api_key", "apikey", "key", "secret", "password"}:
            findings.append(SecurityFinding(path=path, line=line_number, rule="url-query-token", severity="BLOCKER", summary="URL query contains credential-like parameter"))
            continue
        parsed_host_ip = parse_ip_literal(hostname)
        if parsed_host_ip and is_disallowed_private_address(parsed_host_ip):
            findings.append(SecurityFinding(path=path, line=line_number, rule="private-ip-url", severity="BLOCKER", summary="URL contains private IP host"))
            continue
        if hostname and not is_allowed_public_host(hostname, policy):
            findings.append(SecurityFinding(path=path, line=line_number, rule="unapproved-url-host", severity="BLOCKER", summary="URL host is not in the public host allowlist"))
    return findings


def suspicious_assignment(line: str) -> bool:
    match = re.match(r"(?i)\s*(?:password|api_key|secret|access_token|token)\s*[:=]\s*['\"]?([^'\"\s#]+)", line)
    if not match:
        return False
    value = match.group(1)
    if re.search(r"(?:os\.)?(?:getenv|environ\.get)\s*\(", line, flags=re.IGNORECASE):
        return False
    if re.match(r"(?i)^(YOUR_|<|\$\{|placeholder|example|redacted|changeme)", value):
        return False
    return True


def scan_text(path: str, text: str, local_policy: dict[str, Any], policy: dict[str, Any] | None = None) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    for index, line in enumerate(text.splitlines(), start=1):
        findings.extend(url_security_findings(path, index, line, policy))
        if looks_like_secret(line) or suspicious_assignment(line):
            findings.append(SecurityFinding(path=path, line=index, rule="sensitive-pattern", severity="BLOCKER", summary="credential-like content after sanitization"))
        if re.search(r"[A-Za-z]:\\Users\\[^\\\s]+", line):
            findings.append(SecurityFinding(path=path, line=index, rule="windows-user-path", severity="BLOCKER", summary="Windows user path after sanitization"))
        if re.search(r"/(?:home|root|wyw)/[A-Za-z0-9._/-]+", line):
            findings.append(SecurityFinding(path=path, line=index, rule="ubuntu-user-path", severity="BLOCKER", summary="Ubuntu user path after sanitization"))
        if not fnmatch.fnmatchcase(path, "requirements*.txt"):
            findings.extend(private_ip_findings_in_line(path, index, line))
        if re.search(r"(?im)^\s*IdentityFile\s+(?!<SSH_KEY_PATH>)\S+", line):
            findings.append(SecurityFinding(path=path, line=index, rule="ssh-identity-file", severity="BLOCKER", summary="real SSH IdentityFile after sanitization"))
        for literal in local_policy.get("forbidden_literals", []):
            literal_text = str(literal)
            if literal_text and not (literal_text.startswith("<") and literal_text.endswith(">")) and literal_text in line:
                findings.append(SecurityFinding(path=path, line=index, rule="forbidden-literal", severity="BLOCKER", summary="local forbidden literal remains after sanitization"))
    return findings


def scan_snapshot(output: Path, local_policy: dict[str, Any], policy: dict[str, Any] | None = None) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    for file_path in sorted(p for p in output.rglob("*") if p.is_file()):
        rel = normalize_rel(str(file_path.relative_to(output)))
        if rel in {"SNAPSHOT_MANIFEST.json"}:
            pass
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise SecurityError(f"non-UTF-8 file is not allowed in snapshots: {rel}") from exc
        findings.extend(scan_text(rel, text, local_policy, policy))
    return findings


def classify_scripts(files: list[str], policy: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    allowed_helpers = {normalize_rel(path) for path in policy.get("allowed_script_paths", [])}
    for rel in sorted(path for path in files if path.startswith("scripts/")):
        name = Path(rel).name
        if legacy_name_only(name):
            category = "LEGACY"
            decision = "EXCLUDE"
            basis = ["filename marks legacy"]
        elif name == "run_video_ui_workflow.py":
            category = "CURRENT_ENTRYPOINT"
            decision = "KEEP"
            basis = ["confirmed current entrypoint"]
        elif rel in allowed_helpers:
            category = "CURRENT_HELPER"
            decision = "KEEP"
            basis = ["explicitly allowed script helper"]
        elif any(token in name.lower() for token in ("download", "real", "machine")):
            category = "DATA_OR_MACHINE_SPECIFIC"
            decision = "EXCLUDE_FIRST_VERSION"
            basis = ["filename suggests data or machine-specific behavior"]
        else:
            category = "UNKNOWN"
            decision = "MANUAL_REVIEW"
            basis = ["not confirmed as current entrypoint or helper"]
        result.append({"path": rel, "classification": category, "snapshot_decision": decision, "basis": basis})
    return result


def legacy_name_only(name: str) -> bool:
    stem = Path(name).stem.lower()
    if "\u65e7" in name:
        return True
    return bool(re.search(r"(^old$|^old[_\-.]|[_\-.]old$|[_\-.]old[_\-.])", stem))

def run_gitleaks_dir(gitleaks_path: Path, output: Path, report_path: Path, require: bool) -> tuple[str, str | None]:
    if not gitleaks_path.exists():
        if require:
            raise SecurityError(f"required gitleaks executable not found: {gitleaks_path}")
        return "NOT_RUN", None
    help_proc = run_command([str(gitleaks_path), "dir", "--help"])
    if help_proc.returncode != 0:
        raise SecurityError("gitleaks dir --help failed")
    version_proc = run_command([str(gitleaks_path), "version"])
    require_success(version_proc, "gitleaks version")
    version = version_proc.stdout.decode("utf-8", errors="replace").strip()
    scan_proc = run_command([
        str(gitleaks_path),
        "dir",
        str(output),
        "--redact=100",
        "--report-format",
        "json",
        "--report-path",
        str(report_path),
    ])
    if scan_proc.returncode == 1:
        raise SecurityError("gitleaks found one or more findings in staging")
    if scan_proc.returncode != 0:
        stderr = scan_proc.stderr.decode("utf-8", errors="replace").strip()
        raise SecurityError(f"gitleaks staging scan failed: {stderr}")
    return "PASS", version


def file_hashes(output: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for file_path in sorted(p for p in output.rglob("*") if p.is_file()):
        rel = normalize_rel(str(file_path.relative_to(output)))
        if rel == "SNAPSHOT_MANIFEST.json":
            continue
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        hashes[rel] = digest
    return dict(sorted(hashes.items()))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_lines(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in sorted(lines)), encoding="utf-8")


def manifest_contains_forbidden(manifest: dict[str, Any], local_policy: dict[str, Any]) -> bool:
    text = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    return any(str(item.get("from", "")) and str(item.get("from", "")) in text for item in local_policy.get("literal_replacements", []))


def create_manifest(
    output: Path,
    result: BuildResult,
    source_commit: str,
    source_branch: str,
    policy_version: str,
) -> dict[str, Any]:
    return {
        "excluded_file_count": len(sorted(set(result.excluded))),
        "file_hashes": file_hashes(output),
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "final_tree_scanned": result.final_tree_scanned,
        "gitleaks_scan_count": result.gitleaks_scan_count,
        "gitleaks_status": result.gitleaks_status,
        "gitleaks_version": result.gitleaks_version,
        "included_file_count": len(result.included) + 1,
        "legacy_file_count": len(sorted(set(result.legacy))),
        "policy_version": policy_version,
        "redaction_count": len(result.redactions),
        "schema_version": 1,
        "source_branch": source_branch,
        "source_commit": source_commit,
        "unknown_file_count": len(result.unknown),
    }


def build_snapshot(args: argparse.Namespace) -> BuildResult:
    source = Path(args.source)
    output = Path(args.output)
    policy_path = Path(args.policy)
    report_dir = Path(args.report_dir)
    local_policy_path = Path(args.local_policy) if args.local_policy else None
    commit = args.commit

    resolved_commit = preflight(source, output, commit, policy_path, report_dir, local_policy_path)
    policy = load_json(policy_path)
    validate_policy(policy)
    local_policy = load_local_policy(local_policy_path)
    max_size = args.max_file_size if args.max_file_size is not None else int(policy["max_file_size_bytes"])

    result = BuildResult()
    all_files = list_commit_files(source, resolved_commit)
    result.scripts_classification = classify_scripts(all_files, policy)

    selected: list[str] = []
    for rel in all_files:
        if denied_by_policy(rel, policy):
            result.excluded.append(rel)
            if legacy_filename(rel, policy):
                result.legacy.append(rel)
            continue
        if allowed_by_policy(rel, policy):
            selected.append(rel)
            result.included.append(rel)
        else:
            result.unknown.append(rel)

    if args.dry_run:
        return result

    report_dir.mkdir(parents=True, exist_ok=True)
    if not args.clean_output and output.exists() and any(output.iterdir()):
        raise UsageError("output already exists and is not empty; use --clean-output")
    output.parent.mkdir(parents=True, exist_ok=True)
    work_output = make_work_output_path(output)
    branch = git_branch(source)
    try:
        safe_clean_directory(work_output)
        with tempfile.TemporaryDirectory(prefix="review-snapshot-") as tmp:
            extracted = Path(tmp) / "archive"
            extracted.mkdir()
            git_archive_extract(source, resolved_commit, extracted)
            for rel in selected:
                source_path = extracted / rel
                if source_path.exists() and source_path.stat().st_size > max_size:
                    result.excluded.append(rel)
                    result.included.remove(rel)
            copy_selected_files(extracted, work_output, result.included)

        for file_path in sorted(p for p in work_output.rglob("*") if p.is_file()):
            rel = normalize_rel(str(file_path.relative_to(work_output)))
            sanitize_file(file_path, rel, policy, local_policy, result.redactions)

        work_output.joinpath("REVIEW_SNAPSHOT_NOTICE.md").write_text(NOTICE_TEXT, encoding="utf-8")
        provisional_manifest = create_manifest(work_output, result, resolved_commit, branch, policy["policy_version"])
        if manifest_contains_forbidden(provisional_manifest, local_policy):
            raise SecurityError("manifest contains a local-policy literal")
        write_json(work_output / "SNAPSHOT_MANIFEST.json", provisional_manifest)

        result.findings.extend(scan_snapshot(work_output, local_policy, policy))
        if result.findings:
            write_reports(report_dir, result, resolved_commit, branch, "FAIL", None)
            raise SecurityError("built-in sensitive content scan failed")

        if args.gitleaks_path:
            status, version = run_gitleaks_dir(Path(args.gitleaks_path), work_output, report_dir / "gitleaks-staging-redacted.json", args.require_gitleaks)
            result.gitleaks_status = status
            result.gitleaks_version = version
            result.gitleaks_scan_count += 1
        elif args.require_gitleaks:
            raise SecurityError("--require-gitleaks was set but --gitleaks-path was not provided")

        # Record the final expected state before either final scan.  The tree
        # that passes these scans must be byte-for-byte identical to the tree
        # that is published, including the manifest itself.
        result.final_tree_scanned = True
        if args.gitleaks_path:
            result.gitleaks_scan_count += 1
        manifest = create_manifest(work_output, result, resolved_commit, branch, policy["policy_version"])
        if manifest_contains_forbidden(manifest, local_policy):
            raise SecurityError("manifest contains a local-policy literal")
        write_json(work_output / "SNAPSHOT_MANIFEST.json", manifest)
        final_findings = scan_snapshot(work_output, local_policy, policy)
        if final_findings:
            result.findings.extend(final_findings)
            write_reports(report_dir, result, resolved_commit, branch, "FAIL", result.gitleaks_version)
            raise SecurityError("final sensitive content scan failed")

        if args.gitleaks_path:
            status, version = run_gitleaks_dir(Path(args.gitleaks_path), work_output, report_dir / "gitleaks-staging-final-redacted.json", args.require_gitleaks)
            result.gitleaks_status = status
            result.gitleaks_version = version
        publish_output(work_output, output)
    except Exception:
        if work_output.exists():
            shutil.rmtree(work_output, ignore_errors=True)
        raise

    write_reports(report_dir, result, resolved_commit, branch, result.gitleaks_status, result.gitleaks_version)
    return result


def write_reports(report_dir: Path, result: BuildResult, commit: str, branch: str, gitleaks_status: str, gitleaks_version: str | None) -> None:
    write_lines(report_dir / "included-files.local.txt", result.included)
    write_lines(report_dir / "excluded-files.local.txt", result.excluded)
    write_lines(report_dir / "unknown-files.local.txt", result.unknown)
    write_lines(report_dir / "legacy-files.local.txt", result.legacy)
    write_json(report_dir / "redactions.local.json", [record.__dict__ for record in result.redactions])
    write_json(report_dir / "security-findings-redacted.local.json", [finding.__dict__ for finding in result.findings])
    write_json(report_dir / "scripts-classification.local.json", result.scripts_classification)
    write_json(report_dir / "snapshot-report.local.json", {
        "excluded_file_count": len(sorted(set(result.excluded))),
        "final_tree_scanned": result.final_tree_scanned,
        "gitleaks_scan_count": result.gitleaks_scan_count,
        "gitleaks_status": gitleaks_status,
        "gitleaks_version": gitleaks_version,
        "included_file_count": len(result.included),
        "legacy_file_count": len(sorted(set(result.legacy))),
        "redaction_count": len(result.redactions),
        "source_branch": branch,
        "source_commit": commit,
        "unknown_file_count": len(result.unknown),
    })


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a sanitized review snapshot.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--local-policy")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--gitleaks-path")
    parser.add_argument("--clean-output", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--require-gitleaks", action="store_true")
    parser.add_argument("--max-file-size", type=int)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        result = build_snapshot(args)
        if args.verbose:
            print(f"included={len(result.included)} excluded={len(result.excluded)} unknown={len(result.unknown)}")
        return EXIT_OK
    except UsageError as exc:
        print(f"usage/path validation failed: {exc}", file=sys.stderr)
        return exc.exit_code
    except SecurityError as exc:
        print(f"security scan failed: {exc}", file=sys.stderr)
        return exc.exit_code
    except SnapshotError as exc:
        print(f"snapshot build failed: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
