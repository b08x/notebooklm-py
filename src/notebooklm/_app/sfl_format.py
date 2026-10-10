"""One SFL formatter shared by the TUI panels and the web Corpus Explorer.

SFL output reaches the UI in two shapes:

* the assessment shape, ``{"ideational": {...}, "interpersonal": {...}}``
  (``SFLEngine.forward``), and
* the stored ``Clause.sfl`` shape, ``{mood, modality, tenor, pass1[, raw]}``
  (``sfl_tag`` job), where ``pass1`` holds the ideational output.

Either value of a field may be a string, a list, or a nested dict such as
``{"formality": "informal", "stance": "explanatory"}``. :func:`format_sfl`
flattens every field to a list of display strings so a renderer never iterates
a dict and prints its keys.

Transport-neutral: no ``rich`` / ``click`` / ``tui`` imports.
"""

from __future__ import annotations

from typing import Any

IDEATIONAL_FIELDS = ("participants", "processes", "circumstances")
INTERPERSONAL_FIELDS = ("tenor", "mood", "modality")


def flatten_value(value: Any) -> list[str]:
    """Flatten one SFL field value to display strings.

    Strings pass through, lists flatten element-wise, dicts become
    ``"key: value"`` strings (nested values joined with ``", "``), and ``None``
    or empty values yield ``[]``.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        out: list[str] = []
        for key, inner in value.items():
            parts = flatten_value(inner)
            if parts:
                out.append(f"{key}: {', '.join(parts)}")
        return out
    if isinstance(value, list | tuple | set):
        flat: list[str] = []
        for item in value:
            flat.extend(flatten_value(item))
        return flat
    return [str(value)]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def format_sfl(sfl: dict[str, Any] | None) -> dict[str, dict[str, list[str]]]:
    """Normalize either SFL shape to ``{"ideational": {...}, "interpersonal": {...}}``.

    Every field is present and maps to a (possibly empty) list of strings.
    """
    sfl = _as_dict(sfl)
    ideational = _as_dict(sfl.get("ideational")) or _as_dict(sfl.get("pass1"))
    interpersonal = _as_dict(sfl.get("interpersonal")) or sfl
    return {
        "ideational": {key: flatten_value(ideational.get(key)) for key in IDEATIONAL_FIELDS},
        "interpersonal": {
            key: flatten_value(interpersonal.get(key)) for key in INTERPERSONAL_FIELDS
        },
    }
