"""Replay the frozen 006 multimodal input once with the production asset contract."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.service.direct_multimodal_baseline import ASSET_RULES, DIRECT_ASSET_POLICY, PROMPT, submit_direct_html
from src.service.main_model_runtime import DIRECT_MULTIMODAL_PROFILE, MODEL, MainModelRuntime
from src.service.main_ui_workflow import safe_diagnostic, save, sha
from src.utils.single_attempt_transport import isolated_sdk_call


SOURCE_SHA = "4465e84409a6c7507a7fcad028f774d3b01b4ab9981157f3304debfba8e70158"


def load_frozen(archive_path):
    if sha(archive_path) != SOURCE_SHA:
        raise ValueError("DIRECT_ASSET_RECOVERY_SOURCE_HASH")
    with tarfile.open(archive_path) as archive:
        requests = [name for name in archive.getnames() if name.endswith("/requests/direct_coder_request.json")]
        if len(requests) != 1:
            raise ValueError("DIRECT_ASSET_RECOVERY_SOURCE_REQUEST_COUNT")
        root = requests[0].removesuffix("/requests/direct_coder_request.json")
        raw = {
            name: archive.extractfile(f"{root}/{member}").read()
            for name, member in {
                "request": "requests/direct_coder_request.json",
                "response": "requests/direct_coder_response.json",
                "terminal": "terminal.json",
            }.items()
        }
    request, response, terminal = (json.loads(raw[key]) for key in ("request", "response", "terminal"))
    expected = {"model": MODEL, "temperature": 0.2, "max_tokens": 8192, "timeout": 600}
    system, user = request["messages"]
    if (request != {**expected, "messages": request["messages"]}
            or system != {"role": "system", "content": PROMPT}
            or user["role"] != "user" or [item["type"] for item in user["content"]] != ["text", "image_url"]
            or terminal["config"]["runtime_profile"] != DIRECT_MULTIMODAL_PROFILE
            or terminal["model_calls"] != ["direct_coder"] or terminal["html_generated"]
            or response["response"]["choices"][0]["finish_reason"] != "length"):
        raise ValueError("DIRECT_ASSET_RECOVERY_FROZEN_INPUT")
    return raw, request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_archive", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    raw, request = load_frozen(args.source_archive)
    if args.validate_only:
        print("Verified frozen 006 multimodal request and length terminal. Maximum real requests: 1.")
        return 0
    if args.output is None:
        parser.error("Provide a new output directory")
    if subprocess.check_output(["git", "status", "--porcelain", "--", "src", "config",
                                str(Path(__file__).relative_to(ROOT))], cwd=ROOT).strip():
        raise ValueError("DIRECT_ASSET_RECOVERY_SOURCE_DIRTY")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for key, blob in raw.items():
        (output / f"original_{key}.json").write_bytes(blob)
    identity = {
        "asset_policy": DIRECT_ASSET_POLICY, "source_archive_sha256": SOURCE_SHA, "max_physical_requests": 1,
        "automatic_retries": 0, "model": MODEL, "max_output_tokens": 8192, "timeout_seconds": 600,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    }
    save(output / "run_identity.json", identity)
    terminal = {**identity, "html_generated": False, "status": "FAILED_NO_RETRY"}
    system, *rest = request["messages"]
    expected = {**request, "messages": [{**system, "content": PROMPT + "\n\n" + ASSET_RULES}, *rest]}

    def dispatch(actual, **kwargs):
        if actual != expected:
            raise RuntimeError("DIRECT_ASSET_RECOVERY_SERIALIZED_DRIFT")
        return isolated_sdk_call(actual, **kwargs)

    with MainModelRuntime(output / "requests", dispatch, profile=DIRECT_MULTIMODAL_PROFILE) as runtime:
        try:
            terminal.update(submit_direct_html(request, output, compact_assets=True))
        except Exception as error:
            save(output / "failure_diagnostic.json", safe_diagnostic(error))
        terminal["model_calls"] = list(runtime.used)
    save(output / "terminal.json", terminal)
    save(output / "artifact_sha256.json", {str(path.relative_to(output)): sha(path)
                                            for path in sorted(output.rglob("*")) if path.is_file()})
    return 0 if terminal["html_generated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
