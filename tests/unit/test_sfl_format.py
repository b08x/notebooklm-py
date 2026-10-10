"""Shared SFL formatter (fact-43)."""

from __future__ import annotations

from notebooklm._app.sfl_format import flatten_value, format_sfl


def test_flatten_value_shapes() -> None:
    assert flatten_value(None) == []
    assert flatten_value("  ") == []
    assert flatten_value("declarative") == ["declarative"]
    assert flatten_value(["a", ["b", None], 3]) == ["a", "b", "3"]
    assert flatten_value({"formality": "informal", "x": None, "y": ["p", "q"]}) == [
        "formality: informal",
        "y: p, q",
    ]
    assert flatten_value(0.7) == ["0.7"]


def test_format_sfl_assessment_shape() -> None:
    out = format_sfl(
        {
            "ideational": {"participants": ["Ada"], "processes": "wrote"},
            "interpersonal": {"tenor": {"formality": "informal"}, "mood": "declarative"},
        }
    )
    assert out["ideational"] == {
        "participants": ["Ada"],
        "processes": ["wrote"],
        "circumstances": [],
    }
    assert out["interpersonal"]["tenor"] == ["formality: informal"]
    assert out["interpersonal"]["modality"] == []


def test_format_sfl_stored_clause_shape() -> None:
    out = format_sfl(
        {
            "mood": "declarative",
            "modality": {"level": "high"},
            "tenor": "formal",
            "pass1": {"participants": ["the cgroup"]},
        }
    )
    assert out["ideational"]["participants"] == ["the cgroup"]
    assert out["interpersonal"] == {
        "tenor": ["formal"],
        "mood": ["declarative"],
        "modality": ["level: high"],
    }


def test_format_sfl_none() -> None:
    out = format_sfl(None)
    assert all(v == [] for v in out["ideational"].values())
    assert all(v == [] for v in out["interpersonal"].values())
