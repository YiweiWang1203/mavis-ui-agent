"""Vision/ASR imports must not initialize an unrelated search account."""
from importlib import import_module
from .asr_tool import asr_tool
from .read_file_tool import read_file_tool
from .bash_tool import bash_tool
from .file_management import write_file_tool
from .python_repl import python_repl_tool
from .sa2va_tool import sa2va_tool
from .vision_tool import extract_ui_layout, validate_vision_layout

__all__ = ["asr_tool", "read_file_tool", "bash_tool", "write_file_tool",
           "python_repl_tool", "tavily_tool", "sa2va_tool",
           "extract_ui_layout", "validate_vision_layout"]


def __getattr__(name):
    if name != "tavily_tool":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = import_module(f"{__name__}.search").tavily_tool
    globals()[name] = value
    return value
