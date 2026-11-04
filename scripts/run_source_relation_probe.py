"""Compare one frozen production Planner input with and without model-extracted evidence."""
import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.coder import generate_frontend_code
from src.agents.region_review import request_region_review
from src.agents.ui_architect import generate_ui_state
from src.schemas.region_plan import Contract
from src.service.main_model_runtime import MODEL, MainModelRuntime
from src.service.main_ui_workflow import safe_diagnostic, sha
from src.utils.pipeline_trace import PipelineTrace
from src.utils.region_audit_input import observation_content
from src.utils.region_tree import speech_segments
from src.utils.single_attempt_transport import isolated_sdk_call, write_new


FROZEN_FILES = {
    "input_002.json": "99ee539cddfa8a03dac9fb7facafea781ab235853f6c0e6bd47d862491a4522d",
    "source_002_architect_request.json": "cc2014af21998a07cc612f3a3a2c467b011d2e5b15539d82856ac8761b95014c",
}


class SourceRelation(Contract):
    source_id: str
    source_quote: str = Field(min_length=1)
    subject: str | None
    reference: str | None
    frame: str | None
    relation: str | None
    certainty: Literal["explicit", "inferred", "unknown"]


class SourceRelations(Contract):
    relations: list[SourceRelation]


@dataclass(frozen=True)
class FrozenInput:
    request: dict
    intent: str
    locale: str
    vision: dict
    transcript: str
    original_request: str
    numbered: dict


def load_frozen(folder):
    for name, expected in FROZEN_FILES.items():
        if sha(folder / name) != expected:
            raise ValueError("SOURCE_RELATION_FROZEN_HASH_MISMATCH: " + name)
    frozen, request = (json.loads((folder / name).read_text(encoding="utf-8")) for name in FROZEN_FILES)
    text = request["messages"][1]["content"]
    intent, locale_and_vision = text.removeprefix("\n[User Intent]\n").split("\n\n[Preferred Locale]\n", 1)
    locale, vision_and_asr = locale_and_vision.split("\n\n[Vision Elements]\n", 1)
    vision, asr = vision_and_asr.split("\n\nReturn the final fused UI-State JSON.\n\n[Numbered Fresh ASR Segments]\n", 1)
    transcript = frozen["asr_transcript"]
    numbered = {key: segment["text"] for key, segment in speech_segments(transcript).items()}
    if numbered != json.loads(asr):
        raise ValueError("SOURCE_RELATION_FROZEN_ASR_MISMATCH")
    return FrozenInput(request, intent, locale, json.loads(vision), transcript, frozen["original_user_request"], numbered)


def extract_relations(numbered, vision):
    payload = {"asr_segments": numbered, "object_evidence": observation_content(vision)}
    system = (
        "Extract spoken spatial relations from the numbered ASR. Object evidence helps identify referents "
        "but does not specify the requested geometry. For each relation record the exact source segment ID and "
        "verbatim quote, subject, reference object, local or page reference frame, direction or placement, "
        "and certainty. Prefer the named local reference when supported. Mark genuinely unresolved bindings "
        "unknown and use null for unresolved fields. Do not produce layout instructions, tree nodes, geometry, "
        "or a patch. Return one JSON object matching this schema:\n" + json.dumps(SourceRelations.model_json_schema())
    )
    value = request_region_review(MODEL, "source_relation_extract", system, payload)
    SourceRelations.model_validate(value)
    return value


def run_planner(folder, frozen, evidence, dispatch):
    request = frozen.request
    expected = request
    if evidence is not None:
        messages = [*request["messages"]]
        messages[1] = {**messages[1], "content": messages[1]["content"]
                       + "\n\n[Source Relation Evidence]\n" + json.dumps(evidence, ensure_ascii=False)}
        expected = {**request, "messages": messages}

    def checked_dispatch(actual, **kwargs):
        if runtime.used[-1] == "architect" and actual != expected:
            raise RuntimeError("SOURCE_RELATION_PRODUCTION_PLANNER_REQUEST_MISMATCH")
        return dispatch(actual, **kwargs)

    runtime = MainModelRuntime(folder, checked_dispatch, profile="source_relation_arm2")
    return runtime, {
        "user_intent": frozen.intent, "vision_elements": frozen.vision, "preferred_locale": frozen.locale,
        "asr_transcript": frozen.transcript, "source_relation_evidence": evidence,
    }


