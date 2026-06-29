from .env import (
    # Reasoning LLM
    REASONING_MODEL,
    REASONING_BASE_URL,
    REASONING_API_KEY,
    # Basic LLM
    BASIC_MODEL,
    BASIC_BASE_URL,
    BASIC_API_KEY,
    # Vision-language LLM
    VL_MODEL,
    VL_BASE_URL,
    VL_API_KEY,
    # Other configurations
    CHROME_INSTANCE_PATH,
)
from .tools import TAVILY_MAX_RESULTS

# Team configuration (修改了这里 👇)
TEAM_MEMBERS = [
    "researcher", 
    "coder", 
    "reporter", 
    "meeting_agent", 
    "browser_agent",
    "sa2va_agent",
    "vision_agent",    # 👁️ 新增：供 Planner 调用的视觉节点别名
    "ui_architect"     # 🧠 新增：多模态融合架构师节点
] 

__all__ = [
    # Reasoning LLM
    "REASONING_MODEL",
    "REASONING_BASE_URL",
    "REASONING_API_KEY",
    # Basic LLM
    "BASIC_MODEL",
    "BASIC_BASE_URL",
    "BASIC_API_KEY",
    # Vision-language LLM
    "VL_MODEL",
    "VL_BASE_URL",
    "VL_API_KEY",
    # Other configurations
    "TEAM_MEMBERS",
    "TAVILY_MAX_RESULTS",
    "CHROME_INSTANCE_PATH",
]
