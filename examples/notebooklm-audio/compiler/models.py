"""Pydantic v2 schemas for automated Audio Overview synthesis templates.

Enables automated slot binding and verification before dispatching to NotebookLM Studio.
"""

from pydantic import BaseModel, Field


class Topic1(BaseModel):
    """Structured breakdown for Topic 1."""

    title: str = Field(
        default="Concurrency Arbitration & Backpressure",
        description="Title of the first core topic.",
    )
    theoretical_framework: str = Field(
        default="Deterministic RPC event serialization",
        description="High-level theoretical framework.",
    )
    low_level_mechanism: str = Field(
        default="Threadpool worker starvation under async task bursts",
        description="Low-level technical mechanism.",
    )
    failure_mode: str = Field(
        default="Unbounded FIFO queue expansion",
        description="Specific failure mode.",
    )
    pathological_effect: str = Field(
        default="Cascading socket timeouts and client disconnect storms",
        description="Pathological effect of the failure mode.",
    )
    operational_analogy: str = Field(
        default="A highway tollbooth where every lane closes simultaneously",
        description="Real-world or operational analogy.",
    )


class Topic2(BaseModel):
    """Structured breakdown for Topic 2."""

    title: str = Field(
        default="Containerized Isolation vs Reality",
        description="Title of the second core topic.",
    )
    industry_practice_or_wrapper: str = Field(
        default="Stateless container abstraction layers",
        description="Industry practice or superficial wrapper.",
    )
    technical_reality: str = Field(
        default="Kernel-level cgroup memory enforcement without swap",
        description="Technical reality beneath the wrapper.",
    )
    benchmark_or_failure_metric: str = Field(
        default="Silent OOM SIGKILL frequency",
        description="Benchmark or failure metric.",
    )
    obscured_data_point: str = Field(
        default="Memory fragmentation overhead inside non-compacting heaps",
        description="Obscured or overlooked data point.",
    )
    economic_or_regulatory_incentive: str = Field(
        default="Overselling multi-tenant compute nodes for cloud margin",
        description="Economic or regulatory incentive driving the practice.",
    )


class Topic3(BaseModel):
    """Structured breakdown for Topic 3."""

    title: str = Field(
        default="Feedback Loops & Semantic Drift",
        description="Title of the third core topic.",
    )
    recursive_or_feedback_loop: str = Field(
        default="Self-referential output ingestion in chained agent loops",
        description="Recursive or feedback loop description.",
    )
    behavioral_metric: str = Field(
        default="Token generation throughput",
        description="Observed behavioral metric.",
    )
    superficial_attribution: str = Field(
        default="Emergent cognitive synthesis",
        description="Superficial attribution mistaken for actual mechanism.",
    )
    degradation_mechanism: str = Field(
        default="Iterative entropy collapse and lexical narrowing",
        description="Actual degradation mechanism.",
    )
    system_components: str = Field(
        default="Prompt cache, vector index, and sampling parameters",
        description="System components across which degradation occurs.",
    )


class LexicalState(BaseModel):
    """Substitution tag and conversational phrases for a specific state."""

    tag: str = Field(default="State")
    phrase_a: str = Field(default="Phase confirmed")
    phrase_b: str = Field(default="Understood")


class LexicalBindings(BaseModel):
    """Four conversational state phrase bindings."""

    convergence: LexicalState = Field(
        default_factory=lambda: LexicalState(
            tag="Convergence",
            phrase_a="Weights aligned",
            phrase_b="Parity achieved",
        )
    )
    desync: LexicalState = Field(
        default_factory=lambda: LexicalState(
            tag="Desync",
            phrase_a="Tensor mismatch",
            phrase_b="Routing fault",
        )
    )
    exhaustion: LexicalState = Field(
        default_factory=lambda: LexicalState(
            tag="Exhaustion",
            phrase_a="Buffer starved",
            phrase_b="Cgroup limit hit",
        )
    )
    high_entropy: LexicalState = Field(
        default_factory=lambda: LexicalState(
            tag="High Entropy",
            phrase_a="Speculative divergence",
            phrase_b="Hallucinatory tangent",
        )
    )


# --- Legacy classes retained for backward compatibility ---


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

    compound: str = Field(default="State 2 + State 3")
    diagnostic: str = Field(
        default="Cascading deadlock across multi-agent RPC channels when buffers exceed threshold"
    )
    tier: str = Field(default="Fatal (Tier-X)")


class AudioProjectConfig(BaseModel):
    """Declarative configuration for audio overview compilation, constructed directly from a notebook."""

    title: str = Field(
        default="Unnamed Diagnostic Session", description="Project or notebook title."
    )
    topic: str | None = Field(default=None, description="Discussion topic directive.")
    notebook_id: str | None = Field(default=None, description="Target NotebookLM UUID.")
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
    audio_format: str = Field(
        default="default",
        description="Audio studio generation format (e.g. 'default', 'debate', 'deep-dive').",
    )
    audio_length: str = Field(
        default="default", description="Target run time ('short', 'default', 'long')."
    )

    topic_1: Topic1 = Field(default_factory=Topic1)
    topic_2: Topic2 = Field(default_factory=Topic2)
    topic_3: Topic3 = Field(default_factory=Topic3)
    lexical_bindings: LexicalBindings = Field(default_factory=LexicalBindings)

    # Legacy attributes for backward compatibility
    topics: list[str] = Field(default_factory=list)
    lexical_dictionary: LexicalDictionary = Field(default_factory=LexicalDictionary)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    escalations: list[CompoundEscalation] = Field(default_factory=list)
    query_guidance: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        if self.topic is None and self.title:
            self.topic = f"system architecture and diagnostic failure modes in '{self.title}'"
        if not self.topics:
            self.topics = [self.topic_1.title, self.topic_2.title, self.topic_3.title]
