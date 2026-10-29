"""Graph exports; loading a UI subgraph must not initialize unrelated tools."""


def build_graph(*args, **kwargs):
    from .builder import build_graph as build_full_graph

    return build_full_graph(*args, **kwargs)

__all__ = [
    "build_graph",
]
