"""``generate`` job handler: send the previewed prompt, wait, and download the audio overview."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ...views.compiler_gen import run_generate
from ..runner import JobContext

GenerateFn = Callable[..., Awaitable[None]]


async def run_generate_job(ctx: JobContext, *, generate_fn: GenerateFn = run_generate) -> str:
    """Run generation for the queued payload and mirror phases into the job store."""
    if ctx.state is None:
        raise RuntimeError("generate job requires TUI state")
    ctx.phase("submitted")
    await generate_fn(
        ctx.state,
        dict(ctx.payload),
        progress=ctx.phase,
        before_api=ctx.acquire_token,
    )
    return f"audio saved to {ctx.state.compiler_state.get('mp3_path')}"


async def handle(ctx: JobContext) -> str | None:
    return await run_generate_job(ctx)
