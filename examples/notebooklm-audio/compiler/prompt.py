"""Synchronous prompt compiler rendering parameterized audio scripts via Jinja2."""

from pathlib import Path

import jinja2

from .models import AudioProjectConfig

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _get_jinja_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )


def compile_audio_prompt(config: AudioProjectConfig) -> str:
    """Compile an AudioProjectConfig into a complete, ready-to-execute audio studio prompt.

    Replaces all manual `[INSERT ...]` slots with validated configuration variables.
    """
    env = _get_jinja_env()
    # Replace hyphens with underscores in template lookups
    template_name = f"{config.template.replace('-', '_')}.j2"
    template = env.get_template(template_name)

    render_context = {
        "config": config,
        "lexical": config.lexical_dictionary,
        "telemetry": config.telemetry,
        "escalations": config.escalations,
        "topics": config.topics,
    }

    return template.render(**render_context).strip()


def compile_from_yaml(file_path: Path | str) -> str:
    """Load an audio project YAML file and compile it synchronously into an instructional prompt."""
    from .loaders import load_audio_config

    config = load_audio_config(file_path)
    return compile_audio_prompt(config)
