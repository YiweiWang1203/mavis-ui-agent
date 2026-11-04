"""Run the frozen 006 native HTML localized repair with one production request."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.service.direct_multimodal_baseline import (
    BOUNDED_CSS_COMPATIBILITY, HTML_FENCE, expand_catalog_icons, require_complete_html,
)
from src.service.main_model_runtime import DIRECT_MULTIMODAL_PROFILE, MainModelRuntime
from src.service.main_ui_workflow import safe_diagnostic, save, sha
from src.service.native_html_localized_repair import NATIVE_HTML_REPAIR, run_native_html_localized_repair
from src.utils.pipeline_trace import PipelineTrace


MODEL_ARCHIVE_SHA = "9035052708a08d91f5eee2175dfae378551bd14f04b77c0881735ee31bc13f74"
BROWSER_ARCHIVE_SHA = "901c28f49ee9b96b3e07b248a0826beb4a455eb49f65ed31243d14245f167495"
BROWSER_HTML_SHA = "3dc8e538ac0bbf68a04e6b34521586273d063976478210cae3f3831619f2b2f3"
FEEDBACK = {
    "source": "Human independent browser acceptance of the supplied 006 initial page",
    "viewport_css_pixels": [391, 844],
    "target": "L1",
    "asr_excerpt": "然后右边写上price price的，下方就是美金。",
    "observed": {
        "region": "The price area beside the product name",
        "amount": {"text": "$12.99", "y_range_css_pixels": [289.47, 310.80]},
        "label": {"text": "Price", "y_range_css_pixels": [310.80, 328.93]},
        "document_order": ["$12.99", "Price"],
    },
    "expected": "Inside the same local price area, the amount is visibly below the Price label.",
    "preserve": [
        "Centered Details title and visible Back and More controls and icons",
        "Product name, descriptive text and all four visible nutrition cards",
        "All existing text and controls; no new overlap, obscuring elements or increased clipping",
    ],
}


def load_frozen(model_archive, browser_archive):
    if sha(model_archive) != MODEL_ARCHIVE_SHA or sha(browser_archive) != BROWSER_ARCHIVE_SHA:
        raise ValueError("NATIVE_REPAIR_FROZEN_ARCHIVE_HASH")
    with tarfile.open(model_archive) as archive:
        request, response = (archive.extractfile(f"outputs/direct_icon_006_20261104T195102Z/requests/direct_coder_{kind}.json").read()
                             for kind in ("request", "response"))
    with tarfile.open(browser_archive) as archive:
        terminal, browser_html = (archive.extractfile(f"direct_icon_006_20261104T195102Z_svg_replay/{name}").read()
                                  for name in ("terminal.json", "final.html"))
    state = json.loads(terminal)
    choice, = json.loads(response)["response"]["choices"]
    envelope = HTML_FENCE.fullmatch(choice["message"]["content"])
    if (choice["finish_reason"] != "stop" or envelope is None or state["asset_compatibility"] != BOUNDED_CSS_COMPATIBILITY
            or state["html_sha256"] != BROWSER_HTML_SHA or hashlib.sha256(browser_html).hexdigest() != BROWSER_HTML_SHA):
        raise ValueError("NATIVE_REPAIR_FROZEN_HTML_IDENTITY")
    html = envelope["html"]
    require_complete_html(html)
    expanded, _ = expand_catalog_icons(html, allow_bounded_css_svg=True)
    if expanded.encode("utf-8") != browser_html:
        raise ValueError("NATIVE_REPAIR_BROWSER_HTML_MISMATCH")
    asr = json.loads(json.loads(request)["messages"][1]["content"][0]["text"])["asr_transcript"]
    if FEEDBACK["asr_excerpt"] not in asr:
        raise ValueError("NATIVE_REPAIR_FEEDBACK_SOURCE_MISMATCH")
    return request, response, terminal, browser_html, html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_archive", type=Path)
    parser.add_argument("browser_archive", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    request, response, replay_terminal, browser_html, html = load_frozen(args.model_archive, args.browser_archive)
    if args.validate_only:
        print("Verified frozen model HTML, byte-identical browser page and feedback source. Maximum real requests: 1.")
        return 0
    if args.output is None:
        parser.error("Provide a new output directory")
    if subprocess.check_output(["git", "status", "--porcelain", "--", "src", "config",
                                str(Path(__file__).relative_to(ROOT))], cwd=ROOT).strip():
        raise ValueError("NATIVE_REPAIR_SOURCE_DIRTY")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name, blob in {
        "initial_request.json": request, "initial_response.json": response, "initial_replay_terminal.json": replay_terminal,
        "initial_browser.html": browser_html, "initial_model.html": html.encode("utf-8"),
    }.items():
        (output / name).write_bytes(blob)
    save(output / "human_browser_feedback.json", FEEDBACK)
    identity = {
        "mode": NATIVE_HTML_REPAIR, "initial_model_archive_sha256": MODEL_ARCHIVE_SHA,
        "initial_browser_archive_sha256": BROWSER_ARCHIVE_SHA, "initial_browser_sha256": BROWSER_HTML_SHA,
        "initial_model_html_sha256": sha(output / "initial_model.html"),
        "max_physical_requests": 1, "max_output_tokens": 8192, "timeout_seconds": 600, "automatic_retries": 0,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    }
    save(output / "run_identity.json", identity)
    terminal = {**identity, "status": "FAILED_NO_RETRY", "html_generated": False, "browser_acceptance": "NOT_EXECUTED"}
    with PipelineTrace(output / "trace", identity), MainModelRuntime(
            output / "requests", profile=DIRECT_MULTIMODAL_PROFILE) as runtime:
        try:
            terminal.update(run_native_html_localized_repair(json.loads(request), html, FEEDBACK, output))
        except Exception as error:
            save(output / "failure_diagnostic.json", safe_diagnostic(error))
        terminal["model_calls"] = list(runtime.used)
    save(output / "terminal.json", terminal)
    save(output / "artifact_sha256.json", {str(path.relative_to(output)): sha(path)
                                            for path in sorted(output.rglob("*")) if path.is_file()})
    return 0 if terminal["html_generated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
