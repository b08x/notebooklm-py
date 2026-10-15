import json
import logging
from typing import Any

import dspy

logger = logging.getLogger(__name__)

try:
    import spacy

    nlp: Any = spacy.load("en_core_web_md")
except Exception as e:
    logger.warning(f"Failed to load spacy model 'en_core_web_md': {e}")
    nlp = None


class SFLPass2Signature(dspy.Signature):
    """Pass 2: Interpersonal and Textual Analysis. Identify mood, modality, tenor, and thematic structure."""

    utterance = dspy.InputField(desc="The spoken utterance to analyze.")
    pass1_analysis = dspy.InputField(
        desc="The deterministic ideational analysis (participants, processes, circumstances)."
    )
    analysis = dspy.OutputField(
        desc="JSON formatted interpersonal analysis containing keys: mood, modality, tenor"
    )


def ideational_analysis(utterance: str) -> dict[str, list[str]]:
    """Pass 1: deterministic spaCy participants, processes and circumstances.

    Returns empty lists when the spaCy model is not installed.
    """
    p1_dict: dict[str, list[str]] = {"participants": [], "processes": [], "circumstances": []}

    if nlp:
        doc = nlp(utterance)
        p1_dict["participants"] = [chunk.text for chunk in doc.noun_chunks]
        p1_dict["processes"] = [tok.lemma_ for tok in doc if tok.pos_ == "VERB"]

        circumstances = []
        for tok in doc:
            if tok.dep_ == "prep":
                circumstances.append(" ".join([t.text for t in tok.subtree]))
            elif tok.pos_ == "ADV":
                circumstances.append(tok.text)
        p1_dict["circumstances"] = circumstances

    return p1_dict


class SFLEngine(dspy.Module):
    def __init__(self):
        super().__init__()
        self.pass2 = dspy.ChainOfThought(SFLPass2Signature)

    def forward(self, utterance: str) -> dict[str, Any]:
        p1_dict = ideational_analysis(utterance)
        p1_analysis_str = json.dumps(p1_dict)
        p2 = self.pass2(utterance=utterance, pass1_analysis=p1_analysis_str)

        try:
            # We assume the LLM outputs valid JSON in the output field, but we should strip backticks if any
            p2_dict = json.loads(p2.analysis.strip("`").removeprefix("json\n"))
        except Exception as e:
            logger.warning(f"Failed to parse SFL pass 2 output: {e}")
            p2_dict = {"error": "parse failed", "tenor": "neutral", "modality": "neutral"}

        return {"ideational": p1_dict, "interpersonal": p2_dict}


def _extract_segments(diarization: Any) -> list[dict[str, Any]]:
    """Extract speaker segments [{'speaker': str, 'text': str}] across all providers."""
    if not diarization:
        return []

    # 1. Direct segments list (e.g. AssemblyAI utterances or custom segments)
    if isinstance(diarization, list):
        segments: list[dict[str, Any]] = []
        for item in diarization:
            if isinstance(item, dict):
                spk = item.get("speaker") or item.get("speaker_label") or "Unknown"
                spk_str = f"Speaker {spk}" if str(spk).isdigit() or len(str(spk)) == 1 else str(spk)
                text = item.get("text") or item.get("transcript") or ""
                if text.strip():
                    segments.append({"speaker": spk_str, "text": text.strip()})
        return segments

    if isinstance(diarization, dict):
        # 2. Explicit/test format: {"segments": [...]}
        if "segments" in diarization and isinstance(diarization["segments"], list):
            return diarization["segments"]

        # 3. Deepgram format: results -> channels -> alternatives -> paragraphs -> paragraphs
        try:
            results = diarization.get("results")
            if isinstance(results, dict):
                channels = results.get("channels", [])
                if channels:
                    alts = channels[0].get("alternatives", [{}])
                    paras = alts[0].get("paragraphs", {}).get("paragraphs", [])
                    if paras:
                        dg_segments = []
                        for p in paras:
                            spk = p.get("speaker", 0)
                            p_sentences = p.get("sentences", [])
                            p_text = " ".join(s.get("text", "") for s in p_sentences).strip()
                            if not p_text and "text" in p:
                                p_text = p["text"].strip()
                            if p_text:
                                dg_segments.append({"speaker": f"Speaker {spk}", "text": p_text})
                        if dg_segments:
                            return dg_segments

                    # Fallback to words in Deepgram
                    words = alts[0].get("words", [])
                    if words:
                        dg_word_segments: list[dict[str, Any]] = []
                        curr_spk: str | None = None
                        curr_words: list[str] = []
                        for w in words:
                            spk = f"Speaker {w.get('speaker', 0)}"
                            word_text = w.get("punctuated_word") or w.get("word") or ""
                            if spk != curr_spk and curr_words and curr_spk is not None:
                                dg_word_segments.append(
                                    {"speaker": curr_spk, "text": " ".join(curr_words)}
                                )
                                curr_words = []
                            curr_spk = spk
                            curr_words.append(word_text)
                        if curr_words and curr_spk is not None:
                            dg_word_segments.append(
                                {"speaker": curr_spk, "text": " ".join(curr_words)}
                            )
                        if dg_word_segments:
                            return dg_word_segments
        except Exception:
            pass

        # 4. Speechmatics format: results -> list of words
        try:
            results = diarization.get("results")
            if isinstance(results, list):
                sm_segments: list[dict[str, Any]] = []
                curr_spk = None
                curr_words = []
                for r in results:
                    if r.get("type") == "word" and r.get("alternatives"):
                        alt = r["alternatives"][0]
                        spk_raw = alt.get("speaker", "S0")
                        spk = f"Speaker {spk_raw.lstrip('S') or '0'}"
                        word_text = alt.get("content", "")
                        if spk != curr_spk and curr_words and curr_spk is not None:
                            sm_segments.append({"speaker": curr_spk, "text": " ".join(curr_words)})
                            curr_words = []
                        curr_spk = spk
                        curr_words.append(word_text)
                if curr_words and curr_spk is not None:
                    sm_segments.append({"speaker": curr_spk, "text": " ".join(curr_words)})
                if sm_segments:
                    return sm_segments
        except Exception:
            pass

    return []


