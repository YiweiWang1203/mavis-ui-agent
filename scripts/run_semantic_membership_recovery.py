"""Run the authorized recovery over a selected frozen production archive."""
import argparse
import hashlib
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


CASES = {
    "002": {
        "sha": "f554761673ff08e59118d47354831454b6ac70da6af820962c91d273377b90e4",
        "root": "single_layout_v1_20261104T190519Z_002", "recover_control": True,
    },
    "006": {
        "sha": "c1331f49bc4e844ba5dc1e5df9a6bfe87db9353accb51af1d6bd930c742e5adc",
        "root": "single_layout_v1_20261104T190519Z_006", "recover_control": False,
    },
}
MEMBERS = {
    "vision_output": "upstream/vision_output.json",
    "control_state": "control/architect_output.json",
    "control_coder_request": "control/requests/coder_request.json",
    "control_coder_response": "control/requests/coder_response.json",
    "control_architect_request": "control/requests/architect_request.json",
    "candidate_architect_request": "candidate/requests/architect_request.json",
    "candidate_architect_response": "candidate/requests/architect_response.json",
    "original_terminal": "terminal.json",
}


def load_source(path, case_id):
    case = CASES[case_id]
    if sha(path) != case["sha"]:
        raise ValueError("MEMBERSHIP_RECOVERY_SOURCE_HASH")
    with tarfile.open(path) as archive:
        raw = {name: archive.extractfile(f"{case['root']}/{member}").read() for name, member in MEMBERS.items()}
        original_html = (None if case["recover_control"] else
                         archive.extractfile(f"{case['root']}/control/final.html").read())
    frozen = {name: json.loads(blob) for name, blob in raw.items()}
    shared = frozen["vision_output"]
    control = frozen["control_state"]
    coder_input = json.loads(frozen["control_coder_request"]["messages"][1]["content"])
    if (frozen["original_terminal"]["status"] != "PAIR_INCOMPLETE" or not shared["vision_status"]["valid"]
            or any(shared[key] != control[key] for key in ("original_user_request", "asr_transcript", "vision_elements"))
            or coder_execution_state(control["ui_state_json"]) != coder_input["execution"]
            or frozen["control_architect_request"]["messages"][1:] != frozen["candidate_architect_request"]["messages"][1:]):
        raise ValueError("MEMBERSHIP_RECOVERY_SOURCE_CONTRACT")
    if original_html is not None:
        original_control = frozen["original_terminal"]["pair"]["control"]
        if (not original_control["html_generated"] or original_control["html_contract_passed"] is not True
                or hashlib.sha256(original_html).hexdigest() != original_control["html_sha256"]):
            raise ValueError("MEMBERSHIP_RECOVERY_ORIGINAL_CONTROL")
    return raw, frozen, original_html


def offline_gate(path, case_id):
    _, frozen, _ = load_source(path, case_id)
    if not CASES[case_id]["recover_control"]:
        return
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
    parser.add_argument("--case", choices=CASES, default="002")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if not args.validate_only and (args.output is None or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", args.output.name)):
        parser.error("Provide a new output directory with a short run name")
    case = CASES[args.case]
    max_requests = 3 if case["recover_control"] else 2
    worker = multiprocessing.get_context("spawn").Process(target=offline_gate, args=(args.source_archive, args.case))
    worker.start()
    worker.join(60)
    if worker.is_alive():
        worker.terminate()
        worker.join()
        raise RuntimeError("MEMBERSHIP_RECOVERY_SPAWN_TIMEOUT")
    if worker.exitcode:
        raise RuntimeError("MEMBERSHIP_RECOVERY_SPAWN_FAILED")
    if args.validate_only:
        extra = "offline asset replay" if case["recover_control"] else "the preserved original control HTML"
        print(f"Verified case {args.case} frozen inputs and {extra}. Maximum real requests: {max_requests}.")
        return 0

    if subprocess.check_output(["git", "status", "--porcelain", "--", "src", "config", str(Path(__file__).relative_to(ROOT))],
                               cwd=ROOT).strip():
        raise ValueError("MEMBERSHIP_RECOVERY_TRACKED_SOURCE_DIRTY")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    config = ROOT / "config/main_ui.json"
    os.environ.update(json.loads(config.read_text(encoding="utf-8"))["environment"])
    os.environ["UI_REGION_PLAN_NORMALIZATION"] = "row_bottom_alias_v1"
    raw, frozen, original_html = load_source(args.source_archive, args.case)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "frozen").mkdir()
    for name, blob in raw.items():
        (output / "frozen" / f"{name}.json").write_bytes(blob)
    if original_html is not None:
        (output / "frozen" / "original_control.html").write_bytes(original_html)
    identity = {
        "mode": "semantic_membership_contract_v2", "asset_policy": "bounded_svg_uri_v2", "run_id": output.name,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "case": args.case, "source_sha256": case["sha"], "config_sha256": sha(config),
        "normalization": "row_bottom_alias_v1", "max_physical_requests": max_requests,
        "automatic_retries": 0, "max_output_tokens": 8192, "timeout_seconds": 600,
        "comparison_scope": "recovery_only" if case["recover_control"] else "candidate_only_with_historical_control",
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
        if case["recover_control"]:
            control = run_planner_arm(frozen["control_state"], output / "control", output.name,
                                      MEMBERSHIP_RECOVERY_CONTROL, guarded_dispatch(frozen["control_coder_request"]),
                                      trace_label="semantic_membership.recovery", start_at_coder=True)
        else:
            control = {"status": "PRESERVED_HISTORICAL_CONTROL", "model_calls": [],
                       "html_sha256": frozen["original_terminal"]["pair"]["control"]["html_sha256"],
                       "html_path": "frozen/original_control.html"}
        candidate = run_planner_arm(frozen["vision_output"], output / "candidate", output.name,
                                    MEMBERSHIP_RECOVERY_CANDIDATE, candidate_dispatch,
                                    trace_label="semantic_membership.recovery")
    save(output / "summary.json", {"control": control, "candidate": candidate})
    save(output / "artifact_sha256.json", {str(path.relative_to(output)): sha(path)
                                            for path in sorted(output.rglob("*")) if path.is_file()})
    ready = candidate.get("html_contract_passed") is True and (
        not case["recover_control"] or control.get("html_contract_passed") is True
    )
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
