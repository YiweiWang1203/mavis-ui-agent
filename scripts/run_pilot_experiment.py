"""One case/condition per invocation; no batch jobs and no hidden modality inputs.

Existing structured pipeline: native vision extraction -> UI architect -> LLM coder.
All remote stages and direct generation use the explicitly selected same model.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_inputs(case_dir, condition):
    """Read only condition-allowed assets; M0 never opens image/transcript."""
    manifest = json.loads((case_dir / "case.json").read_text(encoding="utf-8-sig"))
    def asset(key):
        path = (case_dir / manifest[key]).resolve()
        if not path.is_relative_to(case_dir.resolve()):
            raise ValueError("case asset must stay within case directory")
        return path
    prompt_path = asset("prompt")
    inputs = {"prompt": prompt_path.read_text(encoding="utf-8-sig"),
              "files": {"prompt": prompt_path}, "transcript_source": "none"}
    if condition != "M0":
        inputs["image"] = asset("image")
        inputs["files"]["image"] = inputs["image"]
        if not inputs["image"].is_file():
            raise ValueError("image missing")
    if condition in {"M2", "direct"}:
        source = manifest.get("transcript_source")
        if source not in {"funasr", "manual_diagnostic"}:
            raise ValueError("transcript_source must be funasr or manual_diagnostic")
        path = asset("transcript")
        inputs.update(transcript=path.read_text(encoding="utf-8-sig"), transcript_source=source)
        inputs["files"]["transcript"] = path
        if not inputs["transcript"].strip() or "[mock transcript]" in inputs["transcript"]:
            raise ValueError("empty/mock transcript is not an experimental input")
    return inputs


def safe_messages(messages):
    # Image bytes are separately retained; keep requests compact.
    text = json.dumps(messages, ensure_ascii=False)
    return json.loads(re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', "[retained in input image/effective_image.jpg]", text))


class TracedClient:
    def __init__(self, client, output):
        self.client, self.output, self.calls = client, output, []
        self.stage = "unknown"
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        index = len(self.calls) + 1
        record = {"index": index, "stage": self.stage, "model": kwargs["model"],
                  "started_utc": datetime.now(timezone.utc).isoformat(),
                  "request": {**kwargs, "messages": safe_messages(kwargs["messages"])}}
        self.calls.append(record)
        start = time.monotonic()
        try:
            response = self.client.chat.completions.create(**kwargs)
            record["response"] = response.model_dump()
            record["status"] = "returned"
            return response
        except Exception as exc:
            # Provider exceptions can include headers/credentials; retain only type/status.
            record.update(status="failed", error_type=type(exc).__name__,
                          http_status=getattr(exc, "status_code", None))
            raise RuntimeError(f"model_call_{index}_failed:{type(exc).__name__}") from None
        finally:
            record["elapsed_seconds"] = time.monotonic() - start
            write_json(self.output / f"call_{index:02d}.json", record)


def execute(inputs, condition, traced, output, model):
    from src.utils.pipeline_trace import PipelineTrace
    with PipelineTrace(output / 'pipeline_trace', {
        'entrypoint':'run_pilot_experiment.execute','condition':condition,
        'preprocessing':'not_executed_reusing_case_assets',
        'transcript_source':inputs.get('transcript_source'),
    }) as trace:
        trace.record('case.inputs', inputs={k:v for k,v in inputs.items() if k!='files'},
                     input_files={key:{'path':str(path),'sha256':sha256(path)} for key,path in inputs['files'].items()})
        result = _execute(inputs, condition, traced, output, model)
        trace.record('pipeline.return', html=result,
                     contains_html=bool(result and '<html' in result.lower()))
        return result


def _execute(inputs, condition, traced, output, model):
    from src.agents import coder, ui_architect
    # Load the existing vision module without initializing unrelated tools/agents.
    spec = importlib.util.spec_from_file_location("pilot_native_vision", ROOT / "src/tools/vision_tool.py")
    vision_tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vision_tool)
    intent = inputs["prompt"]
    if inputs.get("transcript"):
        intent += "\n\n[Spoken transcript]\n" + inputs["transcript"]
    # The native extractor resizes to 1024 and re-encodes; direct uses identical bytes.
    image_url = None
    if inputs.get("image"):
        from PIL import Image
        with Image.open(inputs["image"]) as image:
            image_url, _, _ = vision_tool._encode_image_to_data_url(image.convert("RGB"))
        (output / "effective_image.jpg").write_bytes(base64.b64decode(image_url.split(",", 1)[1]))
    with patch.object(vision_tool, "OpenAI", return_value=traced), \
         patch.object(ui_architect, "_get_openai_client", return_value=traced), \
         patch.object(coder, "_get_openai_client", return_value=traced), \
         patch.object(coder, "save_html_asset", return_value=str(output / "final_code.html")):
        if condition == "direct":
            traced.stage = "direct"
            response = traced.create(model=model, temperature=0.2, messages=[
                {"role": "system", "content": "Generate a complete standalone runnable HTML/CSS/JS UI prototype. Implement interactions locally with simulated data; return only HTML."},
                {"role": "user", "content": [{"type": "text", "text": intent},
                    {"type": "image_url", "image_url": {"url": image_url}}]},
            ])
            return coder.strip_markdown_code_fence(response.choices[0].message.content or "")
        vision = None
        if inputs.get("image"):
            traced.stage = "vision"
            vision = vision_tool.extract_ui_layout(str(inputs["image"]), user_context=intent)
            write_json(output / "vision_raw.json", vision)
            if vision.get("error"):
                raise ValueError("vision_extraction_failed")
            vision, validation = vision_tool.validate_vision_layout(vision, str(inputs["image"]))
            write_json(output / "vision_validated.json", vision)
            write_json(output / "vision_validation.json", validation.model_dump())
            if not validation.valid:
                raise ValueError("vision_validation_failed")
        # M0 deliberately supplies None: native architect accepts absent geometry.
        traced.stage = "ui_architect"
        if os.getenv('UI_STRUCTURE_MODE') == 'hierarchy_registry_image_v1':
            ui_state = ui_architect.generate_ui_state(intent, vision, image_data_url=image_url)
        else:
            ui_state = ui_architect.generate_ui_state(intent, vision)
        write_json(output / "ui_state.json", ui_state)
        if not ui_state or ui_state.get("error"):
            raise ValueError("ui_architect_failed")
        traced.stage = "coder"
        result = coder.generate_frontend_code(ui_state)
        return result.get("code", "") if isinstance(result, dict) else result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--condition", required=True, choices=["M0", "M1", "M2", "direct"])
    parser.add_argument("--model", required=True, help="Same multimodal model for every stage and condition")
    parser.add_argument("--output-root", type=Path, default=Path("outputs/pilot"))
    parser.add_argument("--dry-run", action="store_true", help="Validate/copy inputs without model imports or calls")
    args = parser.parse_args()
    case = args.case.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    output = args.output_root.resolve() / case.name / args.condition / stamp
    output.mkdir(parents=True, exist_ok=False)
    summary = {"condition": args.condition, "model": args.model, "method": "direct" if args.condition == "direct" else "existing_structured_pipeline",
               "status": "started", "python": platform.python_version(), "started_utc": datetime.now(timezone.utc).isoformat(),
               "temperature": {"vision": 0, "ui_architect": 0.3, "coder_or_direct": 0.2},
               "renderer": "llm", "max_retries": 0, "behavior_evaluated": False, "cost": None}
    summary["layout_solver_enabled"] = True
    traced = None
    start = time.monotonic()
    try:
        inputs = load_inputs(case, args.condition)
        summary["transcript_source"] = inputs["transcript_source"]
        summary["input_sha256"] = {key: sha256(path) for key, path in inputs["files"].items()}
        for key, path in inputs["files"].items():
            shutil.copyfile(path, output / (key + path.suffix))
        for name, command in {"git_head": ["git", "rev-parse", "HEAD"], "git_status": ["git", "status", "--short"]}.items():
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
            summary[name] = result.stdout.strip()
        # Hash runtime source, including uncommitted changes, without reading configs/secrets.
        sources = [p for folder in ("src", "scripts") for p in (ROOT / folder).rglob("*.py")]
        sources += list((ROOT / "src" / "prompts").rglob("*.md"))
        sources += list((ROOT / "src" / "priors").rglob("*.json"))
        sources += [ROOT / "requirements.txt", ROOT / "ARCHITECTURE.md"]
        summary["source_sha256"] = {str(p.relative_to(ROOT)): sha256(p) for p in sources}
        if args.dry_run:
            summary["status"] = "dry_run_only"
        else:
            from dotenv import load_dotenv
            load_dotenv()
            key = os.getenv("SILICONFLOW_API_KEY") or os.getenv("OPENAI_API_KEY")
            if not key:
                raise ValueError("missing_api_key")
            endpoint = os.getenv("SILICONFLOW_BASE_URL") or os.getenv("VISION_BASE_URL")
            if not endpoint:
                raise ValueError("explicit_base_url_required")
            from urllib.parse import urlsplit
            url = urlsplit(endpoint)
            if url.username or url.password or url.query or url.fragment:
                raise ValueError("base_url_must_not_contain_credentials_or_query")
            summary["endpoint"] = endpoint
            os.environ.update(VISION_MODEL=args.model, CODER_MODEL=args.model, CODER_PROD_MODEL=args.model,
                              SILICONFLOW_BASE_URL=endpoint, UI_RENDERER_MODE="llm", LAYOUT_SOLVER_ENABLED="1")
            from openai import OpenAI
            traced = TracedClient(OpenAI(api_key=key, base_url=endpoint, max_retries=0, timeout=180), output)
            code = execute(inputs, args.condition, traced, output, args.model)
            if not code or "<html" not in code.lower():
                raise ValueError("no_complete_html_returned")
            (output / "final_code.html").write_text(code, encoding="utf-8")
            summary["status"] = "html_generated_pending_browser_validation"
    except Exception as exc:
        summary.update(status="failed", error_type=type(exc).__name__)
        summary["failure_stack"] = [{"file": frame.filename, "line": frame.lineno, "function": frame.name}
                                    for frame in traceback.extract_tb(exc.__traceback__)]
        if isinstance(exc, ValueError):
            summary["failure_reason"] = str(exc)
        # Raw provider exceptions are intentionally excluded from logs.
    finally:
        summary["elapsed_seconds"] = time.monotonic() - start
        summary["call_count"] = len(traced.calls) if traced else 0
        summary["usage"] = [c.get("response", {}).get("usage") for c in traced.calls] if traced else []
        write_json(output / "run_summary.json", summary)
        print(f"{summary['status']}: {output}")
    return 1 if summary["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
