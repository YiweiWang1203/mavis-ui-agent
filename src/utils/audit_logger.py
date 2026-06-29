import os
import json
from datetime import datetime
from pathlib import Path
import threading


def _safe_serialize(obj):
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return str(obj)


class AuditLogger:
    def __init__(self, mode: str, output_root: str = "data/outputs/audit_logs"):
        self.mode = mode
        self.output_root = Path(output_root)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = self.output_root / f"audit_{ts}_{mode}"
        os.makedirs(self.run_dir, exist_ok=True)

        # subdirs
        (self.run_dir / "prompt_snapshots").mkdir(exist_ok=True)
        (self.run_dir / "state_snapshots").mkdir(exist_ok=True)
        (self.run_dir / "artifacts").mkdir(exist_ok=True)

        # manifest
        self.manifest = {
            "mode": mode,
            "created_at": ts,
            "run_dir": str(self.run_dir),
            "entries": {}
        }
        self._lock = threading.Lock()

        # open files
        self.node_trace_path = self.run_dir / "node_trace.jsonl"
        self.llm_calls_path = self.run_dir / "llm_calls.jsonl"
        self.vision_calls_path = self.run_dir / "vision_calls.jsonl"

        # write initial manifest
        self._write_json(self.run_dir / "audit_manifest.json", self.manifest)

    def _write_json(self, path: Path, data: dict):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _append_jsonl(self, path: Path, record: dict):
        try:
            with self._lock, open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def log_stage(self, stage_name: str, data: dict):
        rec = {"ts": datetime.now().isoformat(), "stage": stage_name, "data": _safe_serialize(data)}
        self._append_jsonl(self.node_trace_path, rec)

    def log_node_start(self, node_name: str, state_summary: dict):
        rec = {"ts": datetime.now().isoformat(), "event": "node_start", "node": node_name, "state_summary": _safe_serialize(state_summary)}
        self._append_jsonl(self.node_trace_path, rec)

    def log_node_end(self, node_name: str, output_summary: dict):
        rec = {"ts": datetime.now().isoformat(), "event": "node_end", "node": node_name, "output_summary": _safe_serialize(output_summary)}
        self._append_jsonl(self.node_trace_path, rec)

    def log_llm_call(self, call_name: str, model: str, system_prompt: str | None, user_prompt: str | None, messages: list | None, response: str | None, metadata: dict | None = None):
        # Save prompt snapshots separately (without secrets)
        name = f"{datetime.now().strftime('%H%M%S')}_{call_name}"
        try:
            if system_prompt:
                p = self.run_dir / "prompt_snapshots" / f"{name}_system.txt"
                p.write_text(system_prompt[:10000], encoding="utf-8")
            if user_prompt:
                p2 = self.run_dir / "prompt_snapshots" / f"{name}_user.txt"
                p2.write_text(user_prompt[:10000], encoding="utf-8")
        except Exception:
            pass

        rec = {
            "ts": datetime.now().isoformat(),
            "call_name": call_name,
            "model": model,
            "system_prompt_snapshot": str((self.run_dir / "prompt_snapshots" / f"{name}_system.txt")) if system_prompt else None,
            "user_prompt_snapshot": str((self.run_dir / "prompt_snapshots" / f"{name}_user.txt")) if user_prompt else None,
            "messages_summary": _safe_serialize(messages) if messages else None,
            "response_summary": (response[:2000] if isinstance(response, str) else _safe_serialize(response)),
            "metadata": _safe_serialize(metadata or {})
        }
        self._append_jsonl(self.llm_calls_path, rec)

    def log_vision_call(self, call_name: str, image_path: str, prompt: str | None, response: str | None, metadata: dict | None = None):
        # Save small snapshot of prompt
        name = f"{datetime.now().strftime('%H%M%S')}_{call_name}"
        try:
            if prompt:
                p = self.run_dir / "prompt_snapshots" / f"{name}_vision_prompt.txt"
                p.write_text(prompt[:5000], encoding="utf-8")
        except Exception:
            pass

        resp_summary = response if response is None else (response[:2000] if isinstance(response, str) else _safe_serialize(response))
        rec = {
            "ts": datetime.now().isoformat(),
            "call_name": call_name,
            "image_path": image_path,
            "prompt_snapshot": str((self.run_dir / "prompt_snapshots" / f"{name}_vision_prompt.txt")) if prompt else None,
            "response_summary": resp_summary,
            "metadata": _safe_serialize(metadata or {})
        }
        self._append_jsonl(self.vision_calls_path, rec)

    def save_prompt_snapshot(self, name: str, content: str):
        try:
            p = self.run_dir / "prompt_snapshots" / f"{name}.txt"
            p.write_text(content[:10000], encoding="utf-8")
            return str(p)
        except Exception:
            return ""

    def save_state_snapshot(self, name: str, state: dict):
        # remove large base64 images
        s = _safe_serialize(state)
        if isinstance(s, dict):
            # sanitize any large strings
            for k, v in list(s.items()):
                if isinstance(v, str) and len(v) > 20000 and v.startswith("data:image"):
                    s[k] = "[BASE64_IMAGE_OMITTED]"
        try:
            p = self.run_dir / "state_snapshots" / f"{name}.json"
            with open(p, "w", encoding="utf-8") as f:
                json.dump(s, f, ensure_ascii=False, indent=2)
            return str(p)
        except Exception:
            return ""

    def register_artifact(self, name: str, path: str, description: str):
        try:
            art = self.run_dir / "artifacts" / "artifact_index.md"
            with open(art, "a", encoding="utf-8") as f:
                f.write(f"- **{name}**: {path} — {description}\n")
        except Exception:
            pass

    def finalize(self, summary: dict | None = None):
        try:
            if summary:
                self.manifest["summary"] = summary
            self._write_json(self.run_dir / "audit_manifest.json", self.manifest)
            # also write a short summary md
            md = self.run_dir / "summary_report.md"
            with open(md, "w", encoding="utf-8") as f:
                f.write("# Audit Summary\n\n")
                f.write(json.dumps(self.manifest.get("summary", {}), ensure_ascii=False, indent=2))
        except Exception:
            pass
