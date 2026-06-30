from langgraph.graph import START, StateGraph

from .nodes import (
    browser_node,
    code_node,
    coordinator_node,
    meeting_node,
    planner_node,
    reporter_node,
    research_node,
    sa2va_node,
    supervisor_node,
    ui_architect_node,
    vision_node,
)
from .types import State


def build_graph():
    """Build and return the agent workflow graph."""
    builder = StateGraph(State)

    builder.add_edge(START, "coordinator")

    builder.add_node("coordinator", coordinator_node)
    builder.add_node("planner", planner_node)
    builder.add_node("supervisor", supervisor_node)

    builder.add_node("researcher", research_node)
    builder.add_node("coder", code_node)
    builder.add_node("browser", browser_node)
    builder.add_node("reporter", reporter_node)

    builder.add_node("meeting_agent", meeting_node)
    builder.add_node("sa2va_agent", sa2va_node)
    builder.add_node("vision_agent", vision_node)
    builder.add_node("ui_architect", ui_architect_node)

    return builder.compile()
