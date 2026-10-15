"""Ingest mode: documents/parents (left), children (top right), detail (bottom right).

The detail pane toggles between tokens, a flat dependency table, groups, and
SFL output for the selected child. ``r`` opens a strategy picker in the detail
pane; ``x`` replaces it with a side-by-side comparison of the document's runs.
"""

from __future__ import annotations

from typing import Any

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from ..state import TUIState
from ..views.corpus_view import (
    DETAIL_VIEWS,
    STRATEGY_CHOICES,
    parent_rows,
    selected_child,
    selected_children,
)
from ._widgets import key_hints, message_panel, panel

INGEST_KEYS = [
    ("j/k", "parent"),
    ("J/K", "child"),
    ("t d g f", "tokens deps groups sfl"),
    ("i", "ingest"),
    ("r", "re-ingest as…"),
    ("x", "compare runs"),
    ("s", "SFL tag"),
    ("F", "fact-check"),
    ("T", "topics"),
]

_BAR_WIDTH = 12


def _bar(value: int, maximum: int) -> Text:
    filled = round(_BAR_WIDTH * value / maximum) if maximum else 0
    return Text("█" * filled + "░" * (_BAR_WIDTH - filled), style="accent")


def _tree(state: TUIState) -> RenderableType:
    view = state.ingest_view
    rows = parent_rows(view)
    if not rows:
        return Text("No ingested documents. Press i to queue an ingest job.", style="muted")
    most = max(r["n_children"] for r in rows)
    cursor = view.get("cursor", 0)
    out: list[RenderableType] = []
    last_doc = None
    for i, row in enumerate(rows):
        if row["document_id"] != last_doc:
            last_doc = row["document_id"]
            run = row["run"]
            out.append(
                Text.assemble(
                    ("▾ ", "muted"),
                    (row["document_id"][:28], "label"),
                    (f"  {run['n_parents']}p {run['n_children']}c {run['strategy']}", "muted"),
                )
            )
        preview = " ".join(row["text"].split())[:26]
        line = Text.assemble(
            ("> " if i == cursor else "  ", "marker"),
            (f"p{row['index']:<3}", "key"),
            (f"{preview:<27}", "selected" if i == cursor else "foreground"),
            (f"{row['n_children']:>4}c ", "muted"),
        )
        line.append_text(_bar(row["n_children"], most))
        out.append(line)
    return Group(*out)


def _children(state: TUIState) -> RenderableType:
    view = state.ingest_view
    kids = selected_children(view)
    if not kids:
        return Text("Loading…" if view.get("pending") else "No children.", style="muted")
    cursor = view.get("child_cursor", 0)
    lines = []
    for i, child in enumerate(kids):
        mark = "> " if i == cursor else "  "
        topic = f" [{child['topic']}]" if child.get("topic") else ""
        sfl = " ·sfl" if child.get("sfl") else ""
        lines.append(
            Text.assemble(
                (mark, "marker"),
                (f"c{i:<3}", "key"),
                (child["text"], "selected" if i == cursor else "foreground"),
                (topic, "accent"),
                (sfl, "success"),
            )
        )
    return Group(*lines)


def _tokens_table(child: dict[str, Any], deps: bool) -> Table:
    table = Table(box=None, padding=(0, 1), show_header=True, header_style="label")
    table.add_column("token")
    table.add_column("POS", style="accent")
    if deps:
        table.add_column("dep", style="info")
        table.add_column("→ head")
    else:
        table.add_column("lemma", style="muted")
        table.add_column("tag", style="muted")
    table.add_column("morphology", style="muted")
    tokens = child.get("tokens") or []
    for tok in tokens:
        morph = "|".join(f"{k}={v}" for k, v in (tok.get("morph") or {}).items())
        if deps:
            head = tok.get("head")
            head_text = ""
            if isinstance(head, int) and 0 <= head < len(tokens) and tok.get("dep") != "ROOT":
                head_text = f"→ {tokens[head].get('text', '')}"
            table.add_row(
                tok.get("text", ""), tok.get("pos", ""), tok.get("dep", ""), head_text, morph
            )
        else:
            table.add_row(
                tok.get("text", ""),
                tok.get("pos", ""),
                tok.get("lemma", ""),
                tok.get("tag", ""),
                morph,
            )
    return table


