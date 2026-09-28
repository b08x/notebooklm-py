# Audio Overview Fact-Checking Plan

## Solution Approach
We will build on top of the existing `run_full_assessment` pipeline in `src/notebooklm/_app/assessment.py`. We will upgrade the `FactCheckAdapter` to support external web searches (with the ability to delegate to agentic coding harnesses), introduce a new SFL analysis pipeline for tracking speaker profiles and anomalies (similar to `sfl-engine`), and update the final output to generate a comprehensive Markdown report.

## Ordered Steps

1. **Ingestion & Transcription (Existing)**
   - **System:** `src/notebooklm/_app/assessment.py` & `TranscriptionAdapter`
   - **Action:** Utilize the existing audio transcription pipeline. We will ensure the diarization metadata is preserved and passed downstream to identify speaker turns (Host 1, Host 2).
   - **Verification:** Run a test transcription and verify that speaker labels are attached to the transcript text.

2. **SIFT Protocol & External Search via Agentic Harness**
   - **System:** `src/notebooklm/_preprocessing/fact_check.py`
   - **Action:** Enhance `FactCheckAdapter` and `FactCheckSignature` using DSPy. Rather than just raw API calls, this will be configurable to delegate the search task to a local Agentic Coding Harness (e.g., Antigravity, Claude Code, Hermes Agent, Open Code) using the Context7 or DeepWiki MCPs, leveraging their built-in web search tools and provider plans (though Exa/Jina API keys are available as a fallback).
   - **Verification:** Write a unit test verifying that the fact check can correctly route requests through the configured harness to verify a false claim.

3. **SFL Engine Implementation (Python Port)**
   - **System:** `src/notebooklm/_preprocessing/sfl_engine.py` (New File)
   - **Action:** Port the core logic of `sfl-engine` to Python using DSPy. We will implement a two-pass pipeline using pure LLM calls (via DSPy signatures) for both Pass 1 (syntactic/ideational) and Pass 2 (interpersonal) to avoid heavy dependencies like `spaCy`.
   - **Action:** Calculate speaker profiles, track tenor/modality shifts, and flag semantic anomalies. If diarization fails or is missing, the system will explicitly flag this failure in the UI/report and bypass the speaker profile analysis to avoid inaccurate results.
   - **Verification:** Feed a mock conversation with a clear register shift and verify that `semantic_anomaly` is flagged.

4. **Integration into Assessment Pipeline**
   - **System:** `src/notebooklm/_app/assessment.py`
   - **Action:** Update `run_full_assessment` to invoke the new SFL Engine on the transcription and aggregate the fact-checking results alongside the SFL metrics into `AssessmentResult`.
   - **Verification:** Run the full `Assess Audio Overview` flow end-to-end and check `AssessmentResult` properties.

5. **Markdown Report Generation**
   - **System:** `src/notebooklm/_app/assessment_formatter.py` (New File) and TUI Views
   - **Action:** Create a Markdown formatter that takes `AssessmentResult`, speaker profiles, anomalies, and fact-checking verdicts to generate the final report with data quality warnings.
   - **Verification:** Assert that the final Markdown string contains the "Data Quality" warning sections.

## Risks & Open Questions
- **Diarization Reliability:** If the chosen transcription provider fails to accurately separate the two speakers, the SFL speaker profiles will be inaccurate. **Mitigation:** We will detect missing diarization, explicitly disable speaker-dependent analysis, and display a clear warning.
- **Agentic Harness Configuration:** We need to ensure the configuration for selecting the desired Agentic Harness (and communicating with the Context7/DeepWiki MCPs) is smooth and robust.
- **Dependency Bloat (Resolved):** We will clarify that porting the syntactic parsing of SFL will NOT require `spaCy`. We will rely entirely on DSPy/LLM annotations for both parsing passes to keep dependencies light.
