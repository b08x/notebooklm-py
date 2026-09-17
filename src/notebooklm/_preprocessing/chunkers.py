import re
from typing import List

class HybridChunker:
    """
    Hierarchical chunker with tokenization-aware refinements.
    """
    def __init__(self, max_chunk_size: int = 1000):
        self.max_chunk_size = max_chunk_size

    def chunk(self, text: str) -> List[str]:
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = []
        current_length = 0

        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
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
    def chunk(self, text: str) -> List[str]:
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        return [s for s in sentences if s]
