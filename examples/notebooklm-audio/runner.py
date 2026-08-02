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

from notebooklm import NotebookLMClient

DEFAULT_PROJECT = Path(__file__).parent / "projects" / "custom-telemetry-session.yaml"


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
                artifact_id=final_status.artifact_id,
            )
            print("  Download successful! Diagnostic session audio saved.")
        else:
            print(f"  [Error] Audio synthesis failed or timed out: {final_status}")


def main() -> None:
    args = parse_args()
    project_file = Path(args.project).resolve()

    print("─── NotebookLM Automated Audio Prompt Compiler ────────────")
    print(f"Reading configuration specification: {project_file.name}")

    config = load_audio_config(project_file)
    if args.notebook_id:
        config.notebook_id = args.notebook_id

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
