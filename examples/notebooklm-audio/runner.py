"""Async orchestration runner for automated NotebookLM Audio Overview synthesis.

Automates the ingestion of existing notebook metadata and source-grounded RAG extraction
to render complete audio prompt scripts without manual string insertion.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Make local compiler available without installation when running directly
sys.path.insert(0, str(Path(__file__).resolve().parent))
# Ensure parent repository notebooklm library is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from compiler.auto_bind import auto_populate_from_notebook
from compiler.loaders import load_audio_config
from compiler.models import AudioProjectConfig
from compiler.prompt import compile_audio_prompt

from notebooklm import AudioFormat, AudioLength, NotebookLMClient

DEFAULT_PROJECT = Path(__file__).parent / "projects" / "custom-telemetry-session.yaml"


def to_audio_enums(fmt: str, length: str) -> tuple[AudioFormat | None, AudioLength | None]:
    """Map YAML ``audio_format`` / ``audio_length`` onto the client enums.

    "default" or empty maps to ``None`` (the API default). Duplicated from
    ``tui/views/compiler_gen.py`` — importing the TUI from examples is worse
    than six lines of duplication.
    """

    def _map(value, enum_cls):
        normalized = value.strip().replace("-", "_").upper()
        if not normalized or normalized == "DEFAULT":
            return None
        try:
            return enum_cls[normalized]
        except KeyError:
            choices = ", ".join(m.name.lower().replace("_", "-") for m in enum_cls)
            raise ValueError(
                f"unknown audio setting {value!r} — valid choices: default, {choices}"
            ) from None

    return _map(fmt, AudioFormat), _map(length, AudioLength)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile and execute an automated NotebookLM Audio Overview production."
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=str(DEFAULT_PROJECT),
        help="Path to declarative audio project YAML configuration.",
    )
    parser.add_argument(
        "-n",
        "--notebook-id",
        type=str,
        default=None,
        help="Explicit existing NotebookLM UUID to bind and extract sources from.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually invoke notebooklm-py to query sources and generate audio (default is dry-run preview).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="generated_diagnostic_session.mp3",
        help="Output filepath for downloaded MP3 when executing live generation.",
    )
    parser.add_argument(
        "--emit",
        action="store_true",
        help="After auto-binding, print ONLY the compiled prompt to stdout "
        "(diagnostics to stderr) so it can be piped into "
        "`notebooklm generate audio --prompt-file -`.",
    )
    return parser.parse_args()


async def execute_audio_pipeline(
    config: AudioProjectConfig, output_path: str, notebook_id: str | None = None
) -> None:
    """Async I/O execution pipeline using NotebookLMClient."""
    target_id = notebook_id or config.notebook_id
    if not target_id or target_id == "dfa4c86e-11b2-4d22-9018-000011112222":
        raise ValueError(
            "An explicit, valid existing notebook ID (-n / --notebook-id or in YAML) is required for live audio execution!"
        )

    audio_format, audio_length = to_audio_enums(config.audio_format, config.audio_length)

    print("Initializing async NotebookLM client from local storage...")
    async with NotebookLMClient.from_storage() as client:
        print(f"\n[1/4] Interrogating existing notebook ({target_id}) for auto-binding...")
        config = await auto_populate_from_notebook(client, target_id, config, verbose=True)

        print("\n[2/4] Compiling finalized zero-touch audio instructions script...")
        compiled_instructions = compile_audio_prompt(config)

        print("\n[3/4] Dispatching compiled dialogue synthesis instructions to Audio Studio...")
        gen_status = await client.artifacts.generate_audio(
            notebook_id=target_id,
            instructions=compiled_instructions,
            audio_format=audio_format,
            audio_length=audio_length,
        )
        print(f"      Task submitted successfully! Task ID: {gen_status.task_id}")

        print("\n[4/4] Polling status while Audio Studio synthesizes dialogue...")
        final_status = await client.artifacts.wait_for_completion(
            target_id,
            gen_status.task_id,
            initial_interval=10.0,
            max_interval=20.0,
            timeout=900.0,
        )

        if final_status.is_complete:
            print(f"\n✔ Synthesis complete! Downloading MP3 artifact to: {output_path}")
            await client.artifacts.download_audio(
                target_id,
                output_path=output_path,
                artifact_id=final_status.task_id,
            )
            print("  Download successful! Diagnostic session audio saved.")
        else:
            print(f"  [Error] Audio synthesis failed or timed out: {final_status}")


async def emit_compiled_prompt(config: AudioProjectConfig, notebook_id: str) -> None:
    """Auto-bind, then print only the compiled prompt to stdout (fact 13).

    Diagnostics go to stderr so the stdout pipe stays clean for
    ``notebooklm generate audio --prompt-file -``.
    """
    async with NotebookLMClient.from_storage() as client:
        config = await auto_populate_from_notebook(client, notebook_id, config, verbose=False)
        compiled = compile_audio_prompt(config)
        sys.stdout.write(compiled)
        sys.stdout.write("\n")
        sys.stdout.flush()
        print(f"[emit] compiled prompt: {len(compiled)} chars", file=sys.stderr)


def main() -> None:
    args = parse_args()
    project_file = Path(args.project).resolve()

    print("─── NotebookLM Automated Audio Prompt Compiler ────────────")
    print(f"Reading configuration specification: {project_file.name}")

    config = load_audio_config(project_file)
    if args.notebook_id:
        config.notebook_id = args.notebook_id

    # --emit: auto-bind against the notebook, then print only the compiled
    # prompt to stdout for piping into `notebooklm generate audio --prompt-file -`.
    if args.emit:
        if not args.notebook_id:
            print("[emit] --emit requires -n / --notebook-id", file=sys.stderr)
            sys.exit(2)
        print("[emit] binding and compiling...", file=sys.stderr)
        asyncio.run(emit_compiled_prompt(config, args.notebook_id))
        return

    # In dry-run mode without network execution, compile immediately with offline defaults
    if not args.execute:
        compiled = compile_audio_prompt(config)
        print(f"\n✔ Offline compiled project: [{config.title}]")
        print(f"  ├── Target Notebook: {config.notebook_id or 'Offline Specification'}")
        print(f"  ├── Template:        {config.template}")
        print(f"  ├── Format & Length: {config.audio_format} ({config.audio_length})")
        print(f"  └── Auto-Extract:    {config.auto_extract} (activates on live --execute)")

        print("\n─── COMPILATION OUTPUT PREVIEW (ZERO-TOUCH INSTRUCTIONS) ──")
        print(compiled)
        print("───────────────────────────────────────────────────────────")
        print("\n[Note] Dry-run preview complete. No network calls occurred.")
        print(
            "To execute against a live existing notebook and auto-extract diagnostic vocabulary from sources:"
        )
        print(
            f"  uv run examples/notebooklm-audio/runner.py {project_file} -n <NOTEBOOK_ID> --execute\n"
        )
    else:
        asyncio.run(execute_audio_pipeline(config, args.out, notebook_id=args.notebook_id))


if __name__ == "__main__":
    main()
