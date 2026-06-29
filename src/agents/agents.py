from langgraph.prebuilt import create_react_agent

from src.prompts import apply_prompt_template
from src.tools import (
    bash_tool,
#   crawl_tool,  # <-- 封印
    python_repl_tool,
    tavily_tool,
)
# from src.tools.browser import browser_tool  # <-- 封印
from src.tools.asr_tool import asr_tool
from src.tools.sa2va_tool import sa2va_tool
from .llm import get_llm_by_type
from src.config.agents import AGENT_LLM_MAP

# Create agents using configured LLM types
research_agent = create_react_agent(
    get_llm_by_type(AGENT_LLM_MAP["researcher"]),
    # 👇 移除了 crawl_tool，只保留 tavily_tool
    tools=[tavily_tool], 
    prompt=lambda state: apply_prompt_template("researcher", state),
)

coder_agent = create_react_agent(
    get_llm_by_type(AGENT_LLM_MAP["coder"]),
    tools=[python_repl_tool, bash_tool],
    prompt=lambda state: apply_prompt_template("coder", state),
)

browser_agent = create_react_agent(
    get_llm_by_type(AGENT_LLM_MAP["browser"]),
    # 👇 核心修改：给它一个空工具列表。这样 Agent 节点依然存在于图中，但不再调用浏览器。
    tools=[], 
    prompt=lambda state: apply_prompt_template("browser", state),
)

meeting_agent = create_react_agent(
    get_llm_by_type(AGENT_LLM_MAP["meeting_agent"]),  
    tools=[asr_tool],
    prompt=lambda state: apply_prompt_template("meeting", state),
)

"""
sa2va_agent 仅作为视频问答工具代理，其推理能力完全由 sa2va_tool 内部的 sa2va:1b 模型实现。
此 agent 不依赖外部 LLM，get_llm_by_type("basic") 仅为结构兼容保留。
"""
sa2va_agent = create_react_agent(
    get_llm_by_type("basic"),  
    tools=[sa2va_tool],
    prompt=lambda state: apply_prompt_template("sa2va_agent", state),
)