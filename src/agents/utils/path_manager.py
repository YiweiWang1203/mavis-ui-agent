import os
from pathlib import Path

# 获取项目根目录 (/my_agent)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# 定义输入目录契约
INPUTS_DIR = PROJECT_ROOT / "data/inputs"
AUDIO_INPUT_DIR = INPUTS_DIR / "audio"
IMAGE_INPUT_DIR = INPUTS_DIR / "images"

# 定义输出目录契约
OUTPUTS_DIR = PROJECT_ROOT / "data/outputs"
HTML_OUTPUT_DIR = OUTPUTS_DIR / "html_code"
DEBUG_SKETCH_DIR = OUTPUTS_DIR / "processed_sketches"

# 确保所有目录都存在，不存在则自动创建
for d in [AUDIO_INPUT_DIR, IMAGE_INPUT_DIR, HTML_OUTPUT_DIR, DEBUG_SKETCH_DIR]:
    d.mkdir(parents=True, exist_ok=True)
    
def get_path_map():
    """方便在节点中打印或传递路径字典"""
    return {
        "root": str(PROJECT_ROOT),
        "sketch_debug_out": str(DEBUG_SKETCH_DIR),
        "html_code_out": str(HTML_OUTPUT_DIR)
    }