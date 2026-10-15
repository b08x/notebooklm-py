import json
import os

from notebooklm._app.ass_export import (
    align_chunk_timestamps,
    extract_normalized_words,
    format_ass_timestamp,
    generate_ass_script,
    sanitize_ass_text,
    save_assessment_ass,
)
from notebooklm._app.assessment import AssessmentChunk, AssessmentResult
from notebooklm._app.assessment_formatter import generate_ass_report


def test_format_ass_timestamp():
    assert format_ass_timestamp(0.0) == "0:00:00.00"
    assert format_ass_timestamp(1.23) == "0:00:01.23"
    assert format_ass_timestamp(65.456) == "0:01:05.46"
    assert format_ass_timestamp(3665.12) == "1:01:05.12"
    assert format_ass_timestamp(-5.0) == "0:00:00.00"


def test_sanitize_ass_text():
    raw = "Hello {World}\nThis is a\r\ntest of ASS text."
    cleaned = sanitize_ass_text(raw)
    assert "｛World｝" in cleaned
    assert "{" not in cleaned
    assert "}" not in cleaned
    assert r"\N" in cleaned


def test_extract_normalized_words_deepgram():
    deepgram_data = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "words": [
                                {
                                    "word": "hello",
                                    "punctuated_word": "Hello,",
                                    "start": 1.2,
                                    "end": 1.5,
                                    "speaker": 0,
                                },
                                {
                                    "word": "world",
                                    "punctuated_word": "world!",
                                    "start": 1.6,
                                    "end": 2.1,
                                    "speaker": 1,
                                },
                            ]
                        }
                    ]
                }
            ]
        }
    }
    words = extract_normalized_words(deepgram_data)
    assert len(words) == 2
    assert words[0].word == "Hello,"
    assert words[0].clean == "hello"
    assert words[0].start == 1.2
    assert words[0].speaker == "Speaker 0"
    assert words[1].speaker == "Speaker 1"


def test_extract_normalized_words_assemblyai():
    assembly_data = [
        {
            "speaker": "A",
            "start": 1000,
            "end": 3000,
            "text": "Hello world",
            "words": [
                {"word": "Hello", "text": "Hello", "start": 1000, "end": 1500, "speaker": "A"},
                {"word": "world", "text": "world", "start": 1600, "end": 2800, "speaker": "A"},
            ],
        }
    ]
    words = extract_normalized_words(assembly_data)
    assert len(words) == 2
    assert words[0].start == 1.0
    assert words[0].end == 1.5
    assert words[0].speaker == "Speaker A"


def test_extract_normalized_words_speechmatics():
    sm_data = {
        "results": [
            {
                "type": "word",
                "start_time": 2.0,
                "end_time": 2.5,
                "alternatives": [{"content": "Testing", "speaker": "S2"}],
            }
        ]
    }
    words = extract_normalized_words(sm_data)
    assert len(words) == 1
    assert words[0].word == "Testing"
    assert words[0].start == 2.0
    assert words[0].speaker == "Speaker 2"


def test_align_chunk_timestamps_with_explicit_chunk_times():
    chunk = AssessmentChunk(
        text="Explicit timing",
        clause_external_id="chunk-1",
        start_time=10.5,
        end_time=15.2,
        speaker="Speaker 1",
    )
    timings = align_chunk_timestamps([chunk])
    assert len(timings) == 1
    assert timings[0] == (10.5, 15.2, "Speaker 1")


def test_align_chunk_timestamps_fallback_sequential():
    chunks = [
        AssessmentChunk(text="First chunk of dialogue here.", clause_external_id="c1"),
        AssessmentChunk(text="Second chunk continues the discussion.", clause_external_id="c2"),
    ]
    timings = align_chunk_timestamps(chunks)
    assert len(timings) == 2
    s1, e1, spk1 = timings[0]
    s2, e2, spk2 = timings[1]
    assert s1 >= 0.0
    assert e1 > s1
    assert s2 >= e1
    assert e2 > s2


