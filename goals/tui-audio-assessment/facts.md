# Facts

- The TUI includes a dedicated fullscreen view for Audio Overview Assessment.
- The assessment view displays the audio output, system instructions, and contextualized source chunks side-by-side.
- The assessment interface uses a hybrid grading model: an automated LLM suggests a score/feedback, and the user can confirm or edit it.
- The preprocessing pipeline implements a Hybrid Chunker with tokenization-aware refinements on top of hierarchical chunking.
- The preprocessing pipeline applies Structural Coherence chunking using a systemic functional approach.
- The preprocessing pipeline integrates the spaCy NLP Pipeline to extract POS, Lemmatization, and NER from the chunks. (Note: Also integrate BERTopic for topic modeling).
- The preprocessing pipeline integrates PII removal via Docling.
- The preprocessing pipeline integrates fact-checker agent validations using the framework at `~/.syncopated/skills/fact-check`.
