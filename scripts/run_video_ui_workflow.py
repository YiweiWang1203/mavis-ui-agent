from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.service.input_adapter import prepare_workflow_input


def _message_dicts_to_human_messages(state: dict[str, Any]) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage

    converted = dict(state)
    messages = []
    for message in state.get("messages", []):
        if isinstance(message, dict):
            messages.append(HumanMessage(content=message.get("content", "")))
        else:
            messages.append(message)
    converted["messages"] = messages
    return converted


def _apply_locale_override(prepared: dict[str, Any], locale: str) -> None:
    if locale == "auto":
        return
    prepared["preferred_locale"] = locale
    prepared["state"]["preferred_locale"] = locale
    prompt = prepared["final_prompt"]
    lines = []
    replaced = False
    for line in prompt.splitlines():
        if line.startswith("preferred_locale:"):
            lines.append(f"preferred_locale: {locale}")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.insert(3, f"preferred_locale: {locale}")
    final_prompt = "\n".join(lines)
    prepared["final_prompt"] = final_prompt
    prepared["state"]["messages"] = [{"role": "user", "content": final_prompt}]


def run_deterministic_pipeline(prepared: dict[str, Any]) -> dict[str, Any]:
    from src.graph.nodes import code_node, ui_architect_node, vision_node

    state = _message_dicts_to_human_messages(prepared["state"])

    print("[1/3] Running vision_node...")
    vision_cmd = vision_node(state)
    state.update(vision_cmd.update)
    print("vision_status:", state.get("vision_status"))
    if not state.get("vision_status", {}).get("valid"):
        return state

    print("[2/3] Running ui_architect_node...")
    ui_cmd = ui_architect_node(state)
    state.update(ui_cmd.update)
    ui_state = state.get("ui_state_json")
    if isinstance(ui_state, dict):
        print("ui_state_json keys:", list(ui_state.keys()))
        print("locale:", ui_state.get("page_meta", {}).get("locale"))
        print("page_kind:", ui_state.get("page_meta", {}).get("page_kind"))
        if ui_state.get("warnings"):
            print("ui_warnings:", ui_state.get("warnings"))
    if not ui_state or (isinstance(ui_state, dict) and ui_state.get("error")):
        return state

    print("[3/3] Running code_node...")
    coder_cmd = code_node(state)
    state.update(coder_cmd.update)
    print("final_code_path:", state.get("final_code_path"))
    print("final_code_length:", len(state.get("final_code") or ""))
    print("final_renderer:", state.get("final_renderer"))
    return state


def run_full_graph(prepared: dict[str, Any]) -> dict[str, Any]:
    from src.graph import build_graph

    graph = build_graph()
    state = prepared["state"]
    final_state = state.copy()
    for update in graph.stream(state, stream_mode="updates"):
        for node_name, content in update.items():
            print(f"\n=== {node_name} ===")
            if isinstance(content, dict):
                final_state.update(content)
                print("keys:", list(content.keys()))
                if content.get("vision_status"):
                    print("vision_status:", content["vision_status"])
                if content.get("ui_state_json"):
                    print("ui_state_json keys:", list(content["ui_state_json"].keys()))
                if content.get("final_code"):
                    print("final_code_length:", len(content["final_code"]))
    return final_state


