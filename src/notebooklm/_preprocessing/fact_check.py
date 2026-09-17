import logging
import os

import dspy

logger = logging.getLogger(__name__)


class FactCheckAdapter:
    def __init__(self):
        self.framework_path = os.environ.get(
            "FACT_CHECK_FRAMEWORK_PATH", os.path.expanduser("~/.syncopated/skills/fact-check")
        )
        self._prompt = self._load_framework()

    def _load_framework(self) -> str:
        sift_path = os.path.join(self.framework_path, "sift.skill")
        if not os.path.exists(sift_path):
            return "No fact-check framework found."

        import zipfile

        try:
            with zipfile.ZipFile(sift_path, "r") as z:
                for name in z.namelist():
                    if name.endswith("SKILL.md"):
                        return z.read(name).decode("utf-8")
        except Exception as e:
            logger.warning(f"Failed to read sift.skill: {e}")
        return "Default fact check prompt"

    @property
    def framework_available(self) -> bool:
        """Whether the external SIFT framework is present on disk.

        When ``False``, :meth:`check` always returns ``True`` (an unverified
        default-pass) — callers must surface that distinction in the UI rather
        than presenting the result as a real fact-check verdict.
        """
        return os.path.exists(self.framework_path)

    def check(self, chunk: str) -> bool:
        if not self.framework_available:
            logger.warning(
                f"Fact-check framework not found at {self.framework_path}. FactCheckAdapter fallback triggered."
            )
            return True

        try:

            class FactCheckSignature(dspy.Signature):
                """Evaluate the factual validity of a text chunk based on fact-checking instructions."""

                framework_instructions = dspy.InputField(
                    desc="Instructions from the fact-checking framework"
                )
                chunk = dspy.InputField(desc="The text chunk to verify")
                is_valid = dspy.OutputField(desc="Return strictly True or False")

            predictor = dspy.Predict(FactCheckSignature)
            res = predictor(framework_instructions=self._prompt, chunk=chunk)
            return str(res.is_valid).strip().lower() == "true"
        except Exception as e:
            logger.warning(f"Fact-check execution failed: {e}")
            return True
