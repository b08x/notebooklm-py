"""Compile and generate audio overviews from the Compiler view (facts 1–14, 18–20).

Two background workers drive the flow:

* ``start_compile`` — load the selected audio YAML, bind it to the sidebar
  notebook, fill template slots from the notebook's ingested clauses (RRF
  retrieval + one LLM call, NotebookLM chat as the fallback), and compile the
  prompt shown in the preview panel.
* ``start_generate`` — send the exact previewed prompt (including any
  ``$EDITOR`` edits) to NotebookLM with the YAML's format/length, wait for
  completion, download the MP3 under ``~/Archive/NotebookLM/audio/``, and
  write a sidecar JSON recording the run (facts 10–11).

Both run on throwaway ``ThreadPoolExecutor`` threads following the existing
``tui/views/notebook_detail.py`` pattern: each worker calls ``asyncio.run``
with its own ``NotebookLMClient.from_storage()``, satisfying the
one-client-per-event-loop rule.
"""

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import dspy

from notebooklm._app.archive import slugify
from notebooklm.client import NotebookLMClient
from notebooklm.types import AudioFormat, AudioLength

from ..compiler_bridge import compile_audio_config, load_audio_project
from ..state import TUIState

logger = logging.getLogger(__name__)

#: Warning threshold for the compiled prompt's character count (fact 5). The
#: count is only a warning — it never blocks sending.
PROMPT_CHAR_WARNING = 5000

#: ``wait_for_completion`` budget for one generation (plan Step 5).
GENERATION_TIMEOUT = 1200.0

_ACTIVE_PHASES = ("compiling", "submitted", "generating", "downloading")


# ---------------------------------------------------------------------------
# Format / length mapping (fact 8, fact 14)
# ---------------------------------------------------------------------------


def _map_enum(value: str, enum_cls: Any, kind: str):
    normalized = value.strip().replace("-", "_").upper()
    if not normalized or normalized == "DEFAULT":
        return None
    try:
        return enum_cls[normalized]
    except KeyError:
        choices = ", ".join(m.name.lower().replace("_", "-") for m in enum_cls)
        raise ValueError(f"unknown {kind} {value!r} — valid choices: default, {choices}") from None


def to_audio_enums(fmt: str, length: str) -> tuple[AudioFormat | None, AudioLength | None]:
    """Map YAML ``audio_format`` / ``audio_length`` strings onto the client enums.

    ``"default"`` or empty maps to ``None`` (the API default); an unknown value
    raises ``ValueError`` naming the valid choices, which the caller surfaces
    at compile time so the preview shows the error before anything is sent.
    """
    return (
        _map_enum(fmt, AudioFormat, "audio_format"),
        _map_enum(length, AudioLength, "audio_length"),
    )


# ---------------------------------------------------------------------------
# RRF-grounded slot filling (facts 3, 18–20)
# ---------------------------------------------------------------------------


class CompilerSlotSignature(dspy.Signature):
    """Fill audio-compiler template slots grounded ONLY in the given context clauses."""

    topic = dspy.InputField(desc="The audio overview's topic directive.")
    context = dspy.InputField(
        desc="Retrieved notebook clauses labelled [C1], [C2], ..., most relevant first."
    )
    agreement = dspy.OutputField(
        desc="One-line source-grounded checkpoint/agreement state (no brackets)."
    )
    confusion = dspy.OutputField(
        desc="One-line source-grounded desync/mismatch state (no brackets)."
    )
    frustration = dspy.OutputField(
        desc="One-line source-grounded bottleneck/exhaustion state (no brackets)."
    )
    brainstorm = dspy.OutputField(
        desc="One-line source-grounded open speculative question (no brackets)."
    )
    topics = dspy.OutputField(
        desc="Three or four distinct core mechanisms or debate topics, one per line."
    )
    escalations = dspy.OutputField(
        desc="Up to two compound failure escalations, one per line, each formatted "
        "'State A + State B :: source-grounded diagnostic :: tier'."
    )
    citations = dspy.OutputField(
        desc="Clause ids cited per slot, one per line as 'agreement: C3, C7; confusion: C1' "
        "covering all six slots (agreement, confusion, frustration, brainstorm, topics, escalations)."
    )


