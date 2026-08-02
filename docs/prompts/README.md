# NotebookLM Prompt Library & Modular Grammar Packs

This directory contains reusable prompt templates and visual grammar configurations for generating NotebookLM artifacts, including **Video Overviews**, **Audio Overviews**, and custom structured summaries.

## The Modular Architecture (4-Layer Pipeline)

Traditionally, prompt engineering in NotebookLM coupled visual instructions, domain concept mappings, narrative voice, and topic constraints into monolithic text blobs (see legacy examples in this directory such as `notebooklm_watercolor_map_template.md`).

To maximize reuse and programmatic assembly, the visual prompt pipeline has been decoupled into **four orthogonal layers**, located under [`video/`](file:///home/b08x/WorkspaceV3/notebooklm-py/docs/prompts/video):

1. **Style Packs (`video/styles/*.yaml`)**: Define pure visual language without any domain topic. Specify camera projection, color palettes, physical drawing mediums, animation transitions, and visual grammar constraints.
   - `watercolor-atlas.yaml`
   - `pixel-simulation.yaml`
   - `research-notebook.yaml`
   - `illustrated-town.yaml`
   - `metro-map.yaml`
   - `strategy-game.yaml`
   - `laboratory-notebook.yaml`

2. **Domain Packs (`video/domains/*.yaml`)**: Define concept-to-metaphor mappings and domain pedagogical rules (e.g., mapping an API to a secure gateway or proteins to cellular warehouse processing depots).
   - `software-architecture.yaml`
   - `nutrition.yaml`
   - `radiology.yaml`
   - `history.yaml`
   - `machine-learning.yaml`

3. **Voice Packs (`video/voices/*.yaml`)**: Define target narrative tone, pacing, structural breakdown, and vocabulary guidelines.
   - `documentary.yaml`
   - `technical-explainer.yaml`
   - `socratic.yaml`

4. **Project Definitions**: Declarative YAML configurations that compose a Style, Domain, Voice, target audience, duration, and list of source documents into a single NotebookLM production.

## Audio Synthesis Prompts (`audio/`)

For generating specialized **Audio Overviews** (podcasts and dialog synthesis), structured persona and lexical binding templates are located in [`audio/`](file:///home/b08x/WorkspaceV3/notebooklm-py/docs/prompts/audio):

- [`mr_and_mrs_language_model.md`](file:///home/b08x/WorkspaceV3/notebooklm-py/docs/prompts/audio/mr_and_mrs_language_model.md): Topic-agnostic dual-host diagnostic audio prompt template featuring chaotic-neutral persona archetypes, telemetry substitution dictionaries, and strict turn-taking rules.

## Orchestration & Compilation

To compile these declarative YAML packs into validated NotebookLM prompts and execute generation via `notebooklm-py`, see the reference compiler and orchestrator implementation located in [`../../examples/notebooklm-video/`](file:///home/b08x/WorkspaceV3/notebooklm-py/examples/notebooklm-video).

### Example Project YAML
```yaml
title: "Autonomous Agent Architectures"
style: "pixel-simulation"      # or "auto-infer" for semantic selection
domain: "software-architecture"
voice: "technical-explainer"
audience: "Senior Distributed Systems Engineers"
length: "10 minutes"
documents:
  - "https://en.wikipedia.org/wiki/Multi-agent_system"
```
