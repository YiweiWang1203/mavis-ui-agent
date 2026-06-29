from typing import Literal, Union, Optional
from typing_extensions import TypedDict
from langgraph.graph import MessagesState

from src.config import TEAM_MEMBERS

# Define routing options
OPTIONS = TEAM_MEMBERS + ["FINISH"]

class Router(TypedDict):
    """Worker to route to next. If no workers needed, route to FINISH."""
    next: str

class State(MessagesState):
    """State for the agent system, extends MessagesState with next field."""

    # Constants
    TEAM_MEMBERS: list[str]

    # --- 核心调度变量 (完全保留你原有的优秀设计) ---
    next: str
    full_plan: str
    parsed_plan: dict
    current_step: int
    
    # --- 🌟 新增：多模态 UI 自动化专属数据契约 ---
    voice_intent: Optional[str]        # 存储提取出的语音意图
    image_path: Optional[str]
    vision_elements: Optional[dict]    # 存储提取出的控件坐标字典 (VisionLayout.dict())
    vision_status: Optional[dict]
    vision_raw_output: Optional[str]
    vision_retry_count: int
    ui_state_json: Optional[dict]      # 存储 UI Architect 融合后的 JSON 契约
    final_code: Optional[str]          # 存储 Coder 最终生成的前端代码
    
    # --- 🌟 容错机制：存储分诊与优雅降级的温馨提示 ---
    warnings: list[str]