@dataclass
class SlotFill:
    """Slot values written into the config, with the clauses they came from."""

    evidence: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


#: Slot group -> retrieval hint appended to ``config.topic`` (plan Step 1b).
_SLOT_HINTS: dict[str, str] = {
    "agreement": "agreement, confirmed checkpoint, successful verification",
    "confusion": "confusion, desync, structural mismatch, misrouting",
    "frustration": "frustration, bottleneck, resource exhaustion, latency",
    "brainstorm": "brainstorm, open speculative design question, future consideration",
    "topics": "core mechanisms and analytical topics",
    "escalations": "compound failure modes and escalation paths",
}


def _parse_citations(text: str) -> dict[str, list[str]]:
    """Parse the signature's ``citations`` output into ``{slot: [label, ...]}``."""
    cited: dict[str, list[str]] = {}
    for chunk in text.replace("\n", " ").split(";"):
        if ":" not in chunk:
            continue
        slot, labels = chunk.split(":", 1)
        slot = slot.strip().lower()
        ids = [tok.strip() for tok in labels.split(",") if tok.strip()]
        if slot and ids:
            cited.setdefault(slot, []).extend(ids)
    return cited


def _wrap_slot(value: str) -> str:
    """Match the YAML convention of bracketed lexical slot values."""
    value = value.strip()
    return value if value.startswith("[") else f"[{value}]"


def _make_escalation(config: Any, compound: str, diagnostic: str, tier: str) -> Any:
    """Build an escalation matching the config's existing model class."""
    sample = config.escalations[0] if config.escalations else None
    if sample is not None:
        return sample.__class__(compound=compound, diagnostic=diagnostic, tier=tier)
    return {"compound": compound, "diagnostic": diagnostic, "tier": tier}


async def fill_slots_from_clauses(
    client: NotebookLMClient,
    session: Any,
    notebook_id: str,
    config: Any,
    lm: Any,
) -> SlotFill | None:
    """Fill the config's template slots from the notebook's ingested clauses.

    Returns ``None`` when the notebook has nothing ingested — the caller falls
    back to the NotebookLM chat extractor and sets a warning (fact 3). The LLM
    call runs under ``dspy.context(lm=lm)`` with the LM captured on the main
    thread; ``setup_dspy_router`` is never called here (fact 20).
    """
    from notebooklm._app.clause_search import _notebook_document_ids, rrf_search

    document_ids = await _notebook_document_ids(client, notebook_id)
    if not document_ids:
        return None

    topic = config.topic or config.title
    retrieved: dict[str, list[Any]] = {}
    for slot, hint in _SLOT_HINTS.items():
        retrieved[slot] = await rrf_search(session, document_ids, f"{topic} — {hint}", top_k=8)
    if not any(retrieved.values()):
        return None

    # Deduplicate clauses across slot groups into stable [C<n>] labels.
    by_label: dict[str, Any] = {}
    by_id: dict[str, str] = {}
    for slot in _SLOT_HINTS:
        for match in retrieved[slot]:
            if match.clause_id not in by_id:
                label = f"C{len(by_label) + 1}"
                by_label[label] = match
                by_id[match.clause_id] = label
    context = "\n\n".join(f"[{label}] {m.text}" for label, m in by_label.items())

    with dspy.context(lm=lm):
        prediction = dspy.Predict(CompilerSlotSignature)(topic=topic, context=context)

    config.lexical_dictionary.agreement = _wrap_slot(prediction.agreement)
    config.lexical_dictionary.confusion = _wrap_slot(prediction.confusion)
    config.lexical_dictionary.frustration = _wrap_slot(prediction.frustration)
    config.lexical_dictionary.brainstorm = _wrap_slot(prediction.brainstorm)

    topics = [re.sub(r"^[-•0-9.]+\s*", "", line).strip() for line in prediction.topics.splitlines()]
    topics = [t for t in topics if t][:4]
    if topics:
        config.topics = topics

    escalations = []
    for line in prediction.escalations.splitlines():
        parts = [p.strip() for p in line.split("::")]
        if len(parts) != 3:
            continue
        compound, diagnostic, tier = parts
        if compound:
            escalations.append(_make_escalation(config, compound, diagnostic, tier))
    if escalations:
        config.escalations = escalations[:2]

    cited = _parse_citations(getattr(prediction, "citations", ""))
    evidence: dict[str, list[tuple[str, str]]] = {}
    for slot in _SLOT_HINTS:
        labels = [lab for lab in cited.get(slot, []) if lab in by_label]
        if not labels:
            labels = [by_id[m.clause_id] for m in retrieved[slot] if m.clause_id in by_id][:2]
        evidence[slot] = [(by_label[lab].clause_id, by_label[lab].text) for lab in labels]
    return SlotFill(evidence=evidence)


