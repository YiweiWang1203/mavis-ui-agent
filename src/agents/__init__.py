"""Agent package exports.

The concrete ReAct agents are expensive to import because they initialize
LangGraph/LangChain tools. Keep this package lazy so utility modules such as
``src.agents.ui_architect`` can be imported in lightweight tests.
"""

_AGENT_EXPORTS = {
    "research_agent",
    "coder_agent",
    "browser_agent",
    "meeting_agent",
    "sa2va_agent",
}

__all__ = sorted(_AGENT_EXPORTS)


def __getattr__(name):
    if name in _AGENT_EXPORTS:
        from .agents import browser_agent, coder_agent, meeting_agent, research_agent, sa2va_agent

        values = {
            "research_agent": research_agent,
            "coder_agent": coder_agent,
            "browser_agent": browser_agent,
            "meeting_agent": meeting_agent,
            "sa2va_agent": sa2va_agent,
        }
        return values[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
