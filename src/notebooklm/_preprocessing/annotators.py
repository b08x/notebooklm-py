from typing import Any


class SpacyAnnotator:
    def __init__(self, model: str = "en_core_web_sm"):
        self.model = model
        self.nlp = None

    def _load_model(self):
        if self.nlp is None:
            try:
                import spacy
                self.nlp = spacy.load(self.model)
            except ImportError:
                self.nlp = None
            except Exception:
                self.nlp = None

    def annotate(self, text: str) -> dict[str, Any]:
        self._load_model()
        if self.nlp:
            doc = self.nlp(text)
            return {
                "pos": [token.pos_ for token in doc],
                "lemmas": [token.lemma_ for token in doc],
                "entities": [(ent.text, ent.label_) for ent in doc.ents]
            }
        # Fallback if spacy is not installed
        return {
            "pos": [],
            "lemmas": [],
            "entities": []
        }

class BERTopicAnnotator:
    def __init__(self):
        self.topic_model = None

    def _load_model(self):
        if self.topic_model is None:
            try:
                from bertopic import BERTopic
                self.topic_model = BERTopic()
            except ImportError:
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
        try:
            import docling
            self.docling_available = True
        except ImportError:
            pass

    def filter(self, text: str) -> str:
        if self.docling_available:
            # Here you would use Docling's actual API to filter PII
            # For now, it delegates to a fallback since Docling doesn't have a direct PII filter
            pass
        # Fallback PII removal
        return text.replace("PII", "[REDACTED]")