async def _chat_fallback(client: NotebookLMClient, notebook_id: str, config: Any) -> Any:
    """NotebookLM-chat slot extraction (``auto_bind``) — fallback when no clauses are ingested."""
    from compiler.auto_bind import auto_populate_from_notebook

    return await auto_populate_from_notebook(client, notebook_id, config, verbose=False)


# ---------------------------------------------------------------------------
# Compile worker (facts 1–5)
# ---------------------------------------------------------------------------


def start_compile(state: TUIState, project_file: str | Path) -> None:
    """Compile ``project_file`` against the notebook selected in the sidebar."""
    cs = state.compiler_state
    if cs.get("phase") in _ACTIVE_PHASES:
        return
    if not state.selected_notebook:
        cs["error"] = "select a notebook first"
        return

    from notebooklm._app.assessment import setup_dspy_router

    try:
        setup_dspy_router()
        lm = dspy.settings.lm
    except Exception as e:
        logger.warning("DSPy router unavailable; slot filling will fall back: %s", e)
        lm = None

    for key in ("error", "warning", "prompt", "edited", "evidence", "scroll"):
        cs.pop(key, None)
    cs["phase"] = "compiling"
    cs["project_yaml"] = str(project_file)
    cs["notebook_id"] = state.selected_notebook

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.compiler_task = executor.submit(
        _run_compile, state, Path(project_file), state.selected_notebook, lm
    )


def _run_compile(state: TUIState, project_file: Path, notebook_id: str, lm: Any) -> None:
    cs = state.compiler_state
    try:
        config = load_audio_project(project_file)
        # Bind to the sidebar selection; the YAML file itself is never written (fact 2).
        config.notebook_id = notebook_id
        audio_format, audio_length = to_audio_enums(config.audio_format, config.audio_length)

        async def _bind() -> tuple[str, str | None, dict[str, list[tuple[str, str]]]]:
            warning: str | None = None
            evidence: dict[str, list[tuple[str, str]]] = {}
            async with NotebookLMClient.from_storage() as client:
                notebook = await client.notebooks.get(notebook_id)
                if config.auto_extract:
                    # Slot extraction failures never fail the compile — the
                    # YAML's own values are kept with a warning (fact 3).
                    try:
                        from notebooklm.db.session import async_session_maker

                        async with async_session_maker() as session:
                            fill = await fill_slots_from_clauses(
                                client, session, notebook_id, config, lm
                            )
                        if fill is not None:
                            evidence = fill.evidence
                        else:
                            # No ingested clauses — chat fallback (fact 3).
                            await _chat_fallback(client, notebook_id, config)
                            warning = (
                                "No ingested clauses found — slots filled via "
                                "NotebookLM chat fallback."
                            )
                    except Exception as e:
                        warning = f"Slot extraction failed ({e}); the YAML's own values were used."
                else:
                    try:
                        await _chat_fallback(client, notebook_id, config)
                    except Exception as e:
                        warning = f"Notebook binding failed ({e}); the YAML's own values were used."
                return notebook.title, warning, evidence

        notebook_title, warning, evidence = asyncio.run(_bind())
        prompt = compile_audio_config(config)
    except Exception as e:
        logger.exception("Compiler: compile of %s failed", project_file)
        cs["phase"] = "error"
        cs["error"] = str(e)
        return

    cs.update(
        {
            "phase": "compiled",
            "prompt": prompt,
            "edited": False,
            "project": project_file.stem,
            "template": config.template,
            "notebook_title": notebook_title,
            "audio_format": config.audio_format,
            "audio_length": config.audio_length,
            "warning": warning,
            "evidence": evidence,
            "scroll": 0,
        }
    )


