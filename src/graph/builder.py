from langgraph.graph import StateGraph, START

from .types import State
from .nodes import (
    supervisor_node,
    research_node,
    code_node,
    coordinator_node,
    browser_node,
    reporter_node,
    planner_node,
    meeting_node,
    sa2va_node,
    vision_node,
    ui_architect_node,  # 🌟 导入我们刚写好的多模态融合架构师节点
)

def build_graph():
    """Build and return the agent workflow graph."""
    builder = StateGraph(State)
    
    # 图的绝对起点：依然交给你优秀的 coordinator 去接待用户
    builder.add_edge(START, "coordinator")
    
    # === 🧠 注册大脑/管理节点 ===
    builder.add_node("coordinator", coordinator_node)
    builder.add_node("planner", planner_node)
    builder.add_node("supervisor", supervisor_node)
    
    # === 🛠️ 注册通用工具节点 (保留你原有的生态) ===
    builder.add_node("researcher", research_node)
    builder.add_node("coder", code_node)
    builder.add_node("browser", browser_node)
    builder.add_node("reporter", reporter_node)
    
    # === 👁️👂 注册感知节点 (耳朵与眼睛) ===
    builder.add_node("meeting_agent", meeting_node)
    # 巧妙的兼容映射：将原有的 sa2va 逻辑同时注册为 prompt 里使用的 vision_agent
    builder.add_node("sa2va_agent", sa2va_node)
    builder.add_node("vision_agent", vision_node)
    
    # === 🧩 注册我们全新的多模态中枢节点 ===
    builder.add_node("ui_architect", ui_architect_node)
    
    return builder.compile()