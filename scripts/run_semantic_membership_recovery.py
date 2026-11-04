"""Run the authorized 002 recovery over the frozen production archive."""
import argparse
import json
import multiprocessing
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.service.main_model_runtime import MEMBERSHIP_RECOVERY_CANDIDATE, MEMBERSHIP_RECOVERY_CONTROL
from src.service.main_ui_workflow import run_planner_arm, save, sha
from src.utils.coder_execution_input import coder_execution_state
from src.utils.pipeline_trace import PipelineTrace
from src.utils.single_attempt_transport import isolated_sdk_call


SOURCE_SHA = "f554761673ff08e59118d47354831454b6ac70da6af820962c91d273377b90e4"
SOURCE_ROOT = "single_layout_v1_20261104T190519Z_002"
MEMBERS = {
    "vision_output": "upstream/vision_output.json",
    "control_state": "control/architect_output.json",
    "control_coder_request": "control/requests/coder_request.json",
    "control_coder_response": "control/requests/coder_response.json",
    "candidate_architect_request": "candidate/requests/architect_request.json",
    "candidate_architect_response": "candidate/requests/architect_response.json",
    "original_terminal": "terminal.json",
}


def load_source(path):
    if sha(path) != SOURCE_SHA:
        raise ValueError("MEMBERSHIP_RECOVERY_SOURCE_HASH")
    with tarfile.open(path) as archive:
        raw = {name: archive.extractfile(f"{SOURCE_ROOT}/{member}").read() for name, member in MEMBERS.items()}
    frozen = {name: json.loads(blob) for name, blob in raw.items()}
    shared = frozen["vision_output"]
    control = frozen["control_state"]
    coder_input = json.loads(frozen["control_coder_request"]["messages"][1]["content"])
    if (frozen["original_terminal"]["status"] != "PAIR_INCOMPLETE" or not shared["vision_status"]["valid"]
            or any(shared[key] != control[key] for key in ("original_user_request", "asr_transcript", "vision_elements"))
            or coder_execution_state(control["ui_state_json"]) != coder_input["execution"]):
        raise ValueError("MEMBERSHIP_RECOVERY_SOURCE_CONTRACT")
    return raw, frozen


def offline_gate(path):
    _, frozen = load_source(path)
    from src.renderers.region_bundle import render_region_bundle
    bundle = frozen["control_coder_response"]["response"]["choices"][0]["message"]["content"]
    tree = frozen["control_state"]["ui_state_json"]["region_tree"]
    _, validation = render_region_bundle(bundle, tree, bounded_svg_uri=True)
    if not validation["passed"]:
        raise ValueError("MEMBERSHIP_RECOVERY_OFFLINE_REPLAY")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_archive", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if not args.validate_only and (args.output is None or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", args.output.name)):
        parser.error("Provide a new output directory with a short run name")
    worker = multiprocessing.get_context("spawn").Process(target=offline_gate, args=(args.source_archive,))
    worker.start()
    worker.join(60)
    if worker.is_alive():
        worker.terminate()
        worker.join()
        raise RuntimeError("MEMBERSHIP_RECOVERY_SPAWN_TIMEOUT")
    if worker.exitcode:
        raise RuntimeError("MEMBERSHIP_RECOVERY_SPAWN_FAILED")
    if args.validate_only:
        print("Verified the frozen inputs and offline asset replay. Maximum real requests: 3.")
        return 0

    if subprocess.check_output(["git", "status", "--porcelain", "--", "src", "config", str(Path(__file__).relative_to(ROOT))],
                               cwd=ROOT).strip():
        raise ValueError("MEMBERSHIP_RECOVERY_TRACKED_SOURCE_DIRTY")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    config = ROOT / "config/main_ui.json"
    os.environ.update(json.loads(config.read_text(encoding="utf-8"))["environment"])
    os.environ["UI_REGION_PLAN_NORMALIZATION"] = "row_bottom_alias_v1"
    raw, frozen = load_source(args.source_archive)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "frozen").mkdir()
    for name, blob in raw.items():
        (output / "frozen" / f"{name}.json").write_bytes(blob)
    identity = {
        "mode": "semantic_membership_contract_v2", "asset_policy": "bounded_svg_uri_v2", "run_id": output.name,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": SOURCE_SHA, "config_sha256": sha(config), "normalization": "row_bottom_alias_v1",
        "max_physical_requests": 3, "automatic_retries": 0, "max_output_tokens": 8192, "timeout_seconds": 600,
    }
    save(output / "run_identity.json", identity)

    def guarded_dispatch(expected, *, planner=False):
        def dispatch(request, **kwargs):
            if expected is not None and (request["messages"][1:] != expected["messages"][1:]
                    or {key: value for key, value in request.items() if key != "messages"} !=
                    {key: value for key, value in expected.items() if key != "messages"}):
                raise ValueError("MEMBERSHIP_RECOVERY_SERIALIZED_INPUT_MISMATCH")
            marker = "MembershipLayout" if planner else "bounded_svg_uri_v2"
            if marker not in request["messages"][0]["content"]:
                raise ValueError("MEMBERSHIP_RECOVERY_REQUEST_POLICY")
            return isolated_sdk_call(request, **kwargs)
        return dispatch

    def candidate_dispatch(request, **kwargs):
        planner = "MembershipLayout" in request["messages"][0]["content"]
        expected = frozen["candidate_architect_request"] if planner else None
        return guarded_dispatch(expected, planner=planner)(request, **kwargs)

    with PipelineTrace(output / "trace", identity):
        control = run_planner_arm(frozen["control_state"], output / "control", output.name,
                                  MEMBERSHIP_RECOVERY_CONTROL, guarded_dispatch(frozen["control_coder_request"]),
                                  trace_label="semantic_membership.recovery", start_at_coder=True)
        candidate = run_planner_arm(frozen["vision_output"], output / "candidate", output.name,
                                    MEMBERSHIP_RECOVERY_CANDIDATE, candidate_dispatch,
                                    trace_label="semantic_membership.recovery")
    save(output / "summary.json", {"control": control, "candidate": candidate})
    save(output / "artifact_sha256.json", {str(path.relative_to(output)): sha(path)
                                            for path in sorted(output.rglob("*")) if path.is_file()})
    return 0 if all(row.get("html_contract_passed") is True for row in (control, candidate)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
