"""Automated RAG extraction and metadata binding for existing NotebookLM notebooks.

Eliminates manual `[INSERT ...]` slot filling by inspecting notebook metadata and executing
analytical RAG queries against existing document sources to harvest source-grounded terminology.
"""

import re
from typing import Any

from .models import AudioProjectConfig


async def auto_populate_from_notebook(
    client: Any,  # NotebookLMClient instance
    notebook_id: str,
    config: AudioProjectConfig,
    verbose: bool = True,
) -> AudioProjectConfig:
    """Query an existing NotebookLM notebook to dynamically fill title, scope, vocabulary, and debate topics."""
    if verbose:
        print(f"\n[Auto-Bind] Connecting to NotebookLM client for ID: {notebook_id}...")

    # 1. Fetch Notebook title and UUID binding
    notebook = await client.notebooks.get(notebook_id)
    config.notebook_id = notebook.id
    if config.title == "Unnamed Diagnostic Session" or not config.title:
        config.title = notebook.title
    if not config.topic or "Unnamed" in config.topic:
        config.topic = (
            f"core architectural trade-offs and runtime diagnostics in '{notebook.title}'"
        )

    # 2. Extract Scope from actual ingested sources
    sources = await client.sources.list(notebook_id)
    source_titles = [getattr(s, "title", "Untitled Source") for s in sources]
    if source_titles:
        short_titles = ", ".join(source_titles[:4])
        if len(source_titles) > 4:
            short_titles += f", and {len(source_titles) - 4} more"
        config.scope = f"{len(sources)} documents ingested ({short_titles})"
    else:
        config.scope = "0 sources found in notebook"

    if verbose:
        print(f"[Auto-Bind] ✔ Bound Title: '{config.title}'")
        print(f"[Auto-Bind] ✔ Bound Scope: '{config.scope}'")

    if not config.auto_extract or not sources:
        return config

    # 3. Perform automated Chat/RAG interrogation to harvest source-grounded diagnostic vocabulary
    if verbose:
        print(
            "[Auto-Bind] Executing analytical RAG query to extract source-grounded telemetry vocabulary and topics..."
        )

    extraction_prompt = (
        "Analyze all ingested documents and extract:\n"
        "1) Exactly ONE success or checkpoint confirmation mechanism.\n"
        "2) Exactly ONE data routing, synchronization, or structural mismatch problem.\n"
        "3) Exactly ONE bottleneck, resource exhaustion, or latency problem.\n"
        "4) Exactly ONE open-ended speculative design question or future consideration.\n"
        "5) List exactly THREE distinct core analytical topics or mechanisms suitable for debate.\n"
        "Please prefix your points clearly with numerals 1 to 5."
    )

    try:
        res = await client.chat.ask(notebook_id, extraction_prompt)
        answer = getattr(res, "answer", str(res))

        # Parse extracted telemetry terms if available in response
        lines = [line.strip() for line in answer.splitlines() if line.strip()]
        for line in lines:
            if line.startswith("1)") or line.startswith("1."):
                config.lexical_dictionary.agreement = f"[{line[2:].strip()}]"
            elif line.startswith("2)") or line.startswith("2."):
                config.lexical_dictionary.confusion = f"[{line[2:].strip()}]"
            elif line.startswith("3)") or line.startswith("3."):
                config.lexical_dictionary.frustration = f"[{line[2:].strip()}]"
            elif line.startswith("4)") or line.startswith("4."):
                config.lexical_dictionary.brainstorm = f"[{line[2:].strip()}]"

        # Look for bullet points or numbered lists after point 5 for topics
        extracted_topics = []
        capture_topics = False
        for line in lines:
            if (
                line.startswith("5)")
                or line.startswith("5.")
                or "topics suitable for debate" in line.lower()
            ):
                capture_topics = True
                continue
            if capture_topics:
                clean_line = re.sub(r"^[-*•0-9.)]+\s*", "", line).strip()
                if len(clean_line) > 15:
                    extracted_topics.append(clean_line)

        if len(extracted_topics) >= 2:
            config.topics = extracted_topics[:4]

        if verbose:
            print("[Auto-Bind] ✔ Harvested Lexical Telemetry Dictionary & Ideational Topics!")
    except Exception as e:
        if verbose:
            print(
                f"[Auto-Bind] Warning: RAG vocabulary extraction fell back to defaults due to error: {e}"
            )

    return config
