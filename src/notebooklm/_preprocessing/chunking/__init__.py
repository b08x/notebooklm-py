"""Chunking strategies (recursive, cluster-semantic, dynamic-window).

``STRATEGIES`` maps the registry name stored in ``chunk_runs.strategy`` to a
factory taking keyword parameters. Implementations live in ``recursive.py``,
``semantic.py`` and ``dynamic.py``; they are imported lazily because they load
spaCy / DSPy.
"""

from __future__ import annotations

import importlib
from typing import Any

from .base import ChildChunk, ChunkResult, ChunkStats, ChunkStrategy, ParentChunk

#: name -> "module:Class"
STRATEGIES: dict[str, str] = {
    "recursive": "recursive:RecursiveSplitter",
    "cluster_semantic": "semantic:ClusterSemanticChunker",
    "dynamic_window": "dynamic:DynamicWindowChunker",
}


def make_strategy(name: str, **params: Any) -> ChunkStrategy:
    if name not in STRATEGIES:
        raise KeyError(f"Unknown chunking strategy {name!r}; known: {sorted(STRATEGIES)}")
    module_name, cls_name = STRATEGIES[name].split(":")
    module = importlib.import_module(f"{__package__}.{module_name}")
    strategy: ChunkStrategy = getattr(module, cls_name)(**params)
    return strategy


__all__ = [
    "STRATEGIES",
    "ChildChunk",
    "ChunkResult",
    "ChunkStats",
    "ChunkStrategy",
    "ParentChunk",
    "make_strategy",
]