def run_arm(folder, frozen, evidence, identity):
    folder.mkdir()
    os.environ["MAVIS_MAIN_RUN_ID"] = identity["run_id"] + "_" + folder.name
    runtime, arguments = run_planner(folder / "requests", frozen, evidence, isolated_sdk_call)
    terminal = {"status": "NO_HTML"}
    with PipelineTrace(folder / "trace", identity), runtime:
        try:
            state = generate_ui_state(**arguments)
            if state.get("error"):
                raise ValueError(state["error"])
            write_new(folder / "compiled_ui_state.json", state)
            result = generate_frontend_code(state, original_user_request=frozen.original_request,
                                            asr_transcript=frozen.transcript)
            artifact = folder / "final.html"
            with artifact.open("xb") as stream:
                stream.write(Path(result["file_path"]).read_bytes())
            terminal.update(status="HTML_PENDING_INDEPENDENT_ACCEPTANCE", html_sha256=sha(artifact),
                            renderer=result["renderer"], html_validation=result["html_validation"])
        except Exception as error:
            write_new(folder / "failure.json", safe_diagnostic(error))
    terminal["model_calls"] = runtime.used
    write_new(folder / "terminal.json", terminal)
    return terminal


def verify_offline(frozen):
    def capture(request, **kwargs):
        return {"ok": False, "error_type": "OFFLINE_PREFLIGHT"}

    with TemporaryDirectory() as directory:
        for name, evidence in (("control", None), ("candidate", {"relations": []})):
            runtime, arguments = run_planner(Path(directory) / name, frozen, evidence, capture)
            with runtime:
                state = generate_ui_state(**arguments)
            if state != {"error": "PROVIDER_OFFLINE_PREFLIGHT"} or runtime.used != ["architect"]:
                raise ValueError("SOURCE_RELATION_PREFLIGHT_REQUEST_MISMATCH")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen_folder", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if not args.validate_only and (args.output is None or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", args.output.name)):
        parser.error("Provide a new output directory with a short run name")
    frozen = load_frozen(args.frozen_folder)
    config_path = ROOT / "config/main_ui.json"
    if not args.validate_only:
        if subprocess.check_output(["git", "diff", "--name-only", "HEAD", "--", "src", "config",
                                    "scripts/run_source_relation_probe.py"], cwd=ROOT).strip():
            raise ValueError("SOURCE_RELATION_TRACKED_SOURCE_DIRTY")
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    os.environ.update(json.loads(config_path.read_text(encoding="utf-8"))["environment"])
    verify_offline(frozen)
    if args.validate_only:
        print("Verified exact historical Planner request and candidate suffix. Maximum physical requests: 5.")
        return 0

    args.output.mkdir(parents=True, exist_ok=False)
    identity = {
        "mode": "source_relation_probe_v1", "case": "002", "run_id": args.output.name,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "frozen_files": FROZEN_FILES, "config_sha256": sha(config_path), "model": MODEL,
        "max_physical_requests": 5, "automatic_retries": 0,
    }
    write_new(args.output / "run_identity.json", identity)
    extract = args.output / "extraction"
    extract.mkdir()
    evidence = None
    with MainModelRuntime(extract / "requests", profile="source_relation_extract1") as runtime:
        try:
            evidence = extract_relations(frozen.numbered, frozen.vision)
            write_new(extract / "relations.json", evidence)
        except Exception as error:
            write_new(extract / "failure.json", safe_diagnostic(error))
    extraction = {"status": "EXTRACTED" if evidence is not None else "EXTRACTION_FAILED", "model_calls": runtime.used}
    write_new(extract / "terminal.json", extraction)
    results = {"extraction": extraction, "control": run_arm(args.output / "control", frozen, None, identity)}
    results["candidate"] = (run_arm(args.output / "candidate", frozen, evidence, identity) if evidence is not None
                            else {"status": "BLOCKED_BY_EXTRACTION", "model_calls": []})
    write_new(args.output / "summary.json", results)
    return 0 if all(results[arm]["status"] == "HTML_PENDING_INDEPENDENT_ACCEPTANCE"
                    for arm in ("control", "candidate")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
