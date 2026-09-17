import os

import dspy


def setup_dspy_router():
    """
    Sets up DSPy model and embedding routing based on environment variables.
    Routes to either local (Ollama) or provider models.
    """
    # Model routing
    model_provider = os.getenv("NOTEBOOKLM_ASSESSMENT_MODEL_PROVIDER", "ollama").lower()
    model_name = os.getenv("NOTEBOOKLM_ASSESSMENT_MODEL", "llama3")

    if model_provider == "ollama":
        lm = dspy.LM(f"ollama_chat/{model_name}")
    else:
        lm = dspy.LM(f"{model_provider}/{model_name}")

    # Embedding routing
    embed_provider = os.getenv("NOTEBOOKLM_ASSESSMENT_EMBED_PROVIDER", "ollama").lower()
    embed_model = os.getenv("NOTEBOOKLM_ASSESSMENT_EMBED_MODEL", "nomic-embed-text")

    if embed_provider == "ollama":
        embedder = dspy.Embedder(f"ollama/{embed_model}")
    else:
        embedder = dspy.Embedder(f"{embed_provider}/{embed_model}")

    # Setting dspy settings
    dspy.settings.configure(lm=lm)
    return lm, embedder

class AudioOverviewAssessmentSignature(dspy.Signature):
    """Assess an audio overview generation based on system instructions and contextualized source chunks."""
    system_instructions = dspy.InputField(desc="The original system instructions for generating the audio overview.")
    audio_metadata = dspy.InputField(desc="Metadata of the generated audio.")
    source_chunks = dspy.InputField(desc="Contextualized source chunks used for the audio generation.")

    score = dspy.OutputField(desc="Suggested score out of 10 for how well it followed the instructions.")
    feedback = dspy.OutputField(desc="Feedback on what went well and what could be improved.")

class AudioOverviewAssessor(dspy.Module):
    def __init__(self):
        super().__init__()
        self.assess = dspy.ChainOfThought(AudioOverviewAssessmentSignature)

    def forward(self, system_instructions: str, audio_metadata: str, source_chunks: list[str]):
        chunks_text = "\n\n".join(source_chunks)
        return self.assess(
            system_instructions=system_instructions,
            audio_metadata=audio_metadata,
            source_chunks=chunks_text
        )

def generate_assessment(system_instructions: str, audio_metadata: str, chunks: list[str]) -> dict[str, str]:
    """
    Run the asynchronous LLM call (via DSPy) to get suggested score and feedback.
    """
    lm, embedder = setup_dspy_router()
    assessor = AudioOverviewAssessor()

    try:
        prediction = assessor(
            system_instructions=system_instructions,
            audio_metadata=audio_metadata,
            source_chunks=chunks
        )
        return {
            "score": prediction.score,
            "feedback": prediction.feedback
        }
    except Exception as e:
        return {
            "score": "Error",
            "feedback": f"Failed to generate assessment: {str(e)}"
        }
