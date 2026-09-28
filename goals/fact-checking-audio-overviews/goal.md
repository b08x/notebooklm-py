# Goal: Fact-Checking Audio Overviews

Build a fact-checking component for NotebookLM that evaluates the accuracy of generated audio overviews. This component will use DSPy to apply a SIFT protocol analysis (leveraging an agentic harness for external web search) and perform a narrative analysis using a pure-LLM systemic functional linguistic (SFL) tagging pipeline to categorize semiotics, pragmatic intention, and speaker shifts. Finally, it will correlate these findings into a detailed Markdown report to trace exactly where identified factual errors originated.

- **Shared Understanding:** [Facts](facts.md)
- **Execution Plan:** [Plan](plan.md)

## Done Condition

This goal is complete when `run_full_assessment` successfully delegates external web searches through the configured agentic harness to verify claims, performs the two-pass SFL analysis on the transcribed audio (including handling diarization fallbacks), and generates a detailed Markdown report containing inline citations and data quality warnings as outlined in the facts and plan.
