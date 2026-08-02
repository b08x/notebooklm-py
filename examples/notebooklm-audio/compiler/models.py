"""Pydantic v2 schemas for automated Audio Overview synthesis templates.

Enables automated slot binding and verification before dispatching to NotebookLM Studio.
"""

from pydantic import BaseModel, Field


class LexicalDictionary(BaseModel):
    """Telemetry substitution dictionary mapped to source mechanisms and failure modes."""

    agreement: str = Field(
        default="[State 1: structural checkpoint sync & verification approval]",
        description="Source-grounded term substituting conversational agreement.",
    )
    confusion: str = Field(
        default="[State 2: unhandled routing exception & semantic desynchronization]",
        description="Source-grounded term substituting conversational confusion.",
    )
    frustration: str = Field(
        default="[State 3: thread exhaustion & token buffer starvation]",
        description="Source-grounded term substituting conversational sighs or frustration.",
    )
    brainstorm: str = Field(
        default="[State 4: high-entropy speculative flow]",
        description="Source-grounded term substituting conversational brainstorming or tangents.",
    )


class TelemetryTiers(BaseModel):
    """Tier classifications for telemetry concept mappings."""

    sigh: str = Field(default="Critical (Tier 1)")
    confusion: str = Field(default="Elevated (Tier 2)")
    unstructured_goal: str = Field(default="Warning (Tier 3)")
    brainstorm: str = Field(default="Experimental (Tier 4)")
    approval: str = Field(default="Nominal (Tier 0)")


class TelemetryConfig(BaseModel):
    """Mathematical severity formula and drift coefficient parameterization."""

    scaling_var: str = Field(
        default="context window divergence quotient",
        description="Variable controlling drift amplification.",
    )
    coefficient: float = Field(default=0.85, description="Scaling multiplication factor.")
    unstructured_goal: str = Field(
        default="unindexed entropy generation",
        description="Source term for unstructured conversational objectives.",
    )
    tiers: TelemetryTiers = Field(default_factory=TelemetryTiers)


class CompoundEscalation(BaseModel):
    """Compound state escalation rules and source-grounded diagnostics."""

    compound: str = Field(example="State 2 + State 3")
    diagnostic: str = Field(
        example="Cascading deadlock across multi-agent RPC channels when buffers exceed threshold"
    )
    tier: str = Field(example="Fatal (Tier-X)")


class AudioProjectConfig(BaseModel):
    """Declarative configuration for audio overview compilation and automatic binding."""

    title: str = Field(
        default="Unnamed Diagnostic Session", description="Project or notebook title."
    )
    topic: str | None = Field(default=None, description="Discussion topic directive.")
    notebook_id: str | None = Field(
        default=None, description="Target NotebookLM UUID if binding to existing notebook."
    )
    template: str = Field(
        default="mr-and-mrs-language-model",
        description="Name of target Jinja2 audio script template.",
    )
    source_type: str = Field(default="notebook", description="'notebook' or 'static'")
    scope: str = Field(
        default="All indexed notebook documents",
        description="Description of ingested corpus scope.",
    )
    static_payload: str | None = Field(
        default=None, description="Raw text payload if source_type is 'static'."
    )
    auto_extract: bool = Field(
        default=True,
        description="If true, use NotebookLM chat API to dynamically populate vocabulary and topics from real sources.",
    )
    include_telemetry: bool = Field(default=True)
    include_escalations: bool = Field(default=True)
    include_style_module: bool = Field(default=True)
    catchphrase: str | None = Field(default="By Cor! God's truth! An unhandled exception!")
    lexical_dictionary: LexicalDictionary = Field(default_factory=LexicalDictionary)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    escalations: list[CompoundEscalation] = Field(
        default_factory=lambda: [
            CompoundEscalation(
                compound="State 2 (Confusion) + State 3 (Frustration)",
                diagnostic="Recursive retry storm exhausting API quota without fallback",
                tier="Severity 1 (Fatal)",
            ),
            CompoundEscalation(
                compound="State 1 (Agreement) + State 4 (Tangent)",
                diagnostic="Unconstrained hyper-scaling of untested speculative hypotheses",
                tier="Severity 2 (Elevated)",
            ),
        ]
    )
    topics: list[str] = Field(
        default_factory=lambda: [
            "Mechanism 1: Concurrency arbitration and backpressure constraints in high-load RPC interfaces",
            "Mechanism 2: Memory retention degradation over extended context window traversals",
            "Mechanism 3: Failure modes during unverified third-party tool delegation",
        ]
    )
    query_guidance: list[str] = Field(
        default_factory=lambda: [
            "What architectural invariants prevent cascading desynchronization during latency surges?",
            "How does the system mitigate memory leak propagation across child conversation threads?",
        ]
    )
    audio_format: str = Field(
        default="default",
        description="Audio studio generation format (e.g. 'default', 'debate', 'deep-dive').",
    )
    audio_length: str = Field(
        default="default", description="Target run time ('short', 'default', 'long')."
    )

    def model_post_init(self, __context: object) -> None:
        if self.topic is None and self.title:
            self.topic = f"system architecture and diagnostic failure modes in '{self.title}'"
