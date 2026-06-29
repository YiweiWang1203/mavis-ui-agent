import os
import json
import sys
import argparse
from dotenv import load_dotenv

# Environment setup
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.insert(0, project_root)

load_dotenv()

from src.graph.builder import build_graph
from src.utils.audit_logger import AuditLogger
from src.config import TEAM_MEMBERS
from pathlib import Path
from src.utils.layout_inspector import save_overlap_report


def score_sketch_candidate(image_path: str) -> dict:
    """Score an image for suitability as UI sketch input."""
    import cv2
    import numpy as np

    out = {
        "image_path": image_path,
        "exists": False,
        "readable": False,
        "width": 0,
        "height": 0,
        "sharpness_score": 0.0,
        "edge_density_score": 0.0,
        "content_coverage_score": 0.0,
        "aspect_score": 0.0,
        "final_score": 0.0,
        "warnings": [],
    }

    p = Path(image_path)
    if not p.exists():
        out["warnings"].append("file_missing")
        return out

    out["exists"] = True

    img = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if img is None:
        out["warnings"].append("not_readable")
        return out

    out["readable"] = True
    h, w = img.shape[:2]
    out["width"] = w
    out["height"] = h

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    lap = cv2.Laplacian(gray, cv2.CV_64F)
    var = float(lap.var())
    sharp = max(0.0, min(1.0, var / (var + 100.0)))
    out["sharpness_score"] = sharp

    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(edges.astype(bool).sum()) / (w * h)
    ed = max(0.0, min(1.0, (edge_density - 0.005) / (0.15 - 0.005)))
    out["edge_density_score"] = ed

    thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)[1]
    coverage = float(thresh.astype(bool).sum()) / (w * h)
    cc = max(0.0, min(1.0, coverage * 2.0))
    out["content_coverage_score"] = cc

    ratio = w / h if h > 0 else 1.0
    target = 9.0 / 16.0
    aspect_score = 1.0 - min(1.0, abs(ratio - target) / 1.0)
    out["aspect_score"] = aspect_score

    final = 0.3 * sharp + 0.3 * ed + 0.25 * cc + 0.15 * aspect_score
    out["final_score"] = float(max(0.0, min(1.0, final)))

    return out


