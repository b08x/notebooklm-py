import json
import logging
from typing import Any, Dict, List, Optional

import dspy

logger = logging.getLogger(__name__)

class SFLPass1Signature(dspy.Signature):
    """Pass 1: Syntactic and Ideational Analysis. Identify participants, processes, and circumstances."""
    
    utterance = dspy.InputField(desc="The spoken utterance to analyze.")
    analysis = dspy.OutputField(desc="JSON formatted syntactic/ideational analysis containing keys: participants, processes, circumstances")

class SFLPass2Signature(dspy.Signature):
    """Pass 2: Interpersonal and Textual Analysis. Identify mood, modality, tenor, and thematic structure."""
    
    utterance = dspy.InputField(desc="The spoken utterance to analyze.")
    pass1_analysis = dspy.InputField(desc="The ideational analysis from Pass 1.")
    analysis = dspy.OutputField(desc="JSON formatted interpersonal analysis containing keys: mood, modality, tenor")

class SFLEngine(dspy.Module):
    def __init__(self):
        super().__init__()
        self.pass1 = dspy.ChainOfThought(SFLPass1Signature)
        self.pass2 = dspy.ChainOfThought(SFLPass2Signature)

    def forward(self, utterance: str) -> Dict[str, Any]:
        p1 = self.pass1(utterance=utterance)
        p2 = self.pass2(utterance=utterance, pass1_analysis=p1.analysis)
        
        try:
            # We assume the LLM outputs valid JSON in the output field, but we should strip backticks if any
            p1_dict = json.loads(p1.analysis.strip("`").removeprefix("json\n"))
            p2_dict = json.loads(p2.analysis.strip("`").removeprefix("json\n"))
        except Exception as e:
            logger.warning(f"Failed to parse SFL output: {e}")
            p1_dict = {"error": "parse failed"}
            p2_dict = {"error": "parse failed", "tenor": "neutral", "modality": "neutral"}

        return {
            "ideational": p1_dict,
            "interpersonal": p2_dict
        }

def analyze_transcript(transcript: str, diarization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run SFL analysis over a transcript. Tracks speaker profiles and semantic anomalies."""
    if not diarization or not diarization.get("speakers"):
        return {
            "error": "Missing or failed diarization. Speaker profiles bypassed.",
            "profiles": {},
            "anomalies": []
        }
    
    # Mocking chunking by speaker for now.
    # In a real scenario, we'd align diarization segments with text.
    # Let's assume diarization["segments"] gives us {"speaker": "Host 1", "text": "..."}
    
    segments = diarization.get("segments", [])
    if not segments:
         return {
            "error": "No diarization segments found.",
            "profiles": {},
            "anomalies": []
        }
        
    engine = SFLEngine()
    profiles = {}
    anomalies = []
    
    previous_tenor = None
    
    for idx, seg in enumerate(segments):
        speaker = seg.get("speaker", "Unknown")
        text = seg.get("text", "")
        
        if speaker not in profiles:
            profiles[speaker] = {"utterances": 0, "dominant_tenor": None, "tenors": []}
            
        profiles[speaker]["utterances"] += 1
        
        res = engine(utterance=text)
        tenor = res["interpersonal"].get("tenor", "neutral")
        
        profiles[speaker]["tenors"].append(tenor)
        
        # Check for semantic anomaly: sudden shift in tenor
        if previous_tenor and tenor != previous_tenor:
            if previous_tenor in ["formal", "academic"] and tenor in ["slang", "casual"]:
                anomalies.append({
                    "segment_index": idx,
                    "speaker": speaker,
                    "issue": f"Semantic anomaly: Sudden shift in tenor from {previous_tenor} to {tenor}",
                    "text": text
                })
        
        previous_tenor = tenor
        
    # Calculate dominant tenor
    for sp, data in profiles.items():
        if data["tenors"]:
            data["dominant_tenor"] = max(set(data["tenors"]), key=data["tenors"].count)
            
    return {
        "profiles": profiles,
        "anomalies": anomalies
    }
