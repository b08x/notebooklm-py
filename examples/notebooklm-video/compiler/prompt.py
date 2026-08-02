"""Synchronous Prompt Compiler assembling declarative packs into NotebookLM payloads."""

from pathlib import Path

import jinja2

from .inference import infer_style_for_project
from .loaders import load_domain_pack, load_style_pack, load_voice_pack
from .models import CompiledPrompt, DomainPack, ProjectConfig, VoicePack

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _get_jinja_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )


def compile_project_config(
    project: ProjectConfig,
    prompts_root: Path | str | None = None,
) -> CompiledPrompt:
    """Compile a ProjectConfig along with its Style, Domain, and Voice packs into a CompiledPrompt.

    This function executes entirely in memory without making network requests.
    """
    # Load Domain Pack first (useful for tags during auto-inference)
    try:
        domain = load_domain_pack(project.domain, root=prompts_root)
    except FileNotFoundError:
        # Fall back to a transient empty domain pack if user passed an inline custom domain name
        domain = DomainPack(name=project.domain, description=f"Custom domain: {project.domain}")

    # Load or infer Style Pack
    if project.style.lower() in {"auto-infer", "auto", "infer"}:
        style = infer_style_for_project(project, domain_pack=domain, prompts_root=prompts_root)
    else:
        style = load_style_pack(project.style, root=prompts_root)

    # Load Voice Pack
    try:
        voice = load_voice_pack(project.voice, root=prompts_root)
    except FileNotFoundError:
        voice = VoicePack(
            name=project.voice,
            tone="Informative and clear educational overview.",
            pacing="Balanced pacing appropriate for the subject matter.",
            narrative_structure=["Introduction", "Core Concepts", "Summary and Takeaways"],
        )

    # Render Jinja2 templates
    env = _get_jinja_env()
    style_template = env.get_template("style_prompt.j2")
    instructions_template = env.get_template("instructions.j2")

    render_context = {
        "project": project,
        "style": style,
        "domain": domain,
        "voice": voice,
    }

    compiled_style_prompt = style_template.render(**render_context).strip()
    compiled_instructions = instructions_template.render(**render_context).strip()

    return CompiledPrompt(
        project_title=project.title,
        style_name=style.name,
        domain_name=domain.name,
        voice_name=voice.name,
        video_format=project.video_format,
        style_prompt=compiled_style_prompt,
        instructions=compiled_instructions,
        documents=project.documents,
        audience=project.audience,
        length=project.length,
    )


def compile_from_yaml(
    project_file: Path | str,
    prompts_root: Path | str | None = None,
) -> CompiledPrompt:
    """Load a project YAML file and compile it synchronously into a CompiledPrompt."""
    from .loaders import load_project_config

    project_config = load_project_config(project_file)
    return compile_project_config(project_config, prompts_root=prompts_root)
