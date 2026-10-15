"""Synchronous prompt compiler rendering parameterized audio scripts via Jinja2."""

from pathlib import Path
from typing import Any

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
    """Compile an AudioProjectConfig into a complete, ready-to-execute audio studio prompt."""
    env = _get_jinja_env()
    # Replace hyphens with underscores in template lookups
    template_name = f"{config.template.replace('-', '_')}.j2"
    template = env.get_template(template_name)

    t1 = getattr(config, "topic_1", None)
    t2 = getattr(config, "topic_2", None)
    t3 = getattr(config, "topic_3", None)
    lb = getattr(config, "lexical_bindings", None)

    render_context: dict[str, Any] = {
        "config": config,
        "lexical": getattr(config, "lexical_dictionary", None),
        "telemetry": getattr(config, "telemetry", None),
        "escalations": getattr(config, "escalations", []),
        "topics": getattr(config, "topics", []),
    }

    if t1 is not None:
        render_context.update(
            {
                "TOPIC_1_TITLE": t1.title,
                "TOPIC_1_THEORETICAL_FRAMEWORK": t1.theoretical_framework,
                "TOPIC_1_LOW_LEVEL_MECHANISM": t1.low_level_mechanism,
                "TOPIC_1_FAILURE_MODE": t1.failure_mode,
                "TOPIC_1_PATHOLOGICAL_EFFECT": t1.pathological_effect,
                "TOPIC_1_OPERATIONAL_ANALOGY": t1.operational_analogy,
            }
        )
    if t2 is not None:
        render_context.update(
            {
                "TOPIC_2_TITLE": t2.title,
                "TOPIC_2_INDUSTRY_PRACTICE_OR_WRAPPER": t2.industry_practice_or_wrapper,
                "TOPIC_2_TECHNICAL_REALITY": t2.technical_reality,
                "TOPIC_2_BENCHMARK_OR_FAILURE_METRIC": t2.benchmark_or_failure_metric,
                "TOPIC_2_OBSCURED_DATA_POINT": t2.obscured_data_point,
                "TOPIC_2_ECONOMIC_OR_REGULATORY_INCENTIVE": t2.economic_or_regulatory_incentive,
            }
        )
    if t3 is not None:
        render_context.update(
            {
                "TOPIC_3_TITLE": t3.title,
                "TOPIC_3_RECURSIVE_OR_FEEDBACK_LOOP": t3.recursive_or_feedback_loop,
                "TOPIC_3_BEHAVIORAL_METRIC": t3.behavioral_metric,
                "TOPIC_3_SUPERFICIAL_ATTRIBUTION": t3.superficial_attribution,
                "TOPIC_3_DEGRADATION_MECHANISM": t3.degradation_mechanism,
                "TOPIC_3_SYSTEM_COMPONENTS": t3.system_components,
            }
        )
    if lb is not None:
        render_context.update(
            {
                "CONVERGENCE_TAG": lb.convergence.tag,
                "STATE_1_PHRASE_A": lb.convergence.phrase_a,
                "STATE_1_PHRASE_B": lb.convergence.phrase_b,
                "DESYNC_TAG": lb.desync.tag,
                "STATE_2_PHRASE_A": lb.desync.phrase_a,
                "STATE_2_PHRASE_B": lb.desync.phrase_b,
                "EXHAUSTION_TAG": lb.exhaustion.tag,
                "STATE_3_PHRASE_A": lb.exhaustion.phrase_a,
                "STATE_3_PHRASE_B": lb.exhaustion.phrase_b,
                "HIGH_ENTROPY_TAG": lb.high_entropy.tag,
                "STATE_4_PHRASE_A": lb.high_entropy.phrase_a,
                "STATE_4_PHRASE_B": lb.high_entropy.phrase_b,
            }
        )

    return template.render(**render_context).strip()


def compile_from_yaml(
    file_path: Path | str,
    prompts_root: Path | str | None = None,
) -> str:
    """Load an audio project YAML file (if present) and compile it synchronously into an instructional prompt."""
    from .loaders import load_audio_config

    config = load_audio_config(file_path)
    return compile_audio_prompt(config)