# ---------------------------------------------------------------------------
# $EDITOR handoff (fact 6)
# ---------------------------------------------------------------------------


@dataclass
class EditorResult:
    """Outcome of one ``$EDITOR`` round trip over the compiled prompt."""

    text: str
    edited: bool
    error: str | None = None


def _resolve_editor() -> str:
    return os.environ.get("EDITOR") or shutil.which("nvim") or "vi"


def edit_prompt_via_editor(text: str, run: Callable[..., Any] = subprocess.run) -> EditorResult:
    """Open ``text`` in ``$EDITOR`` (nvim, then vi) and return the edited result.

    The edit is never written back to the YAML or the template (fact 6). A
    missing editor or a non-zero exit leaves the text unchanged with an error.
    """
    editor = _resolve_editor()
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf:
        path = Path(tf.name)
        tf.write(text.encode("utf-8"))
    try:
        path.write_text(text, encoding="utf-8")
        try:
            proc = run([editor, str(path)])
        except FileNotFoundError:
            return EditorResult(
                text, edited=False, error=f"Editor {editor!r} not found — prompt unchanged."
            )
        if proc.returncode != 0:
            return EditorResult(
                text,
                edited=False,
                error=f"Editor exited with {proc.returncode} — prompt unchanged.",
            )
        new_text = path.read_text(encoding="utf-8")
        return EditorResult(new_text, edited=new_text != text)
    finally:
        path.unlink(missing_ok=True)


def apply_editor_result(state: TUIState, result: EditorResult) -> None:
    """Fold an editor round trip back into the compiler state."""
    cs = state.compiler_state
    if result.error:
        cs["error"] = result.error
    elif result.edited:
        cs["prompt"] = result.text
        cs["edited"] = True
        cs["scroll"] = 0


# ---------------------------------------------------------------------------
# Generate worker (facts 7–12)
# ---------------------------------------------------------------------------


def audio_output_base(
    project_slug: str,
    notebook_title: str,
    now: datetime | None = None,
    audio_dir: str | None = None,
) -> Path:
    """``<root>/<project-slug>/<YYYYMMDD-HHMM>_<notebook-slug>`` (no extension).

    The root is ``$NOTEBOOKLM_AUDIO_DIR`` or ``~/Archive/NotebookLM/audio``;
    the env override exists so tests never touch ``$HOME`` (plan Step 5).
    """
    root = Path(
        audio_dir
        or os.environ.get("NOTEBOOKLM_AUDIO_DIR")
        or Path.home() / "Archive" / "NotebookLM" / "audio"
    )
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M")
    return root / slugify(project_slug) / f"{stamp}_{slugify(notebook_title)}"


def start_generate(state: TUIState) -> None:
    """Send the previewed prompt to NotebookLM (fact 7's ``y``)."""
    cs = state.compiler_state
    prompt = cs.get("prompt")
    if not prompt or not state.selected_notebook:
        return
    if cs.get("phase") in _ACTIVE_PHASES:
        return

    cs["confirm"] = False
    cs["phase"] = "submitted"
    cs["error"] = None
    cs["artifact_id"] = None
    cs["started_at"] = time.time()
    base = audio_output_base(cs.get("project") or "project", cs.get("notebook_title") or "notebook")
    cs["output_base"] = str(base)

    payload = {
        "notebook_id": state.selected_notebook,
        "notebook_title": cs.get("notebook_title") or state.selected_notebook,
        "prompt": prompt,
        "edited": bool(cs.get("edited")),
        "project_yaml": cs.get("project_yaml"),
        "project": cs.get("project"),
        "template": cs.get("template"),
        "audio_format": cs.get("audio_format"),
        "audio_length": cs.get("audio_length"),
        "evidence": cs.get("evidence") or {},
        "output_base": str(base),
        "started_at": cs["started_at"],
    }

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.compiler_task = executor.submit(_run_generate, state, payload)


