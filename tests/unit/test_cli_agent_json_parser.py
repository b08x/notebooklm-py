"""JSON extraction and repair for CLI agent output."""

from __future__ import annotations

import pytest

from notebooklm._preprocessing.cli_agents.parser import (
    JSONExtractionError,
    extract_and_repair_json,
)


def test_clean_json_object_and_list() -> None:
    assert extract_and_repair_json('{"a": 1}') == {"a": 1}
    assert extract_and_repair_json(" [1, 2] \n") == [1, 2]


def test_fenced_block_with_language_tag() -> None:
    text = 'Here you go:\n```json\n{"annotations": [{"index": 0}]}\n```\nDone.'
    assert extract_and_repair_json(text) == {"annotations": [{"index": 0}]}


def test_fenced_block_without_language_tag() -> None:
    assert extract_and_repair_json('```\n[{"mood": "declarative"}]\n```') == [
        {"mood": "declarative"}
    ]


def test_conversational_preamble_and_trailer() -> None:
    text = 'Sure! The analysis is {"mood": "imperative", "tenor": "casual"} — hope that helps.'
    assert extract_and_repair_json(text) == {"mood": "imperative", "tenor": "casual"}


def test_preamble_bracket_does_not_shadow_real_payload() -> None:
    text = 'Note [1]: output follows {"annotations": [{"index": 0, "mood": "x"}]}'
    assert extract_and_repair_json(text) == {"annotations": [{"index": 0, "mood": "x"}]}


def test_nested_structures() -> None:
    text = '{"a": {"b": [1, {"c": [true, null]}]}, "d": "e"}'
    assert extract_and_repair_json(text) == {"a": {"b": [1, {"c": [True, None]}]}, "d": "e"}


def test_ansi_codes_are_stripped() -> None:
    assert extract_and_repair_json('\x1b[32m{"ok": true}\x1b[0m') == {"ok": True}


def test_trailing_commas_repaired() -> None:
    assert extract_and_repair_json('{"a": [1, 2,], "b": 3,}') == {"a": [1, 2], "b": 3}


def test_smart_quotes_repaired() -> None:
    assert extract_and_repair_json("{“mood”: “declarative”}") == {"mood": "declarative"}


def test_python_literal_single_quotes_repaired() -> None:
    assert extract_and_repair_json("{'mood': 'declarative', 'ok': True}") == {
        "mood": "declarative",
        "ok": True,
    }


def test_truncated_document_is_closed() -> None:
    text = '{"annotations": [{"index": 0, "mood": "declarative"}, {"index": 1, "mood": "inter'
    value = extract_and_repair_json(text)
    assert value["annotations"][0] == {"index": 0, "mood": "declarative"}
    assert value["annotations"][1]["index"] == 1


@pytest.mark.parametrize("text", ["", "   ", "no json here at all", "{{{{ not json"])
def test_unrecoverable_text_raises(text: str) -> None:
    with pytest.raises(JSONExtractionError):
        extract_and_repair_json(text)


def test_non_string_raises() -> None:
    with pytest.raises(JSONExtractionError):
        extract_and_repair_json(None)  # type: ignore[arg-type]
