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
    if mode in {"baseline", "placement_v1", "typed_controls_v1"}:
        return prompt
    if mode != "native_controls_v1":
        raise ValueError("UI_CODER_CONTRACT_MODE must be baseline, native_controls_v1, placement_v1 or typed_controls_v1")
    contract_path = prompt_path.with_name("coder_native_controls.md")
    return prompt + "\n\n" + contract_path.read_text(encoding="utf-8")


def strip_markdown_code_fence(code: str) -> str:
    """Return raw HTML when the model wraps output in a Markdown code fence."""
    if not isinstance(code, str):
        return ""
    text = code.strip()
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def save_html_asset(code: str) -> str | None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = HTML_OUTPUT_DIR / f"html_generated_{timestamp}.html"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(code, encoding="utf-8")
    return str(file_path.resolve())


@traced_stage('coder.generate', fields={'ui_state_json'})
def generate_frontend_code(ui_state_json: dict, audit_logger=None) -> dict | str:
    """Generate runnable frontend HTML from a UI-State JSON contract."""
    renderer_mode = os.getenv("UI_RENDERER_MODE", "auto").strip().lower()
    # Reject the retired artifact-repair switch instead of silently altering HTML.
    if os.getenv("UI_INPUT_CONTRACT_MODE", "off").strip().lower() != "off":
        raise ValueError("HTML repair is retired; unset UI_INPUT_CONTRACT_MODE")
    if os.getenv("UI_CODER_CONTRACT_MODE", "baseline").strip().lower() != "baseline" and renderer_mode != "llm":
        raise ValueError("Generation contract comparison requires UI_RENDERER_MODE=llm")
    if renderer_mode in {"auto", "deterministic"}:
        from src.renderers import render_ui_state_html, supports_deterministic_rendering

        supported = supports_deterministic_rendering(ui_state_json)
        if renderer_mode == "deterministic" or supported:
            code = render_ui_state_html(ui_state_json)
            trace_html_contract(code,ui_state_json,renderer='deterministic')
            saved_path = save_html_asset(code)
            logging.getLogger(__name__).info("Deterministic HTML asset saved to: %s", saved_path)
            return {"code": code, "file_path": saved_path, "renderer": "deterministic"}

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
