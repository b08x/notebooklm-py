"""Synchronous loaders for YAML prompt packs and project definitions."""

import os
from pathlib import Path
from typing import Any

import yaml

from .models import DomainPack, ProjectConfig, StylePack, VoicePack

# Resolve default prompt repository root relative to project layout
DEFAULT_PROMPTS_ROOT = Path(__file__).resolve().parents[3] / "docs" / "prompts" / "video"


def _get_root(root: Path | str | None = None) -> Path:
    if root is not None:
        return Path(root)
    env_root = os.environ.get("NOTEBOOKLM_PROMPT_LIBRARY")
    if env_root:
        return Path(env_root)
    return DEFAULT_PROMPTS_ROOT


def _read_yaml(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"YAML file {file_path} did not decode into a mapping dictionary")
    return data


def load_style_pack(name: str, root: Path | str | None = None) -> StylePack:
    """Load and validate a Style Pack by name from the library root."""
    base = _get_root(root) / "styles"
    target = base / f"{name}.yaml"
    if not target.exists():
        # Try .yml fallback
        target = base / f"{name}.yml"
    data = _read_yaml(target)
    return StylePack.model_validate(data)


def list_style_packs(root: Path | str | None = None) -> list[StylePack]:
    """Load all available Style Packs in the repository for selection or inference."""
    base = _get_root(root) / "styles"
    if not base.exists():
        return []
    packs = []
    for file_path in sorted(base.glob("*.y*ml")):
        try:
            packs.append(StylePack.model_validate(_read_yaml(file_path)))
        except (ValueError, Exception):
            # Ignore ill-formed files in directory listings
            continue
    return packs


def load_domain_pack(name: str, root: Path | str | None = None) -> DomainPack:
    """Load and validate a Domain Pack by name."""
    base = _get_root(root) / "domains"
    target = base / f"{name}.yaml"
    if not target.exists():
        target = base / f"{name}.yml"
    data = _read_yaml(target)
    return DomainPack.model_validate(data)


def load_voice_pack(name: str, root: Path | str | None = None) -> VoicePack:
    """Load and validate a Voice Pack by name."""
    base = _get_root(root) / "voices"
    target = base / f"{name}.yaml"
    if not target.exists():
        target = base / f"{name}.yml"
    data = _read_yaml(target)
    return VoicePack.model_validate(data)


def load_project_config(file_path: Path | str) -> ProjectConfig:
    """Load and validate a ProjectConfig from a YAML project file."""
    p = Path(file_path)
    data = _read_yaml(p)
    return ProjectConfig.model_validate(data)
