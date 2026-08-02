"""Pydantic v2 schemas for declarative Video Overview configurations.

Enforces robust type hints and validation before making any I/O requests to NotebookLM.
"""

from pydantic import BaseModel, Field


class StylePack(BaseModel):
    """Declarative visual style language without domain topic specifics."""

    name: str = Field(description="Unique identifier for the visual grammar style.")
    description: str | None = Field(default=None, description="Summary of the visual philosophy.")
    camera: list[str] = Field(
        default_factory=list, description="Camera projections, angles, and framing techniques."
    )
    palette: list[str] = Field(default_factory=list, description="Color palette specifications.")
    medium: list[str] = Field(
        default_factory=list, description="Artistic or structural rendering mediums."
    )
    visual_grammar: list[str] = Field(
        default_factory=list, description="Iconography, landmarks, and spatial conventions."
    )
    animation: list[str] = Field(
        default_factory=list, description="Motion language and structural transitions."
    )
    constraints: list[str] = Field(
        default_factory=lambda: [
            "Avoid photorealism",
            "Maintain a single cohesive visual world",
            "Prefer spatial relationships and physical metaphors over plain slides",
        ],
        description="Negative constraints and stylistic boundary guardrails.",
    )
    tags: list[str] = Field(
        default_factory=list, description="Semantic tags for automatic style inference."
    )


class DomainPack(BaseModel):
    """Domain concept mappings and educational principles."""

    name: str = Field(description="Unique identifier for the domain pack.")
    description: str | None = Field(
        default=None, description="Scope and discipline of the pedagogical domain."
    )
    concept_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Key dictionary mapping abstract domain concepts to tangible physical representations.",
    )
    domain_rules: list[str] = Field(
        default_factory=list, description="Domain-specific rules for accurate explanation."
    )
    tags: list[str] = Field(default_factory=list, description="Keywords defining this domain.")


class VoicePack(BaseModel):
    """Narrative tone, delivery pacing, and structural flow specification."""

    name: str = Field(description="Unique identifier for the voice profile.")
    tone: str = Field(description="Instructional atmosphere and narrative voice.")
    pacing: str = Field(description="Rhythm of narration and cadence relative to visuals.")
    narrative_structure: list[str] = Field(
        default_factory=list, description="Chronological flow of sections across the overview."
    )
    vocabulary_guidelines: list[str] = Field(
        default_factory=list, description="Lexical rules and terminological precision instructions."
    )


class ProjectConfig(BaseModel):
    """Root declarative configuration tying together sources, style, domain, and voice."""

    title: str = Field(description="Title of the video production project.")
    style: str = Field(
        description="Name of the Style Pack, or 'auto-infer' to deduce via semantic corpus analysis."
    )
    domain: str = Field(description="Name of the Domain Pack.")
    voice: str = Field(default="documentary", description="Name of the Voice Pack.")
    documents: list[str] = Field(
        default_factory=list, description="List of local file paths or URLs to ingest as sources."
    )
    audience: str = Field(
        default="general engineers and technologists",
        description="Target demographic and expertise level.",
    )
    length: str = Field(default="8-10 minutes", description="Target video run time.")
    video_format: str = Field(
        default="explainer",
        description="Target NotebookLM format (explainer, brief, cinematic, short).",
    )
    custom_instructions: str | None = Field(
        default=None, description="Optional extra project-specific instructions."
    )


class CompiledPrompt(BaseModel):
    """Ready-to-execute compiled artifact to pass into notebooklm-py execution backend."""

    project_title: str
    style_name: str
    domain_name: str
    voice_name: str
    video_format: str
    style_prompt: str
    instructions: str
    documents: list[str]
    audience: str
    length: str
