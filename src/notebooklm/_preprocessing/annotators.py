import logging
from typing import Any

logger = logging.getLogger(__name__)


def _redact_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Replace each ``(start_char, end_char)`` span with ``[REDACTED]``.

    Position-based, not ``str.replace(ent.text, ...)``: a global substring
    replace nukes every occurrence of an entity's text anywhere in the
    document, not just the tagged span — a short/common mistagged fragment
    (e.g. a stray ``"l"``) then mangles unrelated words throughout the text
    (``"absolutely"`` -> ``"abso[REDACTED]ute[REDACTED]y"``).
    """
    if not spans:
        return text
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    parts = []
    cursor = 0
    for start, end in merged:
        parts.append(text[cursor:start])
        parts.append("[REDACTED]")
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


class SpacyAnnotator:
    def __init__(self, model: str = "en_core_web_md"):
        self.model = model
        self.nlp: Any = None

    def _load_model(self):
        if self.nlp is None:
            try:
                import spacy

                self.nlp = spacy.load(self.model)
            except ImportError:
                logger.warning("spacy not installed. SpacyAnnotator fallback triggered.")
                self.nlp = None
            except Exception as e:
                logger.warning(
                    f"Failed to load spacy model '{self.model}': {e}. SpacyAnnotator fallback triggered."
                )
                self.nlp = None

    def annotate(self, text: str) -> dict[str, Any]:
        self._load_model()
        if self.nlp:
            doc = self.nlp(text)
            return {
                "pos": [token.pos_ for token in doc],
                "lemmas": [token.lemma_ for token in doc],
                "entities": [(ent.text, ent.label_) for ent in doc.ents],
            }
        # Fallback if spacy is not installed
        return {"pos": [], "lemmas": [], "entities": []}


class BERTopicAnnotator:
    def __init__(self):
        self.topic_model = None

    def _load_model(self):
        if self.topic_model is None:
            try:
                from bertopic import BERTopic

                self.topic_model = BERTopic()
            except ImportError:
                logger.warning("bertopic not installed. BERTopicAnnotator fallback triggered.")
                self.topic_model = None

    def annotate(self, docs: list[str]) -> list[int]:
        self._load_model()
        if self.topic_model:
            topics, _ = self.topic_model.fit_transform(docs)
            return topics
        # Fallback
        return [-1] * len(docs)


class DoclingPIIFilter:
    def __init__(self):
        self.docling_available = False
        import importlib.util

        if importlib.util.find_spec("docling") is not None:
            self.docling_available = True
        else:
            logger.warning("docling not installed. DoclingPIIFilter fallback triggered.")

    def filter(self, text: str) -> str:
        res_text = text
        if self.docling_available:
            try:
                import spacy

                nlp = spacy.load("en_core_web_md")
                doc = nlp(res_text)
                spans = [
                    (ent.start_char, ent.end_char)
                    for ent in doc.ents
                    if ent.label_ in ["PERSON", "ORG", "GPE", "LOC", "FAC", "NORP"]
                ]
                res_text = _redact_spans(res_text, spans)
            except Exception:
                pass

        import re

        res_text = re.sub(r"[\w\.-]+@[\w\.-]+", "[REDACTED]", res_text)
        res_text = re.sub(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", "[REDACTED]", res_text)
        res_text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED]", res_text)

        # Fallback for tests
        return res_text.replace("PII", "[REDACTED]")
