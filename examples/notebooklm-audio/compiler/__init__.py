"""NotebookLM Audio Prompt Compiler layer.

Provides automated template parameterization and live NotebookLM RAG extraction
to programmatically populate complex audio synthesis templates with zero manual insertions.
"""

from .models import (
    AudioProjectConfig,
    CompoundEscalation,
    LexicalDictionary,
    TelemetryConfig,
    TelemetryTiers,
)

__all__ = [
    "AudioProjectConfig",
    "CompoundEscalation",
    "LexicalDictionary",
    "TelemetryConfig",
    "TelemetryTiers",
]