def select_best_sketch_candidate(user_image_path: str | None, video_image_path: str | None, output_dir: str | None = None) -> dict:
    """Select best candidate between user image and video-derived image."""
    import os

    ui_score = None
    vid_score = None

    if user_image_path:
        ui_score = score_sketch_candidate(user_image_path)
    if video_image_path:
        vid_score = score_sketch_candidate(video_image_path)

    ui_valid = ui_score is not None and ui_score.get("readable")
    vid_valid = vid_score is not None and vid_score.get("readable")

    if not ui_valid and not vid_valid:
        raise RuntimeError("No valid image candidates available")

    selection_reason = ""
    selected = None
    selected_source = None

    if ui_valid and not vid_valid:
        selected = user_image_path
        selected_source = "user_image"
        selection_reason = "only user image readable"
    elif vid_valid and not ui_valid:
        selected = video_image_path
        selected_source = "video_preprocessed_sketch"
        selection_reason = "only video-derived image readable"
    else:
        u_score = ui_score.get("final_score", 0.0)
        v_score = vid_score.get("final_score", 0.0)
        if abs(u_score - v_score) < 0.05:
            selected = video_image_path
            selected_source = "video_preprocessed_sketch"
            selection_reason = "scores close — prefer video-derived"
        elif v_score > u_score:
            selected = video_image_path
            selected_source = "video_preprocessed_sketch"
            selection_reason = "video score higher"
        else:
            selected = user_image_path
            selected_source = "user_image"
            selection_reason = "user image score higher"

    out = {
        "selected_image_path": selected,
        "selected_source": selected_source,
        "selection_reason": selection_reason,
        "user_score": ui_score,
        "video_score": vid_score,
    }

    if output_dir:
        try:
            os.makedirs(output_dir, exist_ok=True)
            selfpath = os.path.join(output_dir, "sketch_candidate_selection.json")
            with open(selfpath, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return out


def prepare_input_from_video(
    video_path: str,
    user_text: str,
    preprocess_output_dir: str | None = None,
    rotate_degrees: int = 180,
    orientation_correction_enabled: bool = True,
) -> dict:
    """Wrapper that runs the PreAgentOrchestrator and returns a normalized dict result for tests.

    Tests may monkeypatch `src.preprocess.orchestrator.PreAgentOrchestrator` to a fake class.
    """
    from importlib import import_module

    pp_module = import_module("src.preprocess.orchestrator")
    PreAgentOrchestrator = getattr(pp_module, "PreAgentOrchestrator")
    # construct the pydantic UserPreprocessInput expected by the orchestrator
    schemas_mod = import_module("src.preprocess.schemas")
    UserPreprocessInput = getattr(schemas_mod, "UserPreprocessInput")

    inp = UserPreprocessInput(
        user_prompt=user_text,
        video_path=video_path,
        output_dir=preprocess_output_dir or "outputs/preprocess",
        rotate_degrees=rotate_degrees,
        disable_orientation_correction=(not orientation_correction_enabled),
    )

    orch = PreAgentOrchestrator(output_root=preprocess_output_dir)
    res = orch.run(inp)

    out = {}
    if isinstance(res, dict):
        out.update(res)
    else:
        for k in [
            "normalized_sketch_path",
            "orientation_corrected_sketch_path",
            "package_path",
            "text",
            "platform_hint",
            "target_ratio",
            "target_size",
        ]:
            if hasattr(res, k):
                out[k] = getattr(res, k)

    image_path = out.get("normalized_sketch_path") or out.get("orientation_corrected_sketch_path") or out.get("image_path")
    package_path = out.get("package_path")
    # ensure returned text includes preprocessing context when not provided by orchestrator
    text = out.get("text") or (user_text + "\n[视频前置处理上下文]")

    if not package_path and preprocess_output_dir:
        meta = os.path.join(preprocess_output_dir, "metadata", "package.json")
        if os.path.exists(meta):
            package_path = meta

    return {
        "image_path": image_path,
        "text": text,
        "package_path": package_path,
        "preprocess_output_dir": preprocess_output_dir,
        "orientation_corrected_sketch_path": out.get("orientation_corrected_sketch_path"),
        "platform_hint": out.get("platform_hint"),
        "target_ratio": out.get("target_ratio"),
        "target_size": out.get("target_size"),
    }


def main():
    parser = argparse.ArgumentParser(description="多模态 UI 页面生成 Agent")
    parser.add_argument("--text", type=str, help="用户的文字描述需求", default="")
    parser.add_argument("--image", type=str, help="草图的绝对路径")
    parser.add_argument("--video", type=str, help="视频的绝对路径")
    parser.add_argument("--preprocess-output", type=str, help="预处理输出目录", default=None)
    parser.add_argument("--rotate-degrees", type=int, choices=[0, 90, 180, 270], default=180, help="rotation degrees for orientation correction")
    parser.add_argument("--disable-orientation-correction", action="store_true", help="disable orientation correction step")
    parser.add_argument("--audio", type=str, help="录音的绝对路径")
    parser.add_argument("--dry-run", action="store_true", help="only run up to prompt injection and exit without invoking graph")
    parser.add_argument("--audit", action="store_true", help="enable audit logging for this run")
    parser.add_argument("--audit-output", type=str, help="audit output root", default="data/outputs/audit_logs")
    args = parser.parse_args()

    print("[STAGE 1] CLI arguments parsed")

    if not args.image and not args.video:
        parser.error("必须提供 --image 或 --video，至少提供一种输入。")

    if args.text:
        user_text = args.text
    else:
        user_text = "请根据提供的附件生成前端代码。"

    prompt_parts = [f"用户需求: {user_text}"]

    selected_image_path = None
    selected_source = None
    preprocess_package_path = None
    pp_out = args.preprocess_output or os.path.join(project_root, "outputs", "preprocess")

    print("[STAGE 2] Input routing resolved")

    if args.image and not args.video:
        if not os.path.exists(args.image):
            print(f"❌ 图片路径不存在: {args.image}")
            return
        print("[IMAGE MODE] Using original image input directly.")
        selected_image_path = args.image
        selected_source = "user_image"
        prompt_parts.append(f"[IMAGE]: {selected_image_path}")

    elif args.video and not args.image:
        if not os.path.exists(args.video):
            print(f"❌ 视频路径不存在: {args.video}")
            return
        print("[VIDEO MODE] Preprocessing video input...")
        print("[STAGE 3] Video preprocessing started")
        res = prepare_input_from_video(
            video_path=args.video,
            user_text=user_text,
            preprocess_output_dir=pp_out,
            rotate_degrees=args.rotate_degrees,
            orientation_correction_enabled=(not args.disable_orientation_correction),
        )
        print("[STAGE 3] Video preprocessing completed")
        selected_image_path = res["image_path"]
        selected_source = "video_preprocessed_sketch"
        preprocess_package_path = res.get("package_path")
        prompt_parts = [f"用户需求: {res['text']}", f"[IMAGE]: {selected_image_path}"]

    else:
        # both image and video
        if not os.path.exists(args.image):
            print(f"❌ 图片路径不存在: {args.image}")
            return
        if not os.path.exists(args.video):
            print(f"❌ 视频路径不存在: {args.video}")
            return
        print("[MULTI-SOURCE MODE] Both image and video inputs detected.")
        print("[STAGE 3] Video preprocessing started")
        res = prepare_input_from_video(
            video_path=args.video,
            user_text=user_text,
            preprocess_output_dir=pp_out,
            rotate_degrees=args.rotate_degrees,
            orientation_correction_enabled=(not args.disable_orientation_correction),
        )
        print("[STAGE 3] Video preprocessing completed")
        video_image = res["image_path"]

        print("[STAGE 4] Candidate sketch selection started")
        user_score = score_sketch_candidate(args.image)
        video_score = score_sketch_candidate(video_image)
        print(f"[MULTI-SOURCE MODE] user_image_score: {user_score['final_score']}")
        print(f"[MULTI-SOURCE MODE] video_image_score: {video_score['final_score']}")
        sel = select_best_sketch_candidate(args.image, video_image, output_dir=pp_out)
        selected_image_path = sel["selected_image_path"]
        selected_source = sel["selected_source"]
        selection_reason = sel.get("selection_reason", "")
        print("[STAGE 5] Candidate sketch selection completed")

        enhanced = (
            f"{user_text}\n\n[视频前置处理上下文]\n"
            f"当前输入包含视频。系统已自动完成视频前置处理，并提取出视频中的最终草图图像。\n"
            f"视频草图已根据台灯前上方摄像头拍摄方向完成 {args.rotate_degrees}° 方向校正，并已归一化到目标尺寸。\n\n"
            f"[候选草图选择结果]\n"
            f"用户上传图片：\n{args.image}\n\n"
            f"视频提取草图：\n{video_image}\n\n"
            f"最终选择：\n{selected_image_path}\n\n"
            f"选择来源：\n{selected_source}\n\n"
            f"选择原因：\n{selection_reason}\n\n"
            f"[重要要求]\n"
            f"请将最终选择的图像视为唯一的最终 UI 草图输入。\n"
        )
        prompt_parts = [f"用户需求: {enhanced}", f"[IMAGE]: {selected_image_path}"]

    if args.audio:
        if not os.path.exists(args.audio):
            print(f"❌ 音频路径不存在: {args.audio}")
            return
        prompt_parts.append(f"[AUDIO FILE]: {args.audio}")

    final_prompt = "\n".join(prompt_parts)
    print(f"\n📦 接收到的动态输入:\n{final_prompt}\n")

    if args.dry_run:
        print("[DRY RUN] Exiting before graph invocation as requested.")
        print(f"selected_image_path: {selected_image_path}")
        print(f"selected_source: {selected_source}")
        print(f"package_path: {preprocess_package_path}")
        print(f"final_prompt_preview: {final_prompt[:1000]}")
        return

    # --- Audit setup ---
    audit_logger = None
    if args.audit:
        # infer mode
        mode = "image_only" if args.image and not args.video else ("video_only" if args.video and not args.image else "multi_source")
        audit_logger = AuditLogger(mode=mode, output_root=args.audit_output)
        # register initial cli and inputs
        audit_logger.log_stage("cli_args", {k: (str(v) if k != 'audit' else v) for k, v in vars(args).items()})
        audit_logger.save_prompt_snapshot("user_text", user_text)
        audit_logger.save_prompt_snapshot("final_prompt", final_prompt)
        # write initial routing state
        routing = {
            "selected_image_path": selected_image_path,
            "selected_source": selected_source,
            "preprocess_package_path": preprocess_package_path,
        }
        audit_logger.save_state_snapshot("input_routing", routing)
        # we'll attach to inputs after they are created below
        audit_logger_instance = audit_logger
        audit_enabled_flag = True
        audit_run_dir_val = str(audit_logger.run_dir)

    inputs = {
        "TEAM_MEMBERS": TEAM_MEMBERS,
        "messages": [{"role": "user", "content": final_prompt}],
        "voice_intent": None,
        "vision_elements": None,
        "ui_state_json": None,
        "final_code": None,
        "warnings": []
    }
    # attach audit instance if enabled
    if args.audit:
        inputs["_audit_logger_instance"] = audit_logger_instance
        inputs["audit_enabled"] = audit_enabled_flag
        inputs["audit_run_dir"] = audit_run_dir_val
    
    graph = build_graph()
    
    print("🔥 启动全链路实测...")
    
    final_state = inputs.copy()
    
    for output in graph.stream(inputs, stream_mode="updates"):
        for node_name, content in output.items():
            if isinstance(content, dict):
                final_state.update(content)
            
            print(f"\n{'='*50}")
            print(f"✅ --- 节点 [{node_name}] 任务完成 ---")
            if content and "messages" in content and len(content["messages"]) > 0:
                last_msg = content["messages"][-1].content
                if node_name == "coder":
                    print(f"📝 详细输出:\n{last_msg}")
                else:
                    print(f"📝 摘要输出:\n{last_msg[:300]} ...")
            print(f"{'='*50}")

    print("\n🗂️ 开始归档中间态资产...")
    base_output_dir = os.path.join(project_root, "data", "outputs")
    
    vision_data = final_state.get("vision_elements")
    if vision_data:
        vision_path = os.path.join(base_output_dir, "ui_states", "debug_vision_elements.json")
        os.makedirs(os.path.dirname(vision_path), exist_ok=True)
        with open(vision_path, "w", encoding="utf-8") as f:
            json.dump(vision_data, f, ensure_ascii=False, indent=2)
        print(f"✅ 视觉分析坐标已落盘: {vision_path}")
        if audit_logger:
            audit_logger.save_state_snapshot('vision_elements_saved', vision_data)
            audit_logger.register_artifact('vision_elements', vision_path, 'debug vision elements')

    ui_contract = final_state.get("ui_state_json")
    if ui_contract:
        contract_path = os.path.join(base_output_dir, "ui_states", "final_ui_contract.json")
        os.makedirs(os.path.dirname(contract_path), exist_ok=True)
        with open(contract_path, "w", encoding="utf-8") as f:
            json.dump(ui_contract, f, ensure_ascii=False, indent=2)
        print(f"✅ UI 数据契约已落盘: {contract_path}")
        if audit_logger:
            audit_logger.save_state_snapshot('ui_contract_saved', ui_contract)
            audit_logger.register_artifact('ui_contract', contract_path, 'final ui contract')
            # run layout inspector and save report into audit run dir
            try:
                overlap_out = os.path.join(audit_logger.run_dir, 'layout_overlap_report.json')
                save_overlap_report(ui_contract, overlap_out)
                audit_logger.register_artifact('layout_overlap_report', overlap_out, 'layout overlap detection report')
            except Exception:
                pass

    final_code = final_state.get("final_code")
    if final_code:
        html_path = os.path.join(base_output_dir, "html_code", "generated_page.html")
        os.makedirs(os.path.dirname(html_path), exist_ok=True)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(final_code)
        print(f"✅ 最终前端代码已落盘: {html_path}")
        if audit_logger:
            audit_logger.register_artifact('final_html', html_path, 'generated html output')

    print("[STAGE 10] UI code archived")
    if audit_logger:
        try:
            audit_logger.finalize({'status': 'completed'})
            print(f"✅ Audit logs written to: {audit_logger.run_dir}")
        except Exception:
            print("⚠️ Audit finalize failed")


if __name__ == "__main__":
    main()