def _summary(prepared: dict[str, Any], final_state: dict[str, Any], mode: str) -> dict[str, Any]:
    ui_state = final_state.get("ui_state_json") if isinstance(final_state.get("ui_state_json"), dict) else {}
    return {
        "mode": mode,
        "selected_image_path": prepared.get("selected_image_path"),
        "recognition_image_path": prepared.get("recognition_image_path"),
        "layout_image_path": prepared.get("layout_image_path"),
        "vision_image_mode": prepared.get("vision_image_mode"),
        "selected_source": prepared.get("selected_source"),
        "audio_path": prepared.get("audio_path"),
        "package_path": prepared.get("package_path"),
        "preferred_locale": prepared.get("preferred_locale"),
        "vision_status": final_state.get("vision_status"),
        "ui_state_json_present": final_state.get("ui_state_json") is not None,
        "ui_page_kind": ui_state.get("page_meta", {}).get("page_kind"),
        "layout_solver": ui_state.get("page_meta", {}).get("layout_solver"),
        "ui_warnings": ui_state.get("warnings", []),
        "final_code_present": final_state.get("final_code") is not None,
        "final_code_length": len(final_state.get("final_code") or ""),
        "final_code_path": final_state.get("final_code_path"),
        "final_renderer": final_state.get("final_renderer"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run video-to-UI workflow from a video path and user prompt.")
    parser.add_argument("--video", required=True, help="Input sketch video path")
    parser.add_argument("--prompt", required=True, help="User prompt text")
    parser.add_argument("--image", help="Optional user-uploaded sketch image path")
    parser.add_argument("--output", default="outputs/video_ui_workflow", help="Preprocess and debug output directory")
    parser.add_argument("--locale", choices=["auto", "zh-CN", "en"], default="auto", help="UI locale override")
    parser.add_argument("--rotate-degrees", type=int, choices=[0, 90, 180, 270], default=180)
    parser.add_argument("--disable-orientation-correction", action="store_true")
    parser.add_argument("--enable-asr", action="store_true", help="Enable ASR during preprocessing")
    parser.add_argument(
        "--disable-layout-solver",
        action="store_true",
        help="Disable relational layout solving for an A/B comparison with raw vision bboxes.",
    )
    parser.add_argument(
        "--renderer",
        choices=["auto", "deterministic", "llm"],
        default="auto",
        help="Use deterministic rendering for supported pages, force it, or retain the LLM coder.",
    )
    parser.add_argument(
        "--vision-image-mode",
        choices=["recognition", "normalized"],
        default="recognition",
        help="Use orientation-corrected recognition image for VLM by default; use normalized to reproduce the previous behavior.",
    )
    parser.add_argument("--full-graph", action="store_true", help="Run the planner/supervisor LangGraph instead of the deterministic pipeline")
    args = parser.parse_args()

    if args.disable_layout_solver:
        os.environ["LAYOUT_SOLVER_ENABLED"] = "0"
    os.environ["UI_RENDERER_MODE"] = args.renderer

    prepared = prepare_workflow_input(
        text=args.prompt,
        video_path=args.video,
        image_path=args.image,
        preprocess_output_dir=args.output,
        rotate_degrees=args.rotate_degrees,
        orientation_correction_enabled=not args.disable_orientation_correction,
        enable_asr=args.enable_asr,
        vision_image_mode=args.vision_image_mode,
    )
    _apply_locale_override(prepared, args.locale)

    print("selected_image_path:", prepared["selected_image_path"])
    print("recognition_image_path:", prepared.get("recognition_image_path"))
    print("layout_image_path:", prepared.get("layout_image_path"))
    print("vision_image_mode:", prepared.get("vision_image_mode"))
    print("audio_path:", prepared["audio_path"])
    print("preferred_locale:", prepared["preferred_locale"])
    print("layout_solver_enabled:", not args.disable_layout_solver)
    print("renderer:", args.renderer)

    mode = "full_graph" if args.full_graph else "deterministic"
    final_state = run_full_graph(prepared) if args.full_graph else run_deterministic_pipeline(prepared)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "workflow_summary.json"
    summary = _summary(prepared, final_state, mode)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if final_state.get("vision_elements"):
        (output_dir / "vision_elements.json").write_text(
            json.dumps(final_state["vision_elements"], ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    if final_state.get("ui_state_json"):
        (output_dir / "ui_state.json").write_text(
            json.dumps(final_state["ui_state_json"], ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    if final_state.get("final_code"):
        (output_dir / "final_code.html").write_text(final_state["final_code"], encoding="utf-8")

    print("\nsummary:", summary_path)
    print("final_code_path:", summary.get("final_code_path"))
    print("final_code_copy:", output_dir / "final_code.html")
    return 0 if summary.get("final_code_present") else 1


if __name__ == "__main__":
    raise SystemExit(main())
