"""Recover one strict HTML envelope from a frozen direct-video run without model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.service.direct_multimodal_baseline import BOUNDED_CSS_COMPATIBILITY, DIRECT_ASSET_POLICY, HTML_FENCE, save_direct_html
from src.service.main_ui_workflow import save, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--bounded-css-svg", action="store_true",
                        help="Replay a catalog-policy rejection using the bounded CSS SVG compatibility policy")
    args = parser.parse_args()
    source_sha = args.source_sha256.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha) or sha(args.archive) != source_sha:
        raise ValueError("DIRECT_HTML_REPLAY_SOURCE_HASH")
    with tarfile.open(args.archive) as archive:
        records = [name for name in archive.getnames() if name.endswith("/requests/direct_coder_response.json")]
        if len(records) != 1:
            raise ValueError("DIRECT_HTML_REPLAY_SOURCE_REQUEST_COUNT")
        record = records[0]
        root = record.removesuffix("/requests/direct_coder_response.json")
        raw_response = archive.extractfile(record).read()
        raw_terminal = archive.extractfile(root + "/terminal.json").read()
    terminal = json.loads(raw_terminal)
    packet = json.loads(raw_response)
    source_profile = (terminal.get("asset_policy") == DIRECT_ASSET_POLICY if args.bounded_css_svg else
                      terminal.get("config", {}).get("runtime_profile") == "direct_multimodal_baseline_v1")
    if (terminal["status"] != "FAILED_NO_RETRY" or terminal["html_generated"]
            or terminal["model_calls"] != ["direct_coder"]
            or not source_profile
            or not packet.get("ok") or len(packet["response"]["choices"]) != 1):
        raise ValueError("DIRECT_HTML_REPLAY_SOURCE_TERMINAL")
    choice = packet["response"]["choices"][0]
    raw = choice["message"]["content"]
    if not isinstance(raw, str) or not HTML_FENCE.fullmatch(raw):
        raise ValueError("DIRECT_HTML_REPLAY_REQUIRES_SINGLE_FENCE")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "original_response.json").write_bytes(raw_response)
    (output / "original_terminal.json").write_bytes(raw_terminal)
    result = save_direct_html(raw, choice["finish_reason"], output, allow_bounded_css_svg=args.bounded_css_svg)
    result.update({
        "recovery_version": BOUNDED_CSS_COMPATIBILITY if args.bounded_css_svg else "direct_html_envelope_recovery_v1",
        "source_archive_sha256": source_sha, "original_status": terminal["status"],
        "original_html_generated": terminal["html_generated"], "raw_reply_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "model_calls": [], "physical_requests": 0, "browser_acceptance": "NOT_EXECUTED",
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    })
    save(output / "terminal.json", result)
    save(output / "artifact_sha256.json", {path.name: sha(path) for path in sorted(output.iterdir())})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
