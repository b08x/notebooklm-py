from __future__ import annotations

import pytest

from notebooklm._preprocessing.checkworthiness import assess

DECLARATIVE_HIGH = {"mood": "declarative", "modality": "high", "tenor": "neutral"}


def _tokens(*words: tuple[str, str]) -> list[dict[str, str]]:
    return [{"text": text, "lemma": lemma} for text, lemma in words]


DECLARATIVE_TOKENS = _tokens(("Water", "water"), ("boils", "boil"), ("at", "at"), ("100", "100"))


def test_no_sfl_is_not_checkworthy() -> None:
    assert assess(None, DECLARATIVE_TOKENS) == (False, "no sfl")


def test_declarative_high_modality_passes() -> None:
    ok, reason = assess(DECLARATIVE_HIGH, DECLARATIVE_TOKENS)
    assert ok is True
    assert reason


@pytest.mark.parametrize("modality", ["medium", "median", "High", 0.5, 0.9])
def test_modality_at_or_above_medium_passes(modality) -> None:
    ok, _ = assess({"mood": "declarative", "modality": modality}, DECLARATIVE_TOKENS)
    assert ok is True


@pytest.mark.parametrize("modality", ["low", 0.2, "neutral", None])
def test_modality_below_medium_is_rejected(modality) -> None:
    ok, reason = assess({"mood": "declarative", "modality": modality}, DECLARATIVE_TOKENS)
    assert ok is False
    assert "modality" in reason


def test_nested_interpersonal_shape_is_read() -> None:
    sfl = {"interpersonal": {"mood": "declarative", "modality": "high"}}
    assert assess(sfl, DECLARATIVE_TOKENS)[0] is True


@pytest.mark.parametrize("cue", ["might", "may", "perhaps", "could", "possibly", "maybe"])
def test_hedge_lemma_rejects(cue: str) -> None:
    tokens = _tokens(("Water", "water"), (cue, cue), ("boils", "boil"))
    ok, reason = assess(DECLARATIVE_HIGH, tokens)
    assert ok is False
    assert "hedge" in reason


def test_interrogative_rejects() -> None:
    tokens = _tokens(("Does", "do"), ("water", "water"), ("boil", "boil"), ("?", "?"))
    ok, reason = assess({"mood": "interrogative", "modality": "high"}, tokens)
    assert ok is False
    assert reason == "interrogative"


def test_question_mark_ending_rejects_even_when_declarative_mood() -> None:
    tokens = _tokens(("Water", "water"), ("boils", "boil"), ("?", "?"))
    assert assess(DECLARATIVE_HIGH, tokens)[0] is False


def test_non_declarative_mood_rejects() -> None:
    ok, reason = assess({"mood": "imperative", "modality": "high"}, DECLARATIVE_TOKENS)
    assert ok is False
    assert "declarative" in reason


def test_missing_tokens_still_gates_on_sfl() -> None:
    assert assess(DECLARATIVE_HIGH, None)[0] is True
