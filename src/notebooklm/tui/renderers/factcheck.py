"""Fact-check mode: claims list (left), SIFT steps and evidence (right)."""

from __future__ import annotations

from typing import Any

from rich.console import Group, RenderableType
from rich.text import Text

from notebooklm._app.tracing import trace_url

from ..state import TUIState
from ..views.corpus_view import selected_claim
from ._widgets import key_hints, message_panel, panel

FACTCHECK_KEYS = [
    ("j/k", "move"),
    ("a/c/u", "all/contradicted/unverifiable"),
    ("F", "queue fact-check"),
    ("g", "reload"),
]

_VERDICT = {
    "supported": ("✓", "success"),
    "contradicted": ("✗", "error"),
    "unverifiable": ("?", "warning"),
    "not_checkworthy": ("·", "muted"),
    "skipped_no_framework": ("–", "muted"),
}
_SIFT_STEPS = (
    ("stop", "Stop"),
    ("investigate_source", "Investigate"),
    ("find_coverage", "Better coverage"),
    ("trace_claim", "Trace"),
)


def _sfl_short(sfl: dict[str, Any] | None) -> str:
    if not sfl:
        return ""
    return f"{str(sfl.get('mood', ''))[:11]}/{str(sfl.get('modality', ''))[:8]}"


def _claims(state: TUIState) -> RenderableType:
    view = state.factcheck_view
    claims = view.get("claims")
    if claims is None:
        return Text("Loading…", style="muted")
    if not claims:
        return Text(
            "No fact-checks for this filter. Press F to queue a fact_check job.", style="muted"
        )
    cursor = view.get("cursor", 0)
    lines = []
    for i, c in enumerate(claims):
        glyph, style = _VERDICT.get(c["verdict"], ("?", "muted"))
        latency = f"{c['latency_ms'] / 1000:.0f}s" if c.get("latency_ms") else ""
        lines.append(
            Text.assemble(
                ("> " if i == cursor else "  ", "marker"),
                (f"{glyph} ", style),
                (
                    " ".join(c["text"].split())[:48].ljust(49),
                    "selected" if i == cursor else "foreground",
                ),
                (f"{c['verdict']:<16}", style),
                (f"{_sfl_short(c.get('sfl')):<21}", "muted"),
                (f"{latency:>5}", "muted"),
            )
        )
    return Group(*lines)


def _render_step(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items() if v not in (None, "", []))
    return str(value or "")


def _sift(claim: dict[str, Any] | None) -> RenderableType:
    if claim is None:
        return Text("Select a claim.", style="muted")
    steps = claim.get("sift_steps") or {}
    lines = []
    for key, label in _SIFT_STEPS:
        lines.append(
            Text.assemble((f"{label:<16}", "label"), (_render_step(steps.get(key)), "foreground"))
        )
    if claim.get("confidence") is not None:
        probs = claim.get("probabilities") or {}
        detail = "  ".join(f"{k} {v:.2f}" for k, v in probs.items())
        lines.append(
            Text.assemble(
                ("Verdict         ", "label"),
                (f"{claim['verdict']} ({claim['confidence']:.2f})  ", "foreground"),
                (detail, "muted"),
            )
        )
    return Group(*lines)


def _evidence(claim: dict[str, Any] | None) -> RenderableType:
    if claim is None:
        return Text("")
    lines: list[RenderableType] = []
    for i, cit in enumerate(claim.get("citations") or [], start=1):
        lines.append(
            Text.assemble(
                (f"[{i}] ", "key"), (str(cit.get("title") or cit.get("url") or ""), "foreground")
            )
        )
        if cit.get("url"):
            lines.append(Text(f"    {cit['url']}", style="info"))
        if cit.get("quote"):
            lines.append(Text(f"    “{cit['quote']}”", style="muted"))
    if not lines:
        lines.append(Text("No citations.", style="muted"))
    lines.append(Text(""))
    lines.append(Text("Parent context", style="label"))
    lines.append(Text(" ".join((claim.get("parent_text") or "").split())[:600], style="foreground"))
    url = trace_url(claim.get("trace_id"))
    if url:
        lines.append(Text.assemble(("trace ", "label"), (url, "info")))
    if claim.get("model"):
        lines.append(Text.assemble(("model ", "label"), (claim["model"], "muted")))
    return Group(*lines)


def render_factcheck(state: TUIState) -> tuple[Any, Any, Any]:
    """Return (claims panel, SIFT panel, evidence panel)."""
    view = state.factcheck_view
    if not state.selected_notebook:
        msg = message_panel("Select a notebook in 1 Notebooks first.", "Claims")
        return msg, panel(Text(""), "SIFT"), panel(Text(""), "Evidence / Context")
    if view.get("error"):
        err = message_panel(view["error"], "Claims", style="error")
        return err, panel(Text(""), "SIFT"), panel(Text(""), "Evidence / Context")
    flt = view.get("filter") or "all"
    claim = selected_claim(view)
    claims_panel = panel(
        Group(_claims(state), Text(""), key_hints(FACTCHECK_KEYS, sep="  ")),
        f"Claims · {flt}",
        focused=True,
    )
    return claims_panel, panel(_sift(claim), "SIFT"), panel(_evidence(claim), "Evidence / Context")
