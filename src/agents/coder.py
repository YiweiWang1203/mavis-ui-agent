import json
import logging
import os
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from src.agents.utils.path_manager import HTML_OUTPUT_DIR
from src.utils.pipeline_trace import traced_stage, trace_html_contract


DEFAULT_CODER_MODEL = os.getenv("CODER_MODEL", "Qwen/Qwen2.5-Coder-32B")
DEFAULT_BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")


def _get_openai_client():
    from src.service.main_model_runtime import main_client
    bounded = main_client("coder")
    if bounded is not None:
        return bounded
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("SILICONFLOW_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    from openai import OpenAI

    return OpenAI(api_key=api_key, base_url=DEFAULT_BASE_URL)


def read_coder_prompt():
    """Read the Coder system prompt."""
    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "coder.md"
    try:
        prompt = prompt_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        prompt = "Generate a complete runnable HTML file from the provided UI-State JSON."
    mode = os.getenv("UI_CODER_CONTRACT_MODE", "baseline").strip().lower()
    if mode == "main_system_v1":
        return prompt + "\n\n" + prompt_path.with_name("coder_native_controls.md").read_text(encoding="utf-8") + "\n\n" + prompt_path.with_name("coder_main_system.md").read_text(encoding="utf-8")
    if mode in {"baseline", "placement_v1", "typed_controls_v1"}:
        return prompt
    if mode != "native_controls_v1":
        raise ValueError("UI_CODER_CONTRACT_MODE must be baseline, native_controls_v1, placement_v1 or typed_controls_v1")
    contract_path = prompt_path.with_name("coder_native_controls.md")
    return prompt + "\n\n" + contract_path.read_text(encoding="utf-8")


def strip_markdown_code_fence(code: str) -> str:
    """Remove a single explicit Markdown wrapper without searching HTML strings."""
    if not isinstance(code, str):
        return ""
    text = code.strip()
    # Raw documents are never cropped at an apparent tag in script/comment data.
    if text.lower().startswith(("<!doctype", "<html")):
        return text
    import re
    fences = list(re.finditer(r"(?m)^```[^\r\n]*\r?$", text))
    if not fences:
        return text
    if len(fences) != 2 or fences[0].group().strip().lower() not in {"```html", "```"} or fences[1].group().strip() != "```":
        raise ValueError("AMBIGUOUS_OR_INCOMPLETE_HTML_FENCES")
    start = fences[0].end()
    if text[start:start+2] == "\r\n":
        start += 2
    elif text[start:start+1] == "\n":
        start += 1
    end = fences[1].start()
    if text[max(start,end-2):end] == "\r\n":
        end -= 2
    elif text[max(start,end-1):end] == "\n":
        end -= 1
    return text[start:end]


def save_html_asset(code: str) -> str | None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = os.getenv("MAVIS_MAIN_RUN_ID")
    output_dir = HTML_OUTPUT_DIR
    if run_id:
        import re
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
            raise ValueError("INVALID_MAIN_RUN_ID")
        output_dir = output_dir / run_id
    file_path = output_dir / f"html_generated_{timestamp}.html"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("x", encoding="utf-8") as stream:
        stream.write(code)
    return str(file_path.resolve())


def is_complete_html_document(code: str) -> bool:
    from html.parser import HTMLParser
    class Roots(HTMLParser):
        starts = 0
        ends = 0
        def handle_starttag(self, tag, attrs):
            if tag == 'html': self.starts += 1
        def handle_endtag(self, tag):
            if tag == 'html': self.ends += 1
    parser = Roots()
    parser.feed(code)
    parser.close()
    return parser.starts == parser.ends == 1


@traced_stage('coder.generate', fields={'ui_state_json'})
def generate_frontend_code(ui_state_json: dict, audit_logger=None, *, original_user_request: str = "", asr_transcript: str = "") -> dict | str:
    """Generate runnable frontend HTML from a UI-State JSON contract."""
    renderer_mode = os.getenv("UI_RENDERER_MODE", "auto").strip().lower()
    # Reject the retired artifact-repair switch instead of silently altering HTML.
    if os.getenv("UI_INPUT_CONTRACT_MODE", "off").strip().lower() != "off":
        raise ValueError("HTML repair is retired; unset UI_INPUT_CONTRACT_MODE")
    if os.getenv("UI_CODER_CONTRACT_MODE", "baseline").strip().lower() != "baseline" and renderer_mode not in {"llm", "controlled_components_v1"}:
        raise ValueError("Generation contract comparison requires UI_RENDERER_MODE=llm")
    if renderer_mode == "controlled_components_v1":
        if os.getenv("UI_CODER_CONTRACT_MODE", "baseline") != "controlled_components_v1":
            raise ValueError("Controlled renderer requires explicit matching contract mode")
        from src.renderers.controlled_components import render_controlled_components
        code = render_controlled_components(ui_state_json)
        trace_html_contract(code, ui_state_json, renderer="controlled_components_v1")
        return {"code": code, "file_path": save_html_asset(code), "renderer": "controlled_components_v1"}
    if renderer_mode in {"auto", "deterministic"}:
        from src.renderers import render_ui_state_html, supports_deterministic_rendering

        supported = supports_deterministic_rendering(ui_state_json)
        if renderer_mode == "deterministic" or supported:
            code = render_ui_state_html(ui_state_json)
            trace_html_contract(code,ui_state_json,renderer='deterministic')
            saved_path = save_html_asset(code)
            logging.getLogger(__name__).info("Deterministic HTML asset saved to: %s", saved_path)
            return {"code": code, "file_path": saved_path, "renderer": "deterministic"}

    region_tree = ui_state_json.get('region_tree') if ui_state_json.get('page_meta', {}).get('structure_mode') == 'region_tree_v1' else None
    if region_tree:
        prompt_dir = Path(__file__).resolve().parents[1] / "prompts"
        system_prompt = (prompt_dir / "coder_region_tree.md").read_text(encoding="utf-8")
        system_prompt += "\n\n" + (prompt_dir / "coder_native_controls.md").read_text(encoding="utf-8")
        system_prompt += "\nThe native control rules preserve geometry only as defined by region_tree. Use the tree as the only layout contract. Do not infer or apply legacy bounding boxes."
        if ui_state_json.get("page_meta", {}).get("contract_version") == 2:
            from src.utils.region_execution import region_styles
            system_prompt += (
                "\nImplement every actions entry: its trigger must cause its state_change and observable_result. "
                "Explicitly requested local subviews, editing panels and dialogs are permitted. "
                "The restriction on extra pages applies only to unrequested additions. "
                "Implement repeated items as distinct rows and bind requested row interactions. "
                "Show recognizable asset_content, using embedded SVG or local content when appropriate, "
                "not generic empty or text-only image placeholders. Preserve supplied content and labels. "
                "Avoid horizontal overflow and clipped controls. Do not use inline important layout styles. "
                "Every marked tree child must be a direct DOM child of its marked tree parent. "
                "Put any control wrapper on that same marked node, never between two tree nodes. "
                "Cross-axis start/end/center uses content-sized width under a column or height under a row; stretch fills it. "
                "The following tree-derived CSS is appended by the system; style around it and do not override it:\n"
                + region_styles(region_tree))
    else:
        system_prompt = read_coder_prompt()
    if (ui_state_json.get('page_meta',{}).get('layout_solver') or {}).get('version') == 'hierarchy-v1':
        system_prompt += "\nHierarchy contract overrides conflicting placement advice: preserve each id once, exact bbox size and page-global position; do not expand or globally repack controls. Render all elements absolutely under one positioned page root, and attach data-parent-id for non-root elements. Parent backgrounds are permitted behind children. Do not render children a second time through children_ids. Use border-box, zero root/body margins. Render visible region boundaries for drawn containers and image placeholders.\n"
    if os.getenv("UI_CODER_CONTRACT_MODE", "baseline") in {"placement_v1", "typed_controls_v1"}:
        from src.utils.placement_contract import placement_instructions
        system_prompt += placement_instructions(ui_state_json)
    if os.getenv("UI_CODER_CONTRACT_MODE", "baseline") == "typed_controls_v1":
        from src.utils.placement_contract import component_instructions
        system_prompt += component_instructions(ui_state_json)
    user_content = (
        "Generate runnable frontend code from the following UI-State JSON.\n\n"
        f"{json.dumps(ui_state_json, ensure_ascii=False, indent=2)}"
    )
    if os.getenv("UI_CODER_CONTRACT_MODE") == "main_system_v1":
        user_content += "\n\n[Original User Request]\n" + original_user_request + "\n\n[Fresh ASR Transcript]\n" + asr_transcript
    model_to_use = os.getenv("CODER_MODEL", DEFAULT_CODER_MODEL)

    client = _get_openai_client()
    if client is None:
        print("Coder: missing API key. Set SILICONFLOW_API_KEY, OPENAI_API_KEY, or DEEPSEEK_API_KEY.")
        return ""

    try:
        print(f"Generating frontend code with model {model_to_use}...")
        response = client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
        )

        raw_code = response.choices[0].message.content or ""
        code = strip_markdown_code_fence(raw_code)
        if os.getenv("UI_CODER_CONTRACT_MODE") == "main_system_v1" and not is_complete_html_document(code):
            raise ValueError("INCOMPLETE_HTML_DOCUMENT")
        if region_tree:
            from src.utils.region_tree import check_region_markup
            check_region_markup(code, region_tree, direct_parent=ui_state_json.get("page_meta", {}).get("contract_version") == 2)
            if ui_state_json.get("page_meta", {}).get("contract_version") == 2:
                from src.utils.region_execution import attach_region_styles
                from src.utils.pipeline_trace import trace_event
                original_html = code
                code = attach_region_styles(code, region_tree)
                trace_event("coder.region_style_compilation", original_html=original_html,
                            compiled_html=code, derived_css=region_styles(region_tree))
        trace_html_contract(code,ui_state_json,renderer='llm',
                    finish_reason=getattr(response.choices[0],'finish_reason',None))

        try:
            if audit_logger:
                audit_logger.log_llm_call(
                    "coder",
                    model_to_use,
                    system_prompt,
                    user_content,
                    None,
                    raw_code,
                    {"note": "coder generation"},
                )
        except Exception:
            pass

        saved_path = None
        try:
            saved_path = save_html_asset(code)
            logging.getLogger(__name__).info("HTML asset saved to: %s", saved_path)
        except Exception as exc:
            logging.getLogger(__name__).error("HTML asset save failed: %s", exc)

        return {"code": code, "file_path": saved_path}

    except Exception as exc:
        if region_tree:
            raise
        print(f"Code generation failed: {exc}")
        return ""


if __name__ == "__main__":
    test_json_path = Path("outputs/ui_states/example_R8001_M8004_MS801.json")
    if test_json_path.exists():
        result = generate_frontend_code(json.loads(test_json_path.read_text(encoding="utf-8")))
        if isinstance(result, dict):
            print(result.get("code", ""))
            print("\nSaved to:", result.get("file_path"))
        else:
            print(result)
    else:
        print(f"Test file not found: {test_json_path}")
