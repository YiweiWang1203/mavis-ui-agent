"""Run one diagnostic request through the production shadow auditor."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.region_review import audit_region_plan
from src.service.main_model_runtime import MODEL, MainModelRuntime
from src.service.main_ui_workflow import safe_diagnostic, sha
from src.utils.pipeline_trace import PipelineTrace
from src.utils.single_attempt_transport import write_new


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON with plan, segments, vision and original_intent")
    parser.add_argument("output", type=Path, help="A new diagnostic directory")
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"plan", "segments", "vision", "original_intent"}:
        parser.error("Expected plan, segments, vision and original_intent")
    from dotenv import load_dotenv

    config_path = ROOT / "config/main_ui.json"
    environment = json.loads(config_path.read_text(encoding="utf-8"))["environment"]
    policy, renderer = environment["UI_REGION_AUDIT_POLICY"], environment["UI_RENDERER_MODE"]
    if policy != "shadow" or renderer != "region_bundle_v1":
        parser.error("Expected the production region bundle and shadow audit configuration")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "diff", "--name-only", "HEAD", "--", "src", "config",
                                     "scripts/run_region_audit.py"], cwd=ROOT, text=True).splitlines()
    load_dotenv(ROOT / ".env", override=False)
    os.environ["UI_REGION_AUDIT_POLICY"] = policy
    args.output.mkdir(parents=True, exist_ok=False)
    identity = {"profile": "audit1", "audit_policy": policy, "renderer_semantics": renderer, "model": MODEL,
                "commit": commit, "tracked_dirty": dirty, "host": platform.node(), "interpreter": sys.executable,
                "config_sha256": sha(config_path),
                "input_sha256": sha(args.input), "max_requests": 1, "max_output_tokens": 8192,
                "timeout_seconds": 600, "automatic_retries": 0}
    write_new(args.output / "identity.json", identity)
    if dirty:
        write_new(args.output / "failure.json", {"error": "AUDIT_TRACKED_SOURCE_DIRTY"})
        return 1
    with PipelineTrace(args.output / "trace", identity), MainModelRuntime(args.output / "requests", profile="audit1"):
        try:
            result = audit_region_plan(candidate=data["plan"], segments=data["segments"],
                                       vision=data["vision"], original_intent=data["original_intent"],
                                       model=MODEL, stage="semantic_audit")
        except ValueError as error:
            result = {"verdict": "invalid", "issues": [], "diagnostic": str(error)}
        except Exception as error:
            write_new(args.output / "failure.json", safe_diagnostic(error))
            return 1
    write_new(args.output / "result.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
