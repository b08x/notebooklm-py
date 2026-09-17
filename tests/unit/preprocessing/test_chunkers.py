from notebooklm._preprocessing.chunkers import HybridChunker, StructuralCoherenceChunker

def test_hybrid_chunker():
    chunker = HybridChunker(max_chunk_size=4)
    text = "Hello\n\nWorld\n\nThis is a long paragraph"
    chunks = chunker.chunk(text)
    assert len(chunks) == 3
    assert chunks[0] == "Hello"
    assert chunks[1] == "World"
    assert chunks[2] == "This is a long paragraph"

def test_structural_coherence_chunker():
    chunker = StructuralCoherenceChunker()
    text = "First sentence. Second sentence! Third sentence?"
    chunks = chunker.chunk(text)
    assert len(chunks) == 3
    assert chunks[0] == "First sentence."
    assert chunks[1] == "Second sentence!"
    assert chunks[2] == "Third sentence?"