def _sidecar_data(
    payload: dict[str, Any],
    *,
    status: str,
    error: str | None,
    artifact_id: str | None,
    finished_at: float,
) -> dict[str, Any]:
    return {
        "project_yaml": payload.get("project_yaml"),
        "template": payload.get("template"),
        "notebook_id": payload["notebook_id"],
        "notebook_title": payload["notebook_title"],
        "artifact_id": artifact_id,
        "audio_format": payload.get("audio_format"),
        "audio_length": payload.get("audio_length"),
        "prompt": payload["prompt"],
        "edited": payload["edited"],
        "slot_evidence": {
            slot: [{"clause_id": cid, "text": text} for cid, text in clauses]
            for slot, clauses in (payload.get("evidence") or {}).items()
        },
        "started_at": datetime.fromtimestamp(payload["started_at"]).isoformat(),
        "finished_at": datetime.fromtimestamp(finished_at).isoformat(),
        "status": status,
        "error": error,
    }


def _write_sidecar(base: Path, data: dict[str, Any]) -> Path:
    path = base.with_suffix(".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _run_generate(state: TUIState, payload: dict[str, Any]) -> None:
    """Generate, wait, download, and write the sidecar. Every path writes a sidecar (fact 11)."""
    cs = state.compiler_state
    base = Path(payload["output_base"])
    artifact_id: str | None = None
    error: str | None = None
    mp3_path: Path | None = None

    async def _pipeline() -> None:
        nonlocal artifact_id, mp3_path
        fmt, length = to_audio_enums(
            payload.get("audio_format") or "default",
            payload.get("audio_length") or "default",
        )
        async with NotebookLMClient.from_storage() as client:
            status = await client.artifacts.generate_audio(
                notebook_id=payload["notebook_id"],
                instructions=payload["prompt"],
                audio_format=fmt,
                audio_length=length,
            )
            artifact_id = status.task_id
            cs["artifact_id"] = artifact_id
            cs["phase"] = "generating"
            final = await client.artifacts.wait_for_completion(
                payload["notebook_id"],
                artifact_id,
                initial_interval=10.0,
                max_interval=20.0,
                timeout=GENERATION_TIMEOUT,
            )
            if not final.is_complete:
                raise RuntimeError(f"generation did not complete: {final.status}")
            cs["phase"] = "downloading"
            mp3_path = base.with_suffix(".mp3")
            mp3_path.parent.mkdir(parents=True, exist_ok=True)
            await client.artifacts.download_audio(
                payload["notebook_id"],
                output_path=str(mp3_path),
                artifact_id=artifact_id,
            )

    try:
        asyncio.run(_pipeline())
    except Exception as e:
        logger.exception("Compiler: audio generation failed")
        error = str(e)
        cs["phase"] = "failed"
        cs["error"] = error
        if artifact_id:
            cs["artifact_id"] = artifact_id
        # The prompt and edited flag are kept so `g` retries (fact 12).
    else:
        cs["phase"] = "done"
        cs["error"] = None
        cs["mp3_path"] = str(mp3_path)

    cs["finished_at"] = time.time()
    try:
        sidecar = _write_sidecar(
            base,
            _sidecar_data(
                payload,
                status="failed" if error else "done",
                error=error,
                artifact_id=artifact_id,
                finished_at=cs["finished_at"],
            ),
        )
        cs["sidecar_path"] = str(sidecar)
    except Exception as e:
        logger.exception("Compiler: sidecar write failed")
        if cs.get("error") is None:
            cs["error"] = f"sidecar write failed: {e}"
        else:
            cs["error"] = f"{cs['error']}; sidecar write failed: {e}"
