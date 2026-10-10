"""Background loading for the Ingest and Fact-check modes.

Queries run on one worker thread (``asyncio.run`` over ``_app.corpus``) and
write whole keys into ``state.ingest_view`` / ``state.factcheck_view``. A
``generation`` counter drops results that arrive after the notebook changed.
Renderers only read the dicts; they never touch the database.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ..state import TUIState

logger = logging.getLogger(__name__)

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="nblm-corpus")

#: Detail-pane views in the Ingest mode, in ``v`` cycle order.
DETAIL_VIEWS = ("tokens", "deps", "groups", "sfl")
#: Ingest strategies offered by the ``r`` picker.
STRATEGY_CHOICES = ("recursive", "cluster_semantic", "dynamic_window")
#: Fact-check verdict filters bound to ``a``/``c``/``u``.
VERDICT_FILTERS: dict[str, str | None] = {"a": None, "c": "contradicted", "u": "unverifiable"}


def _session_factory() -> Any:
    from ...db.session import async_session_maker

    return async_session_maker()


def _submit(
    view: dict[str, Any],
    key: str,
    query: Callable[[Any], Awaitable[Any]],
    session_factory: Callable[[], Any] = _session_factory,
) -> concurrent.futures.Future:
    generation = view.get("generation", 0)

    async def _run() -> Any:
        async with session_factory() as session:
            return await query(session)

    def _work() -> None:
        try:
            result = asyncio.run(_run())
        except Exception as e:
            logger.exception("Corpus query %s failed", key)
            if view.get("generation", 0) == generation:
                view["error"] = f"{type(e).__name__}: {e}"
            return
        if view.get("generation", 0) == generation:
            view[key] = result
            view["error"] = None

    future = _executor.submit(_work)
    view.setdefault("pending", set()).add(key)
    future.add_done_callback(lambda _f: view.get("pending", set()).discard(key))
    return future


# -- Ingest mode ------------------------------------------------------------


def parent_rows(view: dict[str, Any]) -> list[dict[str, Any]]:
    """Flattened rows for the left pane: one per parent, tagged with its document."""
    rows: list[dict[str, Any]] = []
    for run in view.get("runs") or []:
        for parent in (view.get("parents") or {}).get(run["id"], []):
            rows.append({**parent, "document_id": run["document_id"], "run": run})
    return rows


def selected_parent(view: dict[str, Any]) -> dict[str, Any] | None:
    rows = parent_rows(view)
    if not rows:
        return None
    cursor = max(0, min(view.get("cursor", 0), len(rows) - 1))
    return rows[cursor]


def load_ingest(state: TUIState, *, force: bool = False) -> None:
    """(Re)load runs and parents for the selected notebook."""
    view = state.ingest_view
    notebook_id = state.selected_notebook
    if not notebook_id:
        return
    if not force and view.get("notebook_id") == notebook_id and "runs" in view:
        return
    view["generation"] = view.get("generation", 0) + 1
    view.update(
        notebook_id=notebook_id,
        cursor=0,
        child_cursor=0,
        children={},
        parents={},
        compare=None,
    )
    view.pop("runs", None)

    async def _query(session: Any) -> list[dict[str, Any]]:
        from ..._app import corpus

        runs = await corpus.active_runs(session, notebook_id)
        view["parents"] = {r["id"]: await corpus.parents(session, r["id"]) for r in runs}
        return runs

    _submit(view, "runs", _query)


def load_children(state: TUIState) -> None:
    view = state.ingest_view
    parent = selected_parent(view)
    if parent is None or parent["id"] in (view.get("children") or {}):
        return
    parent_id = parent["id"]

    async def _query(session: Any) -> dict[int, list[dict[str, Any]]]:
        from ..._app import corpus

        return {
            **(view.get("children") or {}),
            parent_id: await corpus.children(session, parent_id),
        }

    _submit(view, "children", _query)


def load_compare(state: TUIState) -> None:
    view = state.ingest_view
    parent = selected_parent(view)
    if parent is None:
        return
    document_id = parent["document_id"]

    async def _query(session: Any) -> dict[str, Any]:
        from ..._app import corpus

        return {
            "document_id": document_id,
            "runs": await corpus.document_runs(session, document_id),
        }

    _submit(view, "compare", _query)


def selected_children(view: dict[str, Any]) -> list[dict[str, Any]]:
    parent = selected_parent(view)
    if parent is None:
        return []
    return (view.get("children") or {}).get(parent["id"], [])


def selected_child(view: dict[str, Any]) -> dict[str, Any] | None:
    kids = selected_children(view)
    if not kids:
        return None
    return kids[max(0, min(view.get("child_cursor", 0), len(kids) - 1))]


# -- Fact-check mode --------------------------------------------------------


def load_claims(state: TUIState, *, force: bool = False) -> None:
    view = state.factcheck_view
    notebook_id = state.selected_notebook
    if not notebook_id:
        return
    verdict = view.get("filter")
    key = (notebook_id, verdict)
    if not force and view.get("loaded_key") == key and "claims" in view:
        return
    view["generation"] = view.get("generation", 0) + 1
    view.update(loaded_key=key, cursor=0)
    view.pop("claims", None)

    async def _query(session: Any) -> list[dict[str, Any]]:
        from ..._app import corpus

        return await corpus.claims(session, notebook_id, verdict)

    _submit(view, "claims", _query)


def selected_claim(view: dict[str, Any]) -> dict[str, Any] | None:
    claims = view.get("claims") or []
    if not claims:
        return None
    return claims[max(0, min(view.get("cursor", 0), len(claims) - 1))]


def is_loading(state: TUIState) -> bool:
    return bool(state.ingest_view.get("pending") or state.factcheck_view.get("pending"))
