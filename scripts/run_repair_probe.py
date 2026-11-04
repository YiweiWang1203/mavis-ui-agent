"""Compare frozen-plan and source-grounded repair branches through the shared Coder."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.coder import generate_frontend_code
from src.agents.region_review import Review, repair_region_plan
from src.service.main_model_runtime import MODEL, MainModelRuntime
from src.service.main_ui_workflow import safe_diagnostic, sha
from src.utils.pipeline_trace import PipelineTrace
from src.utils.region_audit_input import plan_references
from src.utils.region_tree import compile_region_tree, speech_segments
from src.utils.single_attempt_transport import write_new


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_cases(manifest_path):
    manifest = read_json(manifest_path)
    source_manifest_path = manifest_path.with_name("repair_probe_v1_frozen_pair.json")
    source_manifest = read_json(source_manifest_path)
    entries = manifest["cases"]
    if not 1 <= len(entries) <= 2 or {entry["name"] for entry in entries} != source_manifest.keys():
        raise ValueError("PROBE_REQUIRES_ONE_OR_TWO_CASES")
    cases = {}
    for entry in entries:
        name = entry["name"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name) or name in cases:
            raise ValueError("INVALID_OR_DUPLICATE_PROBE_CASE")
        data_path = manifest_path.parent / entry["input"]
        feedback_path = manifest_path.parent / entry["feedback"]
        if sha(data_path) != entry["input_sha256"] or sha(feedback_path) != entry["feedback_sha256"]:
            raise ValueError("PROBE_FROZEN_INPUT_HASH_MISMATCH")
        data, feedback = read_json(data_path), read_json(feedback_path)
        source = source_manifest[name]
        artifacts = source["artifacts"]
        parsed = manifest_path.parent / f"source_{name}_parsed.json"
        planner_request = manifest_path.parent / f"source_{name}_architect_request.json"
        original_feedback = manifest_path.parent / f"source_{name}_feedback.txt"
        if (entry["source_run_id"] != source["run_id"] or entry["source_commit"] != source["source_commit"]
                or entry["source_archive_sha256"] != source["archive_sha256"]
                or sha(parsed) != artifacts["031_architect_model_parsed.json"]["sha256"]
                or sha(planner_request) != artifacts["/architect_request.json"]["sha256"]
                or sha(original_feedback) != source["feedback_sha256"]):
            raise ValueError("PROBE_SOURCE_MANIFEST_MISMATCH")
        messages = read_json(planner_request)["messages"]
        if (read_json(parsed)["output"] != data["plan"] or messages[0]["content"] != data["planner_system"]
                or messages[1]["content"] != data["planner_content"]
                or hashlib.sha256(data["asr_transcript"].encode()).hexdigest()
                != artifacts["/asr/transcript.txt"]["sha256"]):
            raise ValueError("PROBE_SOURCE_PLAN_OR_REQUEST_MISMATCH")
        segments = speech_segments(data["asr_transcript"])
        compile_region_tree(data["plan"], segments, schema_version=2)
        review = Review.model_validate({"verdict": "revise", "issues": [feedback["issue"]]}).model_dump()
        issue = review["issues"][0]
        quote = feedback["quote"]
        if (issue["certainty"] != "error" or len(issue["sources"]) != 1 or not quote
                or quote not in segments[issue["sources"][0]]["text"]):
            raise ValueError("PROBE_FEEDBACK_REQUIRES_VERBATIM_SOURCE")
        ref = plan_references(data["plan"])[issue["plan_ref"]]
        if (ref["path"] != feedback["plan_path"] or ref["value"]["id"] != source["target"]
                or ref["path"] != source.get("target_path", ref["path"])):
            raise ValueError("PROBE_FEEDBACK_REFERENCE_MISMATCH")
        issue["expected_relation"] += f' Verbatim ASR ({issue["sources"][0]}): {quote}'
        issue["plan_path"] = ref["path"]
        cases[name] = (data, segments, review)
    return manifest, sha(source_manifest_path), cases


def run_branch(folder, name, branch, data, segments, review, identity, dispatch=None):
    folder.mkdir(parents=True, exist_ok=False)
    profile = "repair_probe_feedback2" if branch == "feedback" else "repair_probe_control1"
    terminal = {"branch": branch, "profile": profile, "status": "NO_HTML", "model_calls": []}
    write_new(folder / "initial_plan.json", data["plan"])
    if branch == "feedback":
        write_new(folder / "supplied_review.json", review)
    os.environ["MAVIS_MAIN_RUN_ID"] = f"{identity['run_id']}_{name}_{branch}"
    with PipelineTrace(folder / "trace", identity), MainModelRuntime(folder / "requests", dispatch,
                                                                      profile=profile) as runtime:
        try:
            selected = data["plan"]
            if branch == "feedback":
                selected = repair_region_plan(selected, [], MODEL, data["planner_system"],
                                              data["planner_content"], review=review)
            write_new(folder / "selected_plan.json", selected)
            state = compile_region_tree(selected, segments, schema_version=2)
            write_new(folder / "compiled_ui_state.json", state)
            result = generate_frontend_code(state, original_user_request=data["original_user_request"],
                                            asr_transcript=data["asr_transcript"])
            saved = Path(result["file_path"])
            if saved.read_text(encoding="utf-8") != result["code"]:
                raise ValueError("PROBE_CODER_PERSISTENCE_MISMATCH")
            artifact = folder / "final.html"
            with artifact.open("xb") as stream:
                stream.write(saved.read_bytes())
            terminal.update(status="HTML_PENDING_INDEPENDENT_ACCEPTANCE", html_sha256=sha(artifact),
                            renderer=result["renderer"], html_validation=result["html_validation"])
        except Exception as error:
            write_new(folder / "failure.json", safe_diagnostic(error))
        finally:
            terminal["model_calls"] = list(runtime.used)
            write_new(folder / "terminal.json", terminal)
    return terminal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    manifest, source_manifest_sha256, cases = load_cases(args.manifest)
    if args.validate_only:
        print(json.dumps({"cases": list(cases), "max_physical_requests": 3 * len(cases)}))
        return 0
    if args.output is None or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", args.output.name):
        parser.error("Provide a new output directory with a short, alphanumeric run name")
    dirty = subprocess.check_output(["git", "diff", "--name-only", "HEAD", "--", "src", "config",
                                     "scripts/run_repair_probe.py"], cwd=ROOT, text=True).splitlines()
    if dirty:
        raise RuntimeError("PROBE_TRACKED_SOURCE_DIRTY")
    from dotenv import load_dotenv

    config_path = ROOT / "config/main_ui.json"
    config = read_json(config_path)
    if config["environment"]["UI_RENDERER_MODE"] != "region_bundle_v1":
        raise ValueError("PROBE_REQUIRES_PRODUCTION_BUNDLE_RENDERER")
    load_dotenv(ROOT / ".env", override=False)
    os.environ.update(config["environment"])
    args.output.mkdir(parents=True, exist_ok=False)
    identity = {
        "mode": "repair_probe_v1_frozen_plan_diagnostic", "run_id": args.output.name,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "host": platform.node(), "interpreter": sys.executable, "model": MODEL,
        "config_sha256": sha(config_path), "manifest_sha256": sha(args.manifest), "manifest": manifest,
        "source_manifest_sha256": source_manifest_sha256,
        "max_physical_requests": 3 * len(cases), "max_output_tokens": 8192,
        "timeout_seconds": 600, "automatic_retries": 0,
        "vision_asr_and_initial_planner": "FROZEN_ARCHIVE_INPUT_NOT_EXECUTED",
    }
    write_new(args.output / "run_identity.json", identity)
    results = {}
    for name, (data, segments, review) in cases.items():
        results[name] = {}
        for branch in ("control", "feedback"):
            results[name][branch] = run_branch(args.output / name / branch, name, branch, data,
                                               segments, review, identity)
    write_new(args.output / "summary.json", results)
    return 0 if all(x["status"] == "HTML_PENDING_INDEPENDENT_ACCEPTANCE"
                    for pair in results.values() for x in pair.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
