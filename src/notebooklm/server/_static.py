"""Serve the built Corpus Explorer SPA (``web/`` → ``static/ui``) at ``/ui``.

``vite build`` writes ``index.html`` and hashed assets into
``src/notebooklm/server/static/ui``. Unknown paths under ``/ui`` fall back to
``index.html`` so client-side routes survive a reload. The shell is public (it
carries no data); the app asks for the server token and sends it on every
``/v1`` call.

This module imports NO ``click`` / ``rich`` / ``cli``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

UI_DIR = Path(__file__).parent / "static" / "ui"

_NOT_BUILT = (
    "<!doctype html><title>Corpus Explorer</title>"
    "<p>The Corpus Explorer UI is not built. Run <code>pnpm -C web build</code>.</p>"
)


class SPAStaticFiles(StaticFiles):
    """``StaticFiles(html=True)`` that answers unknown paths with ``index.html``."""

    async def get_response(self, path: str, scope: Any) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            response = await super().get_response("index.html", scope)
        if response.status_code == 404:
            response = await super().get_response("index.html", scope)
        return response


def mount_ui(app: FastAPI, directory: Path = UI_DIR) -> None:
    @app.get("/", include_in_schema=False)
    async def _root() -> RedirectResponse:
        return RedirectResponse("/ui/")

    if (directory / "index.html").is_file():
        app.mount("/ui", SPAStaticFiles(directory=directory, html=True), name="ui")
        return

    @app.get("/ui", include_in_schema=False)
    @app.get("/ui/{path:path}", include_in_schema=False)
    async def _not_built(path: str = "") -> HTMLResponse:
        return HTMLResponse(_NOT_BUILT, status_code=503)
