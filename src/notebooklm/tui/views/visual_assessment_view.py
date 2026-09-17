import asyncio
import base64
import concurrent.futures
import json
import logging
import os
from pathlib import Path

from rich.align import Align
from rich.panel import Panel

from notebooklm.tui.state import TUIState, View

logger = logging.getLogger(__name__)

_vlm_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

SYSTEM_PROMPT = """
You are a strict Graph Engineering ontology classifier.
Analyze the provided image in the context of a Prompt Library containing AI frameworks, character personas, and technical workflows.

Classify the image into EXACTLY ONE of the following ontology types:
- "Architecture Diagram" (Technical charts, flowcharts, graphs, or system diagrams)
- "Persona Avatar" (A portrait, illustration, or representation of an AI character or persona)
- "UI Screenshot" (A screenshot of a software interface, web app, or terminal)
- "Irrelevant" (Random photos, selfies, memes, or anything that lacks structural value in a technical library)

Output your response as a strict JSON object with no markdown formatting or backticks, containing exactly these keys:
{
  "ontology_type": "The classification string",
  "description": "A brief, one-sentence description of the image content"
}
"""

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def _run_vlm_assessment(state: TUIState, notebook_id: str):
    import httpx
    from sqlalchemy import select

    from notebooklm.db.models import LocalAsset
    from notebooklm.db.session import async_session_maker

    # OpenRouter API key and model setup
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    model_name = "google/gemma-4-26b-a4b-it"

    if not api_key:
        return {"error": "OPENROUTER_API_KEY environment variable is not set."}

    async def _process_images():
        results = []
        async with async_session_maker() as session:
            res = await session.execute(
                select(LocalAsset).where(
                    LocalAsset.notebook_id == notebook_id,
                    LocalAsset.asset_type == "artifact"
                )
            )
            assets = res.scalars().all()

            image_assets = [a for a in assets if str(a.local_path).lower().endswith(('.png', '.jpg', '.jpeg'))]

            if not image_assets:
                return {"error": "No local image artifacts found. Download them first!"}

            for idx, asset in enumerate(image_assets):
                path = Path(asset.local_path)
                meta_path = path.with_suffix(path.suffix + ".meta.yaml")

                if meta_path.exists():
                    results.append({"file": path.name, "status": "skipped (already assessed)"})
                    continue

                if not path.exists():
                    results.append({"file": path.name, "status": "file missing"})
                    continue

                base64_image = encode_image(str(path))

                # PaliGemma / Gemma best practices: single-turn, objective, image before text
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/{path.suffix[1:]};base64,{base64_image}"
                                }
                            },
                            {
                                "type": "text",
                                "text": SYSTEM_PROMPT
                            }
                        ]
                    }
                ]

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/b08x/notebooklm-py",
                    "X-Title": "NotebookLM-Py VLM Assessment"
                }

                payload = {
                    "model": model_name,
                    "messages": messages,
                    "temperature": 0.1
                }

                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60.0)
                        resp.raise_for_status()
                        data = resp.json()

                        raw_text = data['choices'][0]['message']['content'].strip()
                        if raw_text.startswith('```json'):
                            raw_text = raw_text[7:-3].strip()
                        elif raw_text.startswith('```'):
                            raw_text = raw_text[3:-3].strip()

                        parsed = json.loads(raw_text)

                        ontology_type = parsed.get("ontology_type", "Unknown")
                        description = parsed.get("description", "No description provided.")

                        yaml_content = f'---\nontology_type: "{ontology_type}"\ndescription: "{description}"\n---\n'

                        with open(meta_path, 'w', encoding='utf-8') as f:
                            f.write(yaml_content)

                        results.append({"file": path.name, "status": f"assessed ({ontology_type})"})
                except Exception as e:
                    results.append({"file": path.name, "status": f"error: {e}"})

                # Rate limit (conscious pacing for OpenRouter)
                await asyncio.sleep(1.0)

        return {"results": results}

    return asyncio.run(_process_images())


def start_assess_visual_artifacts(state: TUIState) -> None:
    if not state.selected_notebook:
        return

    state.error_message = f"Assessing visual artifacts for {state.selected_notebook}..."
    state.assessment_state = {
        "is_loading": True,
        "loading_message": "Scanning and classifying image artifacts via OpenRouter...",
        "results": []
    }

    if state.current_view != View.VISUAL_ASSESSMENT:
        state.previous_view = state.current_view
        state.current_view = View.VISUAL_ASSESSMENT

    def on_done(future):
        try:
            res = future.result()
            if "error" in res:
                state.error_message = f"Visual assessment failed: {res['error']}"
                state.assessment_state["is_loading"] = False
                state.assessment_state["error"] = res["error"]
            else:
                state.error_message = "Visual assessment complete."
                state.assessment_state["is_loading"] = False
                state.assessment_state["results"] = res["results"]
        except Exception as e:
            logger.exception("VLM assessment crashed")
            state.error_message = f"Visual assessment crashed: {e}"
            state.assessment_state["is_loading"] = False
            state.assessment_state["error"] = str(e)

    state.background_task = _vlm_executor.submit(_run_vlm_assessment, state, state.selected_notebook)
    state.background_task.add_done_callback(on_done)


class VisualAssessmentView:
    def __init__(self, state: TUIState):
        self.state = state

    def render(self) -> tuple[Panel, Panel]:
        assessment_state = getattr(self.state, "assessment_state", {})

        if assessment_state.get("is_loading"):
            loading_message = assessment_state.get("loading_message", "Loading...")
            loading_panel = Panel(
                Align.center(f"\n\n{loading_message}\n\nThis may take a minute...", vertical="middle"),
                title="VLM Assessment in Progress",
                border_style="border",
                style="main",
            )
            return loading_panel, Panel("", border_style="border")

        error = assessment_state.get("error")
        if error:
            error_panel = Panel(
                Align.center(f"\n\n[red]{error}[/red]\n\nPress Esc to return.", vertical="middle"),
                title="VLM Assessment Failed",
                border_style="border",
                style="main",
            )
            return error_panel, Panel("", border_style="border")

        results = assessment_state.get("results", [])

        left_text = "Visual Artifact Assessment:\n\n"
        left_text += f"Processed {len(results)} image(s).\n\n"
        left_text += "A `.meta.yaml` sidecar file was generated for each successfully classified image.\n"
        left_panel = Panel(left_text, title="VLM Assessment Summary")

        right_lines = []
        for r in results:
            if "error" in r["status"] or "skipped" in r["status"]:
                color = "yellow" if "skipped" in r["status"] else "red"
                right_lines.append(f"• {r['file']}: [{color}]{r['status']}[/]")
            else:
                right_lines.append(f"• {r['file']}: [green]{r['status']}[/]")

        right_panel = Panel(
            "\n".join(right_lines) if right_lines else "No image artifacts processed.",
            title="Image Classifications",
            border_style="border",
        )

        return left_panel, right_panel
