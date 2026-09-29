"""Live smoke test for the notebook-curation goal (throwaway notebook).

Runs the exact business-logic layer the TUI dispatches to, against the real
account, local Postgres, and the real archive root:

1. Add a source.
2. Remove items with a reason.
3. Archive; inspect the tarball.
4. Decline the delete; confirm the notebook is kept.
5. Archive again, confirm the delete; check the notebook is gone and the
   removal_log / archived_notebooks rows exist.
"""

from __future__ import annotations

import asyncio
import json
import sys

from notebooklm._app.archive import execute_archive_delete, run_archive
from notebooklm._app.curation import (
    execute_add_source,
    execute_remove_items,
    list_curation_items,
)
from notebooklm.client import NotebookLMClient
from notebooklm.db.session import async_session_maker

TITLE = "curation-smoke"


def log(step: str, **kw: object) -> None:
    print(f"[smoke] {step} :: {json.dumps(kw, default=str)}", flush=True)


async def main() -> int:
    async with (
        NotebookLMClient.from_storage() as client,
        async_session_maker() as session,
    ):
        # --- setup: throwaway notebook with 1 URL source, 1 text source, a note ---
        nb = await client.notebooks.create(TITLE)
        nb_id = nb.id
        log("created notebook", id=nb_id, title=nb.title)

        await execute_add_source(client, nb_id, "url", "https://example.com")
        await execute_add_source(client, nb_id, "text", "Hallucinated content about a fake study.")
        note = await client.notes.create(
            nb_id, title="Experiment note", content="Throwaway note body."
        )
        log("sources+note added", note_id=note.id)

        report = None
        try:
            status = await client.artifacts.generate_report(nb_id)
            log("report generation started", task_id=status.task_id)
            report = await client.artifacts.wait_for_completion(nb_id, status.task_id, timeout=240)
            log("report generated", status=str(report))
        except Exception as exc:
            log("report generation unavailable (continuing without it)", error=str(exc))

        items = await list_curation_items(client, nb_id)
        log("curation items", count=len(items), kinds=[i.kind for i in items])

        # --- step 1: add a source (a second URL, live) ------------------------
        added = await execute_add_source(
            client, nb_id, "url", "https://www.iana.org/help/example-domains"
        )
        log("step1 add source ok", id=added.id, title=added.title)

        # --- step 2: remove items with a reason -------------------------------
        targets = [item for item in items if item.kind == "note" or "Hallucinated" in item.title]
        assert targets, "expected at least one note and the text source to remove"
        result = await execute_remove_items(
            client, session, nb_id, nb.title, targets, "hallucinated"
        )
        log(
            "step2 removal",
            removed=[i.id for i in result.removed],
            failed=[(i.id, e) for i, e in result.failed],
        )
        assert not result.failed, "removal batch had failures"

        # --- step 3: archive; inspect the tarball -----------------------------
        progress: list[tuple[int, int]] = []
        archive1 = await run_archive(
            client, session, nb_id, "experimental", lambda d, t: progress.append((d, t))
        )
        log(
            "step3 archive",
            error=archive1.error,
            final=str(archive1.final_path),
            partial=str(archive1.partial_path),
            files=(archive1.verify.file_count if archive1.verify else None),
            verify_ok=(archive1.verify.ok if archive1.verify else None),
            progress_last=(progress[-1] if progress else None),
        )
        assert archive1.error is None, f"archive failed: {archive1.error}"
        assert archive1.final_path is not None, "archive did not finalize"

        # --- step 4: decline the delete; notebook stays -----------------------
        declined = await execute_archive_delete(client, session, archive1, "wrong title")
        still_there = await client.notebooks.get_or_none(nb_id)
        log(
            "step4 declined delete", declined=declined, notebook_still_there=still_there is not None
        )
        assert declined is False and still_there is not None, "decline must keep the notebook"

        # --- step 5: archive again, confirm the delete -------------------------
        archive2 = await run_archive(client, session, nb_id, "experimental", None)
        log(
            "step5 re-archive",
            error=archive2.error,
            final=str(archive2.final_path),
        )
        assert archive2.error is None and archive2.final_path is not None

        confirmed = await execute_archive_delete(client, session, archive2, "curation")
        gone = await client.notebooks.get_or_none(nb_id)
        log("step5 confirmed delete", confirmed=confirmed, notebook_gone=gone is None)
        assert confirmed is True and gone is None, "notebook must be gone after confirm"

        # --- check the DB records ---------------------------------------------
        from sqlalchemy import select

        from notebooklm.db.models import ArchivedNotebook, RemovalLog

        removal_rows = list(
            (
                await session.execute(select(RemovalLog).where(RemovalLog.notebook_id == nb_id))
            ).scalars()
        )
        archived_rows = list(
            (
                await session.execute(
                    select(ArchivedNotebook).where(ArchivedNotebook.notebook_id == nb_id)
                )
            ).scalars()
        )
        log(
            "db records",
            removal_log=[(r.action, r.item_type, r.reason, r.item_id) for r in removal_rows],
            archived_notebooks=[
                (r.title, r.remote_deleted, r.archive_path, len(r.document_ids))
                for r in archived_rows
            ],
        )
        assert any(r.action == "remove" for r in removal_rows), "removal_log missing remove rows"
        assert any(r.action == "archive" for r in removal_rows), "removal_log missing archive row"
        assert archived_rows and archived_rows[-1].remote_deleted is True

        print("[smoke] ALL STEPS PASSED", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
