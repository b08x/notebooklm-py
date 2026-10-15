"""Automated Chat-based RAG extraction and metadata binding for NotebookLM notebooks.

Eliminates static YAML configurations by dynamically querying NotebookLM's chat API
to harvest source-grounded topics and lexical binding phrases directly from notebook sources.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .models import AudioProjectConfig, LexicalState, Topic1, Topic2, Topic3

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Analyze all ingested documents in this notebook and extract technical details for a structured dual-host dialogue.
Return your response as a valid JSON object with the following exact keys:
{
  "topic_1": {
    "title": "short descriptive title for topic 1",
    "theoretical_framework": "the high-level theoretical framework or concept",
    "low_level_mechanism": "the low-level technical mechanism",
    "failure_mode": "how it fails or breaks",
    "pathological_effect": "the resulting pathological symptom or consequence",
    "operational_analogy": "a vivid operational or mechanical analogy"
  },
  "topic_2": {
    "title": "short descriptive title for topic 2",
    "industry_practice_or_wrapper": "common industry practice or surface wrapper",
    "technical_reality": "the actual underlying technical reality",
    "benchmark_or_failure_metric": "key failure metric or benchmark",
    "obscured_data_point": "a hidden or obscured data point or trade-off",
    "economic_or_regulatory_incentive": "the economic or organizational incentive"
  },
  "topic_3": {
    "title": "short descriptive title for topic 3",
    "recursive_or_feedback_loop": "a feedback loop or recursive behavior",
    "behavioral_metric": "behavioral metric that is observed",
    "superficial_attribution": "the superficial explanation people give",
    "degradation_mechanism": "the actual degradation mechanism",
    "system_components": "the interacting system components involved"
  },
  "lexical": {
    "convergence": {
      "tag": "short tag e.g. Convergence or Sync",
      "phrase_a": "short conversational phrase for speaker A",
      "phrase_b": "short conversational phrase for speaker B"
    },
    "desync": {
      "tag": "short tag e.g. Desync or Routing Error",
      "phrase_a": "short conversational phrase for speaker A",
      "phrase_b": "short conversational phrase for speaker B"
    },
    "exhaustion": {
      "tag": "short tag e.g. Exhaustion or Bottleneck",
      "phrase_a": "short conversational phrase for speaker A",
      "phrase_b": "short conversational phrase for speaker B"
    },
    "high_entropy": {
      "tag": "short tag e.g. High Entropy or Tangent",
      "phrase_a": "short conversational phrase for speaker A",
      "phrase_b": "short conversational phrase for speaker B"
    }
  }
}
Output ONLY the JSON object, with no markdown code fences or conversational filler.
"""


def _extract_json_block(text: str) -> dict[str, Any] | None:
    """Attempt to parse text or extract a fenced/unfenced JSON block from text."""
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return None


