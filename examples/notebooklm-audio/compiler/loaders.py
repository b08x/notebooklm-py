"""Synchronous loader and constructor for declarative audio synthesis configurations."""

from pathlib import Path
from typing import Any

import yaml

from .models import AudioProjectConfig


def load_audio_config(file_path: Path | str) -> AudioProjectConfig:
    """Load and validate an AudioProjectConfig from a YAML configuration file."""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Audio config file not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"YAML file {p} did not decode into a mapping dictionary")
    return AudioProjectConfig.model_validate(data)


def create_audio_config(
    notebook_id: str | None = None,
    title: str | None = None,
    **kwargs: Any,
) -> AudioProjectConfig:
    """Create an in-memory AudioProjectConfig directly for a notebook without requiring a YAML file."""
    data: dict[str, Any] = {}
    if notebook_id:
        data["notebook_id"] = notebook_id
    if title:
        data["title"] = title
    data.update(kwargs)
    return AudioProjectConfig(**data)
