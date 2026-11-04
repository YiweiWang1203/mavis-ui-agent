"""Recover the frozen source-binding run without replaying video, Vision or extraction."""
import argparse
import json
import multiprocessing
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.coder import generate_frontend_code
from src.service.main_model_runtime import MainModelRuntime, SOURCE_BINDING_RECOVERY_PROFILE
from src.service.main_ui_workflow import run_source_binding_arm, safe_diagnostic, save, sha
from src.service.source_relations import SourceRelations, bind_relations, keyed_relations
from src.utils.pipeline_trace import PipelineTrace
from src.utils.region_tree import compile_region_tree, speech_segments


SOURCE_SHA = "10aeb1f18e52c6853915bebe67d409a742915100ec6b09aa27c3586cc96c2df7"
SOURCE_ROOT = "outputs/source_binding_e2e_v1_20261104182505Z/"
MEMBERS = {
    "vision_output.json": "upstream/vision_output.json",
    "relations.json": "upstream/relations.json",
    "original_binder_request.json": "upstream/requests/source_relation_bind_request.json",
    "original_binder_response.json": "upstream/requests/source_relation_bind_response.json",
    "original_binder_failure.json": "upstream/source_relation_bind_failure.json",
    "original_control_planner_request.json": "control/requests/architect_request.json",
    "original_control_planner_response.json": "control/requests/architect_response.json",
    "original_terminal.json": "terminal.json",
}


def load_source(path):
    if sha(path) != SOURCE_SHA:
        raise ValueError("BINDING_RECOVERY_SOURCE_HASH_MISMATCH")
    with tarfile.open(path) as archive:
        raw = {name: archive.extractfile(SOURCE_ROOT + member).read() for name, member in MEMBERS.items()}
    values = {name: json.loads(blob.decode("utf-8", "strict")) for name, blob in raw.items()}
    shared = values["vision_output.json"]
    relations = values["relations.json"]
    SourceRelations.model_validate(relations)
    transcript = shared["asr_transcript"]
    segments = speech_segments(transcript)
    numbered = {key: row["text"] for key, row in segments.items()}
    binder_payload = json.loads(values["original_binder_request.json"]["messages"][1]["content"])
    if binder_payload["relation_records"] != relations or binder_payload["asr_segments"] != numbered:
        raise ValueError("BINDING_RECOVERY_SOURCE_REQUEST_MISMATCH")
    control = json.loads(values["original_control_planner_response.json"]["response"]["choices"][0]["message"]["content"])
    if not shared["vision_status"]["valid"] or values["original_terminal.json"]["status"] != "PAIR_INCOMPLETE":
        raise ValueError("BINDING_RECOVERY_SOURCE_STATUS_MISMATCH")
    return raw, shared, relations, control, segments, numbered


def configure():
    config = json.loads((ROOT / "config/main_ui.json").read_text(encoding="utf-8"))
    os.environ.update(config["environment"])
    os.environ["UI_REGION_PLAN_NORMALIZATION"] = "row_bottom_alias_v1"


def preflight(path):
    configure()
    _, _, relations, control, segments, _ = load_source(path)
    keys = keyed_relations(relations)
    if list(keys.values()) != relations["relations"]:
        raise ValueError("BINDING_RECOVERY_RELATION_IDENTITY_MISMATCH")
    compile_region_tree(control, segments, schema_version=2)


def recover_control(folder, run_id, shared, control, segments):
    folder.mkdir()
    os.environ["MAVIS_MAIN_RUN_ID"] = run_id + "_control"
    status = {"status": "NO_HTML", "model_calls": []}
    with MainModelRuntime(folder / "requests", profile="repair_probe_control1") as runtime:
        try:
            save(folder / "raw_plan.json", control)
            compiled = compile_region_tree(control, segments, schema_version=2)
            save(folder / "compiled_ui_state.json", compiled)
            result = generate_frontend_code(compiled, original_user_request=shared["original_user_request"],
                                            asr_transcript=shared["asr_transcript"])
            artifact = folder / "final.html"
            with Path(result["file_path"]).open("rb") as source, artifact.open("xb") as target:
                shutil.copyfileobj(source, target)
            status.update(status="HTML_GENERATED_PENDING_BROWSER_ACCEPTANCE", html_sha256=sha(artifact),
                          html_validation=result["html_validation"])
        except Exception as error:
            save(folder / "failure.json", safe_diagnostic(error))
        status["model_calls"] = list(runtime.used)
    save(folder / "terminal.json", status)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_archive", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if not args.validate_only and (args.output is None or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", args.output.name)):
        parser.error("Provide a new output directory with a short run name")
    worker = multiprocessing.get_context("spawn").Process(target=preflight, args=(args.source_archive,))
    worker.start()
    worker.join(60)
    if worker.is_alive():
        worker.terminate()
        worker.join()
        raise RuntimeError("BINDING_RECOVERY_SPAWN_PREFLIGHT_TIMEOUT")
    if worker.exitcode:
        raise RuntimeError("BINDING_RECOVERY_SPAWN_PREFLIGHT_FAILED")
    if args.validate_only:
        print("Frozen archive, keyed relations, control compiler and spawn preflight verified. Maximum requests: 4.")
        return 0

    if subprocess.check_output(["git", "diff", "--name-only", "HEAD", "--", "src", "config",
                                "scripts/run_binding_identity_recovery.py"], cwd=ROOT).strip():
        raise ValueError("BINDING_RECOVERY_TRACKED_SOURCE_DIRTY")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    configure()
    raw, shared, relations, control, segments, numbered = load_source(args.source_archive)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    frozen = output / "frozen"
    frozen.mkdir()
    for name, blob in raw.items():
        with (frozen / name).open("xb") as stream:
            stream.write(blob)
    identity = {"mode": "binding_identity_recovery_v1", "run_id": args.output.name,
                "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "source_sha256": SOURCE_SHA, "config_sha256": sha(ROOT / "config/main_ui.json"),
                "normalization": "row_bottom_alias_v1", "max_physical_requests": 4, "automatic_retries": 0}
    save(output / "run_identity.json", identity)
    binder = output / "binder"
    binder.mkdir()
    binding = None
    with PipelineTrace(output / "trace", identity):
        save(binder / "relation_keys.json", keyed_relations(relations))
        with MainModelRuntime(binder / "requests", profile=SOURCE_BINDING_RECOVERY_PROFILE) as runtime:
            try:
                binding = bind_relations(relations, numbered, shared["vision_elements"])
                save(binder / "binding.json", binding)
            except Exception as error:
                save(binder / "failure.json", safe_diagnostic(error))
        binder_status = {"status": "RETURNED_NOT_SEMANTIC_ACCEPTANCE" if binding is not None else "FAILED",
                         "model_calls": list(runtime.used)}
        save(binder / "terminal.json", binder_status)
        control_status = recover_control(output / "control", args.output.name, shared, control, segments)
        candidate = run_source_binding_arm(shared, output / "candidate", args.output.name,
                                           relations if binding is not None else None, binding)
    save(output / "summary.json", {"binder": binder_status, "control": control_status, "candidate": candidate})
    save(output / "artifact_sha256.json", {str(path.relative_to(output)): sha(path)
                                            for path in sorted(output.rglob("*")) if path.is_file()})
    return 0 if all(row["status"] == "HTML_GENERATED_PENDING_BROWSER_ACCEPTANCE"
                    for row in (control_status, candidate)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
