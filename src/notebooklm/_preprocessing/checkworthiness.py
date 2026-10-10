"""Pre-LLM gate: decide whether a child clause is worth fact-checking.

Reads only the stored SFL output and spaCy tokens. Never calls an LLM.
"""

from __future__ import annotations

from typing import Any

#: Lemmas (or surface forms) that mark a clause as hedged.
HEDGE_CUES = frozenset({"might", "may", "perhaps", "could", "possibly", "maybe"})
#: Modality labels that pass the gate.
PASSING_MODALITY_LABELS = frozenset({"high", "medium", "median", "moderate"})
#: Numeric modality at or above this value passes the gate.
PASSING_MODALITY_SCORE = 0.5


def _sfl_field(sfl: dict[str, Any], key: str) -> Any:
    """Read ``key`` from a stored SFL dict, top level or under ``interpersonal``."""
    if key in sfl:
        return sfl[key]
    inner = sfl.get("interpersonal")
    if isinstance(inner, dict):
        return inner.get(key)
    return None


def _modality_passes(modality: Any) -> bool:
    if isinstance(modality, dict):
        modality = next((modality[k] for k in ("level", "value", "score") if k in modality), None)
    if isinstance(modality, bool):
        return False
    if isinstance(modality, int | float):
        return float(modality) >= PASSING_MODALITY_SCORE
    if isinstance(modality, str):
        label = modality.strip().lower()
        if label in PASSING_MODALITY_LABELS:
            return True
        try:
            return float(label) >= PASSING_MODALITY_SCORE
        except ValueError:
            return False
    return False


def _token_field(token: Any, key: str) -> str:
    if isinstance(token, dict):
        value = token.get(key)
        if value is not None:
            return str(value).strip().lower()
    return ""


def assess(sfl: dict[str, Any] | None, tokens: list[dict[str, Any]] | None) -> tuple[bool, str]:
    """Return ``(checkworthy, reason)`` for one child clause."""
    if sfl is None:
        return False, "no sfl"

    token_list = tokens if isinstance(tokens, list) else []
    for token in token_list:
        text = _token_field(token, "text")
        if _token_field(token, "lemma") in HEDGE_CUES or text in HEDGE_CUES:
            return False, f"hedge cue: {text}"

    surface = [t for t in (_token_field(tok, "text") for tok in token_list) if t]
    if surface and surface[-1].endswith("?"):
        return False, "interrogative"

    mood = _sfl_field(sfl, "mood")
    if "declarative" not in str(mood or "").lower():
        return False, f"mood not declarative: {mood}"

    modality = _sfl_field(sfl, "modality")
    if not _modality_passes(modality):
        return False, f"modality below medium: {modality}"

    return True, "declarative, modality ok"