def _groups(child: dict[str, Any]) -> RenderableType:
    groups = child.get("groups") or {}
    noun = groups.get("noun_chunks") or []
    clauses = groups.get("clauses") or []
    lines = [Text("noun chunks", style="label")]
    lines += [Text(f"  [{g.get('text', '')}]", style="foreground") for g in noun] or [
        Text("  none", style="muted")
    ]
    lines.append(Text("clauses", style="label"))
    lines += [
        Text.assemble((f"  {c.get('dep', ''):<9}", "info"), (c.get("text", ""), "foreground"))
        for c in clauses
    ] or [Text("  none", style="muted")]
    return Group(*lines)


def _sfl(child: dict[str, Any]) -> RenderableType:
    sfl = child.get("sfl")
    if not sfl:
        return Text("Not tagged. Press s to queue an sfl_tag job.", style="muted")
    lines = []
    for key in ("mood", "modality", "tenor"):
        lines.append(Text.assemble((f"{key:<9}", "label"), (str(sfl.get(key, "")), "foreground")))
    for key in ("theme", "rheme"):
        if sfl.get(key):
            lines.append(Text.assemble((f"{key:<9}", "label"), (str(sfl[key]), "foreground")))
    if sfl.get("cohesive_markers"):
        markers = ", ".join(map(str, sfl["cohesive_markers"]))
        lines.append(Text.assemble(("cohesive ", "label"), (markers, "foreground")))
    pass1 = sfl.get("pass1") or {}
    for key in ("participants", "processes", "circumstances"):
        if pass1.get(key):
            lines.append(
                Text.assemble(
                    (f"{key:<14}", "muted"), (", ".join(map(str, pass1[key])), "foreground")
                )
            )
    return Group(*lines)


def _compare(view: dict[str, Any]) -> RenderableType:
    data = view.get("compare") or {}
    runs = (data.get("runs") or [])[:2]
    if len(runs) < 2:
        return Text(
            "Only one run for this document. Press r to re-ingest with another strategy.",
            style="muted",
        )
    table = Table(box=None, padding=(0, 2), header_style="label")
    table.add_column("")
    for run in runs:
        label = f"run {run['id']} {run['strategy']}" + (" ●" if run["is_active"] else "")
        table.add_column(label)
    for key in (
        "n_parents",
        "n_children",
        "mean_len",
        "p95_len",
        "entity_vetoes",
        "chunker_version",
    ):
        values = [run[key] for run in runs]
        table.add_row(key, *(f"{v:.1f}" if isinstance(v, float) else str(v) for v in values))
    same = runs[0]["source_hash"] == runs[1]["source_hash"]
    note = Text(
        "same source text" if same else "source text differs",
        style="success" if same else "warning",
    )
    return Group(table, note)


def _picker(view: dict[str, Any]) -> RenderableType:
    cursor = view.get("picker_cursor", 0)
    lines = [Text("Re-ingest notebook with:", style="label")]
    for i, name in enumerate(STRATEGY_CHOICES):
        lines.append(
            Text.assemble(
                ("> " if i == cursor else "  ", "marker"),
                (name, "selected" if i == cursor else "foreground"),
            )
        )
    lines.append(key_hints([("enter", "queue"), ("esc", "cancel")]))
    return Group(*lines)


def render_ingest(state: TUIState) -> tuple[Any, Any, Any]:
    """Return (tree panel, children panel, detail panel)."""
    view = state.ingest_view
    if not state.selected_notebook:
        msg = message_panel("Select a notebook in 1 Notebooks first.", "Ingest")
        return msg, panel(Text(""), "Children"), panel(Text(""), "Detail")
    if view.get("error"):
        err = message_panel(view["error"], "Ingest", style="error")
        return err, panel(Text(""), "Children"), panel(Text(""), "Detail")

    title = "Documents / Parents" + (
        " (loading)" if "runs" in (view.get("pending") or set()) else ""
    )
    tree = panel(_tree(state), title, focused=True)
    kids = panel(_children(state), "Children")

    if view.get("picker"):
        detail_body: RenderableType = _picker(view)
        detail_title = "Strategy"
    elif view.get("show_compare"):
        detail_body = _compare(view)
        detail_title = "Compare runs"
    else:
        mode = view.get("detail", DETAIL_VIEWS[0])
        child = selected_child(view)
        if child is None:
            detail_body = Text("Select a child.", style="muted")
        elif mode == "groups":
            detail_body = _groups(child)
        elif mode == "sfl":
            detail_body = _sfl(child)
        else:
            detail_body = _tokens_table(child, deps=mode == "deps")
        detail_title = f"Detail · {mode}"
    detail = panel(Group(detail_body, Text(""), key_hints(INGEST_KEYS, sep="  ")), detail_title)
    return tree, kids, detail
