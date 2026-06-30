from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REQUIRED_MODULES = [
    "pydantic",
    "cv2",
    "PIL",
    "dotenv",
    "langchain_core",
    "langgraph",
]

OPTIONAL_MODULES = [
    "pytest",
    "funasr",
    "torch",
    "openai",
]

DEPRECATED_MODELS = {
    "Pro/Qwen/Qwen2.5-VL-7B-Instruct": "Qwen/Qwen3-VL-8B-Instruct",
    "Qwen/Qwen2.5-VL-7B-Instruct": "Qwen/Qwen3-VL-8B-Instruct",
    "Qwen/Qwen2-VL-72B-Instruct": "Qwen/Qwen3-VL-32B-Instruct",
}


def check_module(name: str) -> dict[str, Any]:
    try:
        module = importlib.import_module(name)
        version = getattr(module, "__version__", None)
        return {"name": name, "ok": True, "version": version}
    except Exception as exc:
        return {"name": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def check_ffmpeg() -> dict[str, Any]:
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "path": None, "error": "ffmpeg not found in PATH"}
    try:
        proc = subprocess.run([exe, "-version"], check=False, capture_output=True, text=True, timeout=10)
        first_line = proc.stdout.splitlines()[0] if proc.stdout else ""
        return {"ok": proc.returncode == 0, "path": exe, "version": first_line}
    except Exception as exc:
        return {"ok": False, "path": exe, "error": f"{type(exc).__name__}: {exc}"}


def check_path(path: str | None, kind: str, must_exist: bool = True) -> dict[str, Any]:
    if not path:
        return {"kind": kind, "path": path, "ok": not must_exist, "exists": False}
    p = Path(path).expanduser()
    exists = p.exists()
    return {
        "kind": kind,
        "path": str(p),
        "ok": exists if must_exist else True,
        "exists": exists,
        "is_file": p.is_file() if exists else False,
        "is_dir": p.is_dir() if exists else False,
    }


def check_writable_dir(path: Path) -> dict[str, Any]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return {"path": str(path), "ok": True}
    except Exception as exc:
        return {"path": str(path), "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def detect_workspace_root() -> Path:
    configured = os.getenv("MAVIS_WORKSPACE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def load_env_file() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
    except Exception:
        pass


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    workspace_root = detect_workspace_root()
    model_root = Path(os.getenv("FUNASR_MODELS_DIR", workspace_root / "data" / "models" / "iic")).expanduser()

    environment = {
        "MAVIS_WORKSPACE_ROOT": os.getenv("MAVIS_WORKSPACE_ROOT"),
        "FUNASR_MODELS_DIR": os.getenv("FUNASR_MODELS_DIR"),
        "ASR_DEVICE": os.getenv("ASR_DEVICE", "cuda"),
        "VISION_MODEL": os.getenv("VISION_MODEL"),
        "VISION_BASE_URL": os.getenv("VISION_BASE_URL"),
        "VL_MODEL": os.getenv("VL_MODEL"),
        "VL_BASE_URL": os.getenv("VL_BASE_URL"),
    }
    deprecated_model_hits = {
        key: {"current": value, "replacement": DEPRECATED_MODELS[value]}
        for key, value in environment.items()
        if key.endswith("_MODEL") and value in DEPRECATED_MODELS
    }

    return {
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "platform": sys.platform,
        },
        "workspace": {
            "root": str(workspace_root),
            "exists": workspace_root.exists(),
            "outputs_writable": check_writable_dir(workspace_root / "outputs"),
        },
        "environment": environment,
        "deprecated_models": deprecated_model_hits,
        "modules": {
            "required": [check_module(name) for name in REQUIRED_MODULES],
            "optional": [check_module(name) for name in OPTIONAL_MODULES],
        },
        "ffmpeg": check_ffmpeg(),
        "paths": {
            "video": check_path(args.video, "video", must_exist=bool(args.video)),
            "image": check_path(args.image, "image", must_exist=bool(args.image)),
            "audio": check_path(args.audio, "audio", must_exist=bool(args.audio)),
            "funasr_models": check_path(str(model_root), "funasr_models", must_exist=False),
        },
    }


def has_failures(report: dict[str, Any]) -> bool:
    required_modules = report["modules"]["required"]
    if any(not item["ok"] for item in required_modules):
        return True
    if not report["ffmpeg"]["ok"]:
        return True
    for key in ("video", "image", "audio"):
        item = report["paths"][key]
        if item["path"] and not item["ok"]:
            return True
    if not report["workspace"]["outputs_writable"]["ok"]:
        return True
    if report.get("deprecated_models"):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Check runtime environment for mavis-ui-agent.")
    parser.add_argument("--video", help="Optional video path to validate")
    parser.add_argument("--image", help="Optional image path to validate")
    parser.add_argument("--audio", help="Optional audio path to validate")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    load_env_file()
    report = build_report(args)
    failed = has_failures(report)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Python: {report['python']['executable']}")
        print(f"Workspace: {report['workspace']['root']}")
        print(f"Outputs writable: {report['workspace']['outputs_writable']['ok']}")
        print(f"ffmpeg: {'OK' if report['ffmpeg']['ok'] else 'MISSING'} {report['ffmpeg'].get('path') or ''}")

        print("\nRequired modules:")
        for item in report["modules"]["required"]:
            suffix = f" ({item['version']})" if item.get("version") else ""
            detail = suffix if item["ok"] else f" - {item['error']}"
            print(f"  {'OK' if item['ok'] else 'MISSING'} {item['name']}{detail}")

        print("\nOptional modules:")
        for item in report["modules"]["optional"]:
            suffix = f" ({item['version']})" if item.get("version") else ""
            detail = suffix if item["ok"] else f" - {item['error']}"
            print(f"  {'OK' if item['ok'] else 'MISSING'} {item['name']}{detail}")

        for key, item in report["paths"].items():
            if item["path"]:
                print(f"{key}: {'OK' if item['ok'] else 'MISSING'} {item['path']}")

        if report.get("deprecated_models"):
            print("\nDeprecated model configuration:")
            for key, item in report["deprecated_models"].items():
                print(f"  {key}: {item['current']} -> use {item['replacement']}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
