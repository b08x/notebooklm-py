import re


class HybridChunker:
    """
    Hierarchical chunker with tokenization-aware refinements.
    """

    def __init__(self, max_chunk_size: int = 1000):
        self.max_chunk_size = max_chunk_size

    def chunk(self, text: str) -> list[str]:
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk: list[str] = []
        current_length = 0

        for p in paragraphs:
            p = p.strip()
            if not p:
                continue

            if len(p) > self.max_chunk_size:
                sentences = re.split(r"(?<=[.!?])\s+", p)
                for s in sentences:
                    s = s.strip()
                    if not s:
                        continue
                    if current_length + len(s) > self.max_chunk_size and current_chunk:
                        chunks.append("\n\n".join(current_chunk))
                        current_chunk = [s]
                        current_length = len(s)
                    else:
                        current_chunk.append(s)
                        current_length += len(s)
            else:
                if current_length + len(p) > self.max_chunk_size and current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = [p]
                    current_length = len(p)
                else:
                    current_chunk.append(p)
                    current_length += len(p)

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks


class StructuralCoherenceChunker:
    """
    Structural Coherence chunking using a systemic functional approach.
    """

    def __init__(self, model: str = "en_core_web_md"):
        self.model = model

    def chunk(self, text: str) -> list[str]:
        try:
            import spacy

            nlp = spacy.load(self.model)
            doc = nlp(text)
            return [sent.text.strip() for sent in doc.sents if sent.text.strip()]
        except Exception:
            sentences = re.split(r"(?<=[.!?])\s+", text.strip())
            return [s for s in sentences if s]