def test_generate_ass_script_complete():
    chunk1 = AssessmentChunk(
        text="The stochastic routing is just brutal today, mister language model.",
        clause_external_id="art-1:0",
        topic_id=1,
        entities=[("language model", "ORG")],
        fact_check_passed=True,
        fact_check_citations="Bypassed: Classified as subjective/meta-dialogue with no verifiable factual claims.",
        speaker="Speaker 1",
        start_time=4.12,
        end_time=9.50,
        sfl={
            "ideational": {
                "participants": ["Speaker", "The stochastic routing"],
                "processes": ["is"],
                "circumstances": ["just"],
            },
            "interpersonal": {
                "tenor": "informal, conversational",
                "mood": "declarative",
                "modality": "high",
            },
        },
    )

    chunk2 = AssessmentChunk(
        text="Python 3.14 was released in 2026 by Jane Doe.",
        clause_external_id="art-1:1",
        topic_id=2,
        entities=[("Jane Doe", "PERSON"), ("2026", "DATE")],
        fact_check_passed=False,
        fact_check_citations="Contradiction: Source document states Python release year was 2025.",
        speaker="Speaker 2",
        start_time=10.0,
        end_time=14.5,
    )

    chunk3 = AssessmentChunk(
        text="Quantum computers utilize qubits.",
        clause_external_id="art-1:2",
        topic_id=3,
        entities=[],
        fact_check_passed=True,
        fact_check_citations="Verified against physics reference corpus.",
        speaker="Speaker 0",
        start_time=15.0,
        end_time=18.0,
    )

    result = AssessmentResult(
        system_instructions="Evaluate factual accuracy and tone.",
        audio_metadata=json.dumps({"provider": "deepgram"}),
        transcript="Full audio transcript...",
        chunks=[chunk1, chunk2, chunk3],
        sfl_metrics={"total_clauses": 3},
    )

    script = generate_ass_script(result, title="AI Psychosis Assessment")

    # Assert Script Info
    assert "[Script Info]" in script
    assert "Title: AI Psychosis Assessment" in script
    assert "PlayResX: 1920" in script
    assert "PlayResY: 1080" in script

    # Assert V4+ Styles
    assert "[V4+ Styles]" in script
    assert "Style: Dialogue_Speaker1" in script
    assert "Style: Dialogue_Speaker2" in script
    assert "Style: FactCheck_Pass" in script
    assert "Style: FactCheck_Fail" in script
    assert "Style: FactCheck_Bypass" in script
    assert "Style: FactCheck_Unverified" in script
    assert "Style: Annotation_SFL" in script
    assert "Style: Assessment_Header" in script

    # Assert Events
    assert "[Events]" in script

    # Check Layer 0 Dialogue
    assert "Dialogue: 0,0:00:04.12,0:00:09.50,Dialogue_Speaker1,Speaker 1" in script
    assert "[Speaker 1]" in script
    assert "The stochastic routing" in script

    # Check Entity styling
    assert "Jane Doe" in script

    # Check Layer 1 FactCheck HUD
    # Chunk 1 is bypassed
    assert "FactCheck_Bypass,FactCheck" in script
    assert "FACT-CHECK: BYPASSED (SUBJECTIVE)" in script
    # Chunk 2 is contradiction / fail
    assert "FactCheck_Fail,FactCheck" in script
    assert "FACT-CHECK: CONTRADICTION" in script
    assert "Source document states Python" in script
    # Chunk 3 is verified / pass
    assert "FactCheck_Pass,FactCheck" in script
    assert "FACT-CHECK: VERIFIED" in script

    # Check Layer 2 SFL HUD
    assert "Annotation_SFL,SFL" in script
    assert "SFL METAFUNCTIONS" in script
    assert "The stochastic routing" in script
    assert "informal, conversational" in script

    # Check Title card
    assert "Assessment_Header,AssessmentInfo" in script
    assert "NotebookLM Audio Assessment" in script


def test_generate_ass_report_wrapper():
    chunk = AssessmentChunk(text="Sample dialogue.", clause_external_id="c1")
    res = AssessmentResult(system_instructions="", audio_metadata="", transcript="", chunks=[chunk])
    script = generate_ass_report(res, title="Wrapper Test")
    assert "[Script Info]" in script
    assert "Title: Wrapper Test" in script
    assert "Sample dialogue." in script


def test_save_assessment_ass(tmp_path):
    chunk = AssessmentChunk(text="File save test.", clause_external_id="c-save")
    res = AssessmentResult(system_instructions="", audio_metadata="", transcript="", chunks=[chunk])
    out_file = str(tmp_path / "subdir" / "test_output.ass")
    saved_path = save_assessment_ass(res, out_file, title="Saved Assessment")
    assert os.path.exists(saved_path)
    with open(saved_path, encoding="utf-8") as f:
        content = f.read()
    assert "[Script Info]" in content
    assert "File save test." in content