async def auto_populate_from_notebook(
    client: Any,
    notebook_id: str,
    config: AudioProjectConfig | None = None,
    verbose: bool = True,
) -> AudioProjectConfig:
    """Query an existing NotebookLM notebook to dynamically fill title, scope, vocabulary, and topics."""
    if config is None:
        config = AudioProjectConfig(notebook_id=notebook_id)

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

    # 3. Perform automated Chat/RAG interrogation to harvest source-grounded topics and phrases
    if verbose:
        print(
            "[Auto-Bind] Executing Chat RAG query to harvest 3 topics and 4 state phrase pairs..."
        )

    try:
        res = await client.chat.ask(notebook_id, _EXTRACTION_PROMPT)
        answer = getattr(res, "answer", str(res))
        parsed = _extract_json_block(answer)

        if parsed:
            # Map Topic 1
            t1_data = parsed.get("topic_1")
            if isinstance(t1_data, dict):
                config.topic_1 = Topic1(
                    title=str(t1_data.get("title") or config.topic_1.title),
                    theoretical_framework=str(
                        t1_data.get("theoretical_framework") or config.topic_1.theoretical_framework
                    ),
                    low_level_mechanism=str(
                        t1_data.get("low_level_mechanism") or config.topic_1.low_level_mechanism
                    ),
                    failure_mode=str(t1_data.get("failure_mode") or config.topic_1.failure_mode),
                    pathological_effect=str(
                        t1_data.get("pathological_effect") or config.topic_1.pathological_effect
                    ),
                    operational_analogy=str(
                        t1_data.get("operational_analogy") or config.topic_1.operational_analogy
                    ),
                )

            # Map Topic 2
            t2_data = parsed.get("topic_2")
            if isinstance(t2_data, dict):
                config.topic_2 = Topic2(
                    title=str(t2_data.get("title") or config.topic_2.title),
                    industry_practice_or_wrapper=str(
                        t2_data.get("industry_practice_or_wrapper")
                        or config.topic_2.industry_practice_or_wrapper
                    ),
                    technical_reality=str(
                        t2_data.get("technical_reality") or config.topic_2.technical_reality
                    ),
                    benchmark_or_failure_metric=str(
                        t2_data.get("benchmark_or_failure_metric")
                        or config.topic_2.benchmark_or_failure_metric
                    ),
                    obscured_data_point=str(
                        t2_data.get("obscured_data_point") or config.topic_2.obscured_data_point
                    ),
                    economic_or_regulatory_incentive=str(
                        t2_data.get("economic_or_regulatory_incentive")
                        or config.topic_2.economic_or_regulatory_incentive
                    ),
                )

            # Map Topic 3
            t3_data = parsed.get("topic_3")
            if isinstance(t3_data, dict):
                config.topic_3 = Topic3(
                    title=str(t3_data.get("title") or config.topic_3.title),
                    recursive_or_feedback_loop=str(
                        t3_data.get("recursive_or_feedback_loop")
                        or config.topic_3.recursive_or_feedback_loop
                    ),
                    behavioral_metric=str(
                        t3_data.get("behavioral_metric") or config.topic_3.behavioral_metric
                    ),
                    superficial_attribution=str(
                        t3_data.get("superficial_attribution")
                        or config.topic_3.superficial_attribution
                    ),
                    degradation_mechanism=str(
                        t3_data.get("degradation_mechanism") or config.topic_3.degradation_mechanism
                    ),
                    system_components=str(
                        t3_data.get("system_components") or config.topic_3.system_components
                    ),
                )

            # Map Lexical Bindings
            lex_data = parsed.get("lexical")
            if isinstance(lex_data, dict):
                for state_key, target_attr in (
                    ("convergence", "convergence"),
                    ("desync", "desync"),
                    ("exhaustion", "exhaustion"),
                    ("high_entropy", "high_entropy"),
                ):
                    sub = lex_data.get(state_key)
                    if isinstance(sub, dict):
                        curr = getattr(config.lexical_bindings, target_attr)
                        setattr(
                            config.lexical_bindings,
                            target_attr,
                            LexicalState(
                                tag=str(sub.get("tag") or curr.tag),
                                phrase_a=str(sub.get("phrase_a") or curr.phrase_a),
                                phrase_b=str(sub.get("phrase_b") or curr.phrase_b),
                            ),
                        )

            config.topics = [config.topic_1.title, config.topic_2.title, config.topic_3.title]
            if verbose:
                print(
                    "[Auto-Bind] ✔ Successfully extracted topics and state phrases from Chat RAG."
                )
        else:
            if verbose:
                print(
                    "[Auto-Bind] ⚠ Could not parse structured JSON from Chat response; using robust defaults."
                )
    except Exception as e:
        logger.warning("Chat RAG extraction failed: %s; using robust defaults.", e)
        if verbose:
            print(f"[Auto-Bind] ⚠ Chat extraction failed ({e}); using robust defaults.")

    return config
