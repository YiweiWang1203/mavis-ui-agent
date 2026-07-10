# Review Snapshot Tools

This directory contains local tooling for producing a sanitized review snapshot
from a committed source tree. The snapshot is intended for external code review,
not for development.

The builder uses `git archive` for the selected commit, safely extracts only
regular files and directories, applies a strict allowlist, then applies deny
rules, deterministic redaction, built-in sensitive content checks, and Gitleaks
directory scans. Gitleaks may be omitted only in isolated unit tests. Formal
sync or release snapshots must use `--require-gitleaks`.

The builder writes into a sibling temporary directory first. Export, redaction,
the notice, the manifest, built-in scans, and Gitleaks scans all complete before
the official output directory is replaced. A failed build leaves no official
staging directory behind, and an older successful output is preserved until the
new one passes.

Unknown files do not automatically enter a snapshot. Directory allowlist entries
still require an explicitly allowed extension, except for exact file allowlist
entries such as `.env.example`.

Reports are written outside the snapshot directory. The local policy file is
also expected to live outside the repository and must not be committed.

Example:

```powershell
python tools/review_snapshot/build_snapshot.py `
  --source "D:\agentworkspace\mavis-ui-agent" `
  --output "D:\agentworkspace\mavis-ui-agent-review-staging" `
  --commit HEAD `
  --policy "tools\review_snapshot\policy.json" `
  --local-policy "D:\agentworkspace\mavis-review-policy.local.json" `
  --report-dir "D:\agentworkspace\mavis-ui-agent-security-audit" `
  --gitleaks-path "C:\Users\27731\tools\gitleaks\gitleaks.exe" `
  --clean-output `
  --require-gitleaks
```

The sync tool copies a passing staging directory into a local sanitized review
repository while preserving the target `.git` directory. Before it removes or
copies anything, it verifies the manifest schema, `gitleaks_status`, complete
file set, required notice file, and SHA-256 hash for every staged file. It never
commits, pushes, pulls, fetches, or contacts a network.
