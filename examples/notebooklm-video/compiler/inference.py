"""Semantic and heuristic visual grammar inference from project corpus and domain attributes.

Enables automated selection of optimal Style Packs when a project specifies `style: auto-infer`.
"""

import re
from pathlib import Path

from .loaders import list_style_packs
from .models import DomainPack, ProjectConfig, StylePack

# Direct domain-to-style recommendation mapping table per architectural spec
DOMAIN_STYLE_AFFINITIES: dict[str, str] = {
    "software-architecture": "pixel-simulation",
    "distributed-systems": "pixel-simulation",
    "nutrition": "research-notebook",
    "radiology": "research-notebook",
    "medicine": "research-notebook",
    "history": "watercolor-atlas",
    "geopolitics": "watercolor-atlas",
    "machine-learning": "laboratory-notebook",
    "artificial-intelligence": "laboratory-notebook",
    "network-protocols": "metro-map",
    "telecommunications": "metro-map",
    "organizational-workflows": "illustrated-town",
    "enterprise": "illustrated-town",
    "economics": "strategy-game",
    "finance": "strategy-game",
    "strategy": "strategy-game",
}


def _extract_corpus_keywords(project: ProjectConfig, max_chars_per_doc: int = 4096) -> set[str]:
    """Extract semantic text signal from project titles, document filenames, and local file contents."""
    text_buffer = [project.title, project.domain]
    for doc_uri in project.documents:
        text_buffer.append(doc_uri)
        p = Path(doc_uri)
        # If document is a readable local text file, peek at its initial text
        if (
            p.exists()
            and p.is_file()
            and p.suffix.lower() in {".md", ".txt", ".py", ".yaml", ".json", ".csv"}
        ):
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")[:max_chars_per_doc]
                text_buffer.append(content)
            except Exception:
                pass

    combined_text = " ".join(text_buffer).lower()
    # Tokenize words (> 3 chars)
    tokens = set(re.findall(r"\b[a-z]{4,}\b", combined_text))
    return tokens


def infer_style_for_project(
    project: ProjectConfig,
    domain_pack: DomainPack | None = None,
    available_styles: list[StylePack] | None = None,
    prompts_root: Path | str | None = None,
) -> StylePack:
    """Infer the most suitable visual StylePack based on domain affinity and corpus semantic tags."""
    if available_styles is None:
        available_styles = list_style_packs(root=prompts_root)

    if not available_styles:
        raise RuntimeError("No Style Packs found in repository to infer from.")

    # 1. Check direct high-confidence affinity mapping table first
    domain_clean = project.domain.lower().replace("_", "-").strip()
    if domain_clean in DOMAIN_STYLE_AFFINITIES:
        target_name = DOMAIN_STYLE_AFFINITIES[domain_clean]
        for sp in available_styles:
            if sp.name.lower() == target_name:
                return sp

    # 2. Score based on semantic keyword matching against StylePack tags and descriptions
    corpus_tokens = _extract_corpus_keywords(project)
    if domain_pack and domain_pack.tags:
        for tag in domain_pack.tags:
            corpus_tokens.update(re.findall(r"\b[a-z]{4,}\b", tag.lower()))

    best_style = available_styles[0]
    highest_score = -1.0

    for style in available_styles:
        score = 0.0
        # Check matching tags
        for tag in style.tags:
            tag_words = set(re.findall(r"\b[a-z]{4,}\b", tag.lower()))
            if tag_words and tag_words.issubset(corpus_tokens):
                score += 3.0

        # Check description overlap
        if style.description:
            desc_words = set(re.findall(r"\b[a-z]{4,}\b", style.description.lower()))
            overlap = len(desc_words.intersection(corpus_tokens))
            score += overlap * 0.5

        if score > highest_score:
            highest_score = score
            best_style = style

    return best_style
