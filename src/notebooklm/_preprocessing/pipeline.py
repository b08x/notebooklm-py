import logging
from dataclasses import dataclass, field

from notebooklm._preprocessing.annotators import BERTopicAnnotator, DoclingPIIFilter, SpacyAnnotator
from notebooklm._preprocessing.chunkers import HybridChunker, StructuralCoherenceChunker

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """One preprocessed source chunk.

    Fact-checking is a separate, opt-in action (run per chunk from the TUI) rather
    than part of pipeline output, so this carries no ``fact_check_passed`` field —
    that verdict lives on the ``Clause`` row a chunk gets ingested as.
    """

    text: str
    topic_id: int = -1
    entities: list[tuple[str, str]] = field(default_factory=list)

    @property
    def formatted(self) -> str:
        """Flattened text representation for callers that want a plain string."""
        ent_str = ", ".join(f"{label} ({kind})" for label, kind in self.entities) or "None"
        return f"{self.text}\n\n--- Metadata ---\nTopic ID: {self.topic_id}\nEntities: {ent_str}"


class PreprocessingPipeline:
    def __init__(self):
        self.hybrid_chunker = HybridChunker()
        self.struct_chunker = StructuralCoherenceChunker()
        self.spacy_ann = SpacyAnnotator()
        self.topic_ann = BERTopicAnnotator()
        self.pii_filter = DoclingPIIFilter()

    def process(self, text: str) -> list[Chunk]:
        logger.info("Starting preprocessing pipeline")

        # 1. PII Filter
        safe_text = self.pii_filter.filter(text)

        # 2. Chunking
        raw_chunks = self.hybrid_chunker.chunk(safe_text)
        refined_chunks = []
        for c in raw_chunks:
            refined_chunks.extend(self.struct_chunker.chunk(c))

        if not refined_chunks:
            return []

        # 3. Topic Modeling (bulk)
        try:
            topics = self.topic_ann.annotate(refined_chunks)
        except Exception:
            topics = [-1] * len(refined_chunks)

        final_chunks = []
        for i, chunk in enumerate(refined_chunks):
            # 4. Spacy Annotations
            try:
                ann = self.spacy_ann.annotate(chunk)
                entities = [(text, label) for text, label in ann.get("entities", [])]
            except Exception:
                entities = []

            topic = topics[i] if i < len(topics) else -1

            final_chunks.append(Chunk(text=chunk, topic_id=topic, entities=entities))

        return final_chunks
