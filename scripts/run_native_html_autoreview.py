"""Audit the frozen initial native page with one production review request."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.service.direct_multimodal_baseline import HTML_FENCE, expand_catalog_icons, require_complete_html
from src.service.main_model_runtime import NATIVE_HTML_AUTOREVIEW_PROFILE, NATIVE_HTML_RELATION_AUDIT_PROFILE, MainModelRuntime
from src.service.main_ui_workflow import safe_diagnostic, save, sha
from src.service.native_html_autoreview import run_native_html_autoreview
from src.utils.pipeline_trace import PipelineTrace


MODEL_ARCHIVE_SHA = "9035052708a08d91f5eee2175dfae378551bd14f04b77c0881735ee31bc13f74"
BROWSER_ARCHIVE_SHA = "901c28f49ee9b96b3e07b248a0826beb4a455eb49f65ed31243d14245f167495"
SCREENSHOT_SHA = "dbd09a13fe4bd0711fc7e3c1206e955d5e10e3cd22083c69b83ff30285f1cf75"
MODEL_HTML_SHA = "e0192e8fe9866d2ec6c5637450f429af7ff44799ac9fd9a1ac6efa90dce859e1"
BROWSER_HTML_SHA = "3dc8e538ac0bbf68a04e6b34521586273d063976478210cae3f3831619f2b2f3"


def load_frozen(model_archive, browser_archive, screenshot_path):
    if (sha(model_archive), sha(browser_archive), sha(screenshot_path)) != (
            MODEL_ARCHIVE_SHA, BROWSER_ARCHIVE_SHA, SCREENSHOT_SHA):
        raise ValueError("NATIVE_AUTOREVIEW_FROZEN_INPUT_HASH")
    with tarfile.open(model_archive) as archive:
        root = "outputs/direct_icon_006_20261104T195102Z/requests"
        request, response = (archive.extractfile(f"{root}/direct_coder_{kind}.json").read()
                             for kind in ("request", "response"))
    with tarfile.open(browser_archive) as archive:
        browser_html = archive.extractfile("direct_icon_006_20261104T195102Z_svg_replay/final.html").read()
    choice, = json.loads(response)["response"]["choices"]
    envelope = HTML_FENCE.fullmatch(choice["message"]["content"])
    if choice["finish_reason"] != "stop" or envelope is None:
        raise ValueError("NATIVE_AUTOREVIEW_FROZEN_RESPONSE")
    html = envelope["html"]
    require_complete_html(html)
    expanded, _ = expand_catalog_icons(html, allow_bounded_css_svg=True)
    if (hashlib.sha256(html.encode("utf-8")).hexdigest() != MODEL_HTML_SHA
            or hashlib.sha256(browser_html).hexdigest() != BROWSER_HTML_SHA
            or expanded.encode("utf-8") != browser_html):
        raise ValueError("NATIVE_AUTOREVIEW_FROZEN_HTML_IDENTITY")
    return request, html, screenshot_path.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_archive", type=Path)
    parser.add_argument("browser_archive", type=Path)
    parser.add_argument("initial_screenshot", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--relation-audit", action="store_true")
    args = parser.parse_args()
    request, html, screenshot = load_frozen(args.model_archive, args.browser_archive, args.initial_screenshot)
    if args.validate_only:
        print("Verified the initial model HTML, browser page and screenshot. Maximum real requests: 1.")
        return 0
    if args.output is None:
        parser.error("Provide a new output directory")
    if subprocess.check_output(["git", "status", "--porcelain", "--", "src", "config",
                                str(Path(__file__).relative_to(ROOT))], cwd=ROOT).strip():
        raise ValueError("NATIVE_AUTOREVIEW_SOURCE_DIRTY")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "initial_request.json").write_bytes(request)
    (output / "initial_model.html").write_bytes(html.encode("utf-8"))
    (output / "initial_screenshot.jpg").write_bytes(screenshot)
    profile = NATIVE_HTML_RELATION_AUDIT_PROFILE if args.relation_audit else NATIVE_HTML_AUTOREVIEW_PROFILE
    identity = {
        "mode": profile, "initial_model_archive_sha256": MODEL_ARCHIVE_SHA,
        "initial_browser_archive_sha256": BROWSER_ARCHIVE_SHA, "initial_browser_sha256": BROWSER_HTML_SHA,
        "initial_model_html_sha256": MODEL_HTML_SHA, "initial_screenshot_sha256": SCREENSHOT_SHA,
        "max_physical_requests": 1, "max_output_tokens": 8192, "timeout_seconds": 600, "automatic_retries": 0,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    }
    save(output / "run_identity.json", identity)
    terminal = {**identity, "status": "FAILED_NO_RETRY"}
    with PipelineTrace(output / "trace", identity), MainModelRuntime(
            output / "requests", profile=profile) as runtime:
        try:
            review = run_native_html_autoreview(json.loads(request), html, screenshot, relation_audit=args.relation_audit)
            save(output / "review.json", review)
            terminal.update(status="REVIEW_READY_FOR_INDEPENDENT_ASSESSMENT", issue_count=len(review["issues"]))
        except Exception as error:
            save(output / "failure_diagnostic.json", safe_diagnostic(error))
        terminal["model_calls"] = list(runtime.used)
    for name in ("request", "response"):
        artifact = output / "requests" / f"native_html_review_{name}.json"
        if artifact.is_file():
            terminal[name + "_sha256"] = sha(artifact)
    save(output / "terminal.json", terminal)
    save(output / "artifact_sha256.json", {str(path.relative_to(output)): sha(path)
                                            for path in sorted(output.rglob("*")) if path.is_file()})
    return 0 if "issue_count" in terminal else 1


if __name__ == "__main__":
    raise SystemExit(main())
