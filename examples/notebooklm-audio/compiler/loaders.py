"""Synchronous loader and YAML parser for declarative audio synthesis configurations."""

from pathlib import Path

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