def engine_batches(engine: Any) -> bool:
    """True when ``engine`` analyses many utterances per call (``forward_batch``).

    Looked up on the class: engines that batch define the method there.
    """
    return callable(getattr(type(engine), "forward_batch", None)) and bool(
        getattr(engine, "batch", True)
    )


def sfl_results(engine: Any, texts: list[str]) -> list[Any]:
    """One SFL result per text: a whole batch when the engine supports it.

    A failed item may be an exception instance in place of a dict.
    """
    if engine_batches(engine):
        return list(engine.forward_batch(texts))
    return [engine(utterance=text) for text in texts]


def analyze_transcript(
    transcript: str, diarization: Any = None, *, engine: Any = None
) -> dict[str, Any]:
    """Run SFL analysis over a transcript. Tracks speaker profiles and semantic anomalies.

    ``engine`` defaults to the DSPy :class:`SFLEngine`. An engine with
    ``forward_batch`` (the CLI-agent ``AgentSFLEngine``) receives every segment
    in batched prompts instead of one model call per segment.
    """
    segments = _extract_segments(diarization)
    if not segments:
        return {
            "error": "Missing or failed diarization. Speaker profiles bypassed.",
            "profiles": {},
            "anomalies": [],
        }

    engine = engine if engine is not None else SFLEngine()
    profiles: dict[str, Any] = {}
    anomalies = []

    previous_tenor = None
    results = sfl_results(engine, [seg.get("text", "") for seg in segments])

    for idx, (seg, res) in enumerate(zip(segments, results, strict=True)):
        speaker = seg.get("speaker", "Unknown")
        text = seg.get("text", "")

        if speaker not in profiles:
            profiles[speaker] = {"utterances": 0, "dominant_tenor": None, "tenors": []}

        profiles[speaker]["utterances"] += 1

        if isinstance(res, BaseException):
            logger.warning(f"SFL analysis failed for segment {idx}: {res}")
            res = {"interpersonal": {}}
        tenor = res.get("interpersonal", {}).get("tenor", "neutral")
        # A loosely formatted DSPy reply can return a nested object; counting
        # tenors needs a hashable label.
        if not isinstance(tenor, str):
            tenor = "neutral"

        profiles[speaker]["tenors"].append(tenor)

        # Check for semantic anomaly: sudden shift in tenor
        if previous_tenor and tenor != previous_tenor:
            if previous_tenor in ["formal", "academic"] and tenor in ["slang", "casual"]:
                anomalies.append(
                    {
                        "segment_index": idx,
                        "speaker": speaker,
                        "issue": f"Semantic anomaly: Sudden shift in tenor from {previous_tenor} to {tenor}",
                        "text": text,
                    }
                )

        previous_tenor = tenor

    # Calculate dominant tenor
    for data in profiles.values():
        if data["tenors"]:
            data["dominant_tenor"] = max(set(data["tenors"]), key=data["tenors"].count)

    return {"profiles": profiles, "anomalies": anomalies}


def __getattr__(name: str) -> Any:
    # Lazy re-export: ``cli_agents.sfl_engine`` imports this module for pass 1,
    # so an eager import here would be circular.
    if name == "AgentSFLEngine":
        from .cli_agents.sfl_engine import AgentSFLEngine

        return AgentSFLEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
