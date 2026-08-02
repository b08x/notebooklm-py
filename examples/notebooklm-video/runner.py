"""Async orchestration runner for NotebookLM video generation.

Decouples declarative synchronous compilation from async I/O network transport.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

# Make local compiler available without installation when running directly
sys.path.insert(0, str(Path(__file__).resolve().parent))
# Ensure parent repository notebooklm library is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from compiler.prompt import compile_from_yaml

from notebooklm import NotebookLMClient, VideoFormat, VideoStyle

DEFAULT_PROJECT = Path(__file__).parent / "projects" / "ai-agents.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile and execute a modular NotebookLM Video Overview production."
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=str(DEFAULT_PROJECT),
        help="Path to declarative project YAML configuration.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually invoke notebooklm-py to create notebook and generate video (default is dry-run compilation preview).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="generated_video_overview.mp4",
        help="Output filepath for downloaded MP4 when executing live generation.",
    )
    return parser.parse_args()


async def execute_video_pipeline(compiled: Any, output_path: str) -> None:
    """Async I/O execution backend using notebooklm-py."""
    print("Initializing async NotebookLM client from local storage...")
    async with NotebookLMClient.from_storage() as client:
        print(f"\n[1/5] Creating notebook: '{compiled.project_title}'...")
        notebook = await client.notebooks.create(compiled.project_title)
        print(f"      Notebook initialized with ID: {notebook.id}")

        print(f"\n[2/5] Uploading and ingesting {len(compiled.documents)} document sources...")
        for doc in compiled.documents:
            if doc.startswith("http://") or doc.startswith("https://"):
                print(f"      Ingesting remote web URL: {doc}")
                await client.sources.add_url(notebook.id, doc)
            else:
                p = Path(doc).resolve()
                if p.exists():
                    print(f"      Uploading local file source: {p.name}")
                    await client.sources.add_file(notebook.id, str(p))
                else:
                    print(f"      [Warning] Source path not found, skipping: {doc}")

        # Give backend indexing brief buffer
        await asyncio.sleep(4.0)

        print("\n[3/5] Dispatching compiled prompts to Video Studio...")
        format_enum = getattr(VideoFormat, compiled.video_format.upper(), VideoFormat.EXPLAINER)

        # Handle API constraint: cinematic and short formats do not accept style_prompt parameter.
        # Instead, dynamically embed our compiled visual grammar directly into general instructions.
        if format_enum in (VideoFormat.CINEMATIC, VideoFormat.SHORT):
            print(
                f"      Format '{format_enum.name}' selected (style_prompt merged into instructions)."
            )
            combined_instructions = (
                f"{compiled.style_prompt}\n\n=== CONTENT INSTRUCTIONS ===\n{compiled.instructions}"
            )
            generation = await client.artifacts.generate_video(
                notebook.id,
                video_format=format_enum,
                video_style=VideoStyle.AUTO_SELECT,
                language="en",
                instructions=combined_instructions,
            )
        else:
            generation = await client.artifacts.generate_video(
                notebook.id,
                video_format=format_enum,
                video_style=VideoStyle.CUSTOM,
                style_prompt=compiled.style_prompt,
                language="en",
                instructions=compiled.instructions,
            )

        print(f"      Task submitted successfully! Task ID: {generation.task_id}")
        print("\n[4/5] Polling status while NotebookLM renders video (typically 3-8 minutes)...")

        final_status = await client.artifacts.wait_for_completion(
            notebook.id,
            generation.task_id,
            initial_interval=10.0,
            max_interval=30.0,
            timeout=1200.0,
        )

        if final_status.is_complete:
            print(f"\n[5/5] Rendering complete! Downloading artifact to: {output_path}")
            await client.artifacts.download_video(
                notebook.id,
                output_path=output_path,
                artifact_id=final_status.artifact_id,
            )
            print("      Download successful! Production complete.")
        else:
            print(f"      [Error] Video generation failed or timed out: {final_status}")


def main() -> None:
    args = parse_args()

    project_file = Path(args.project).resolve()
    print("─── NotebookLM Video Prompt Compiler ──────────────────────")
    print(f"Reading project specification: {project_file.name}")

    # Synchronous compilation step (in-memory, CPU bound)
    compiled = compile_from_yaml(project_file)

    print(f"\n✔ Synchronously compiled project: [{compiled.project_title}]")
    print(f"  ├── Style Pack:  {compiled.style_name}")
    print(f"  ├── Domain Pack: {compiled.domain_name}")
    print(f"  ├── Voice Pack:  {compiled.voice_name}")
    print(f"  └── Target:      {compiled.video_format} ({compiled.length} for {compiled.audience})")

    print("\n─── COMPILATION OUTPUT PREVIEW (DRY RUN) ──────────────────")
    print("\n[STYLE PROMPT (VideoStyle.CUSTOM / Visual Grammar)]")
    print(compiled.style_prompt)
    print("\n[CONTENT INSTRUCTIONS (Narrative & Pedagogical Rules)]")
    print(compiled.instructions)
    print("───────────────────────────────────────────────────────────")

    if not args.execute:
        print("\n[Note] Dry-run preview complete. No network calls or notebook creations occurred.")
        print("To run live execution via notebooklm-py, add the `--execute` flag:")
        print(f"  uv run examples/notebooklm-video/runner.py {project_file} --execute\n")
    else:
        # Asynchronous execution pipeline (I/O bound)
        asyncio.run(execute_video_pipeline(compiled, args.out))


if __name__ == "__main__":
    main()
