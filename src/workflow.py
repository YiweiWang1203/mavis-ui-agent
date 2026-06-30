import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
workspace_root = project_root.parent

for path in (str(project_root), str(workspace_root)):
    if path not in sys.path:
        sys.path.insert(0, path)

load_dotenv(project_root / ".env")

from src.config import TEAM_MEMBERS
from src.graph import build_graph
from src.service.input_adapter import prepare_workflow_input


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def enable_debug_logging():
    logging.getLogger("src").setLevel(logging.DEBUG)


graph = build_graph()


def run_agent_workflow(
    messages: list[dict] | None = None,
    debug: bool = False,
    *,
    text: str | None = None,
    image_path: str | None = None,
    video_path: str | None = None,
    audio_path: str | None = None,
    preprocess_output_dir: str | None = None,
    rotate_degrees: int = 180,
    orientation_correction_enabled: bool = True,
    enable_asr: bool = False,
):
    """Run the LangGraph workflow from either raw messages or media paths."""
    if debug:
        enable_debug_logging()

    if video_path or image_path:
        prepared = prepare_workflow_input(
            text=text,
            image_path=image_path,
            video_path=video_path,
            audio_path=audio_path,
            preprocess_output_dir=preprocess_output_dir,
            rotate_degrees=rotate_degrees,
            orientation_correction_enabled=orientation_correction_enabled,
            enable_asr=enable_asr,
        )
        inputs = prepared["state"]
    else:
        if not messages or not any(m.get("content") for m in messages):
            raise ValueError("Input messages could not be empty")
        inputs = {
            "TEAM_MEMBERS": TEAM_MEMBERS,
            "messages": messages,
            "deep_thinking_mode": True,
            "search_before_planning": True,
        }

    logger.info("Starting LangGraph workflow")
    result = graph.invoke(inputs)
    logger.info("Workflow completed")
    return result


if __name__ == "__main__":
    print("\n" + "=" * 20 + " AGENT GRAPH (Mermaid) " + "=" * 20)
    try:
        print(graph.get_graph().draw_mermaid())
    except Exception as exc:
        print(f"Graph was built, but Mermaid rendering failed: {exc}")
    print("=" * 60 + "\n")
