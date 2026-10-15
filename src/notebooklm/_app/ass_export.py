"""Advanced SubStation Alpha (.ass) subtitle export for audio assessments.

Exports audio assessments into a rich, broadcast-quality .ass subtitle file
containing:
1. Synchronized speaker dialogue at bottom-center with distinct speaker styles
   and inline entity highlights.
2. Real-time Fact-Check HUD at top-right with color-coded status badges
   (Verified, Contradiction, Bypassed/Subjective, Unverified), citations, and
   clause references.
3. Real-time SFL (Systemic Functional Linguistics) linguistic analysis HUD at
   top-left displaying Ideational (Participants, Processes, Circumstances) and
   Interpersonal (Tenor, Mood, Modality) metafunctions.
4. Assessment title card and summary HUD.

This module is transport-neutral — no ``click`` / ``rich`` / ``tui`` imports.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .sfl_format import format_sfl

if TYPE_CHECKING:
    from .assessment import AssessmentChunk, AssessmentResult

# ---------------------------------------------------------------------------
# ASS Color Palette (ASS uses hexadecimal &HAABBGGRR& where AA=alpha, BB=blue, GG=green, RR=red)
# ---------------------------------------------------------------------------

ASS_WHITE = "&H00FFFFFF&"
ASS_OFFWHITE = "&H00F5F5F5&"
ASS_DARK_SHADOW = "&H00100E14&"
ASS_BOX_BG = "&HA0141014&"  # ~62% opaque dark box
ASS_HEADER_BG = "&H80000000&"

# Speaker accents (Dialogue)
ASS_SPEAKER_0 = "&H00F0F0F0&"  # Clean white/silver
ASS_SPEAKER_1 = "&H00E6C844&"  # Vibrant teal/cyan (R:44, G:C8, B:E6)
ASS_SPEAKER_2 = "&H00E0A0FF&"  # Lavender/purple (R:FF, G:A0, B:E0)
ASS_SPEAKER_3 = "&H0080B8FF&"  # Soft peach/gold (R:FF, G:B8, B:80)

# Fact-Check status colors
ASS_FC_PASS = "&H0070FA50&"  # Emerald Green (R:50, G:FA, B:70)
ASS_FC_FAIL = "&H005A5AFF&"  # Coral Red (R:FF, G:5A, B:5A)
ASS_FC_BYPASS = "&H00F0D860&"  # Sky Blue / Cyan (R:60, G:D8, B:F0)
ASS_FC_UNVERIFIED = "&H0032C8FF&"  # Amber Gold (R:FF, G:C8, B:32)

# SFL & Annotation accents
ASS_SFL_LABEL = "&H00AAAAAA&"
ASS_SFL_TITLE = "&H0080B8FF&"
ASS_SFL_TENOR = "&H0070FA50&"
ASS_SFL_MOOD = "&H00F0D860&"
ASS_SFL_MODALITY = "&H00E0A0FF&"
ASS_MUTED = "&H00888888&"

# Entity highlighting colors
ENTITY_ASS_COLORS: dict[str, str] = {
    "PERSON": "&H0080B8FF&",  # Peach/Gold
    "ORG": "&H00F0D860&",  # Cyan
    "DATE": "&H0080E8FF&",  # Yellow/Gold
    "TIME": "&H0080E8FF&",  # Yellow
    "GPE": "&H00F0A0D0&",  # Lilac/Pink
    "LOC": "&H00F0A0D0&",  # Lilac/Pink
    "MONEY": "&H0070FA50&",  # Green
    "NORP": "&H00F0A0D0&",  # Lilac/Pink
}


# ---------------------------------------------------------------------------
# Formatting & Sanitization Helpers
# ---------------------------------------------------------------------------


def format_ass_timestamp(seconds: float) -> str:
    """Format seconds into ASS timestamp: H:MM:SS.cs (e.g. 0:01:23.45)."""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    cs = int(round((secs - int(secs)) * 100))
    int_secs = int(secs)
    if cs >= 100:
        cs = 0
        int_secs += 1
        if int_secs >= 60:
            int_secs = 0
            minutes += 1
            if minutes >= 60:
                minutes = 0
                hours += 1
    return f"{hours}:{minutes:02d}:{int_secs:02d}.{cs:02d}"


def sanitize_ass_text(text: str) -> str:
    """Sanitize text for ASS subtitle events to avoid breaking ASS tag syntax."""
    if not text:
        return ""
    # Standardize line endings and convert newlines to ASS linebreaks (\N)
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    # Replace curly braces with full-width unicode braces to preserve user content
    # without corrupting ASS style override blocks
    cleaned = cleaned.replace("{", "｛").replace("}", "｝")
    # Convert consecutive newlines to single \N and single newlines to \N
    cleaned = re.sub(r"\n+", r"\\N", cleaned.strip())
    return cleaned


def _clean_word(w: str) -> str:
    """Strip punctuation and lowercase for token comparison."""
    return re.sub(r"[^\w]", "", w).lower()


# ---------------------------------------------------------------------------
# Diarization & Timestamp Alignment
# ---------------------------------------------------------------------------


@dataclass
class AlignedWord:
    word: str
    clean: str
    start: float
    end: float
    speaker: str


def extract_normalized_words(diarization: Any) -> list[AlignedWord]:
    """Extract normalized timestamped words across all supported diarization formats."""
    words: list[AlignedWord] = []
    if not diarization:
        return words

    try:
        # 1. Deepgram or Speechmatics format
        if isinstance(diarization, dict) and "results" in diarization:
            res_data = diarization.get("results")
            if isinstance(res_data, dict):
                # Deepgram
                channels = res_data.get("channels", [])
                if channels:
                    dg_words = channels[0].get("alternatives", [{}])[0].get("words", [])
                    for w in dg_words:
                        word_str = w.get("punctuated_word") or w.get("word") or ""
                        spk = f"Speaker {w.get('speaker', 0)}"
                        words.append(
                            AlignedWord(
                                word=word_str,
                                clean=_clean_word(word_str),
                                start=float(w.get("start", 0.0)),
                                end=float(w.get("end", 0.0)),
                                speaker=spk,
                            )
                        )
                if words:
                    return words
            elif isinstance(res_data, list):
                # Speechmatics
                for r in res_data:
                    if r.get("type") == "word" and r.get("alternatives"):
                        alt = r["alternatives"][0]
                        word_str = alt.get("content", "")
                        spk_raw = alt.get("speaker", "S0")
                        spk = f"Speaker {spk_raw.lstrip('S') or '0'}"
                        start = float(r.get("start_time", 0.0))
                        end = float(r.get("end_time", start + 0.3))
                        words.append(
                            AlignedWord(
                                word=word_str,
                                clean=_clean_word(word_str),
                                start=start,
                                end=end,
                                speaker=spk,
                            )
                        )
                if words:
                    return words

        # 2. AssemblyAI format (list of utterances with ms timestamps)
        if isinstance(diarization, list):
            for utt in diarization:
                utt_spk = f"Speaker {utt.get('speaker', '0')}"
                utt_words = utt.get("words", [])
                if utt_words:
                    for w in utt_words:
                        word_str = w.get("text", "")
                        words.append(
                            AlignedWord(
                                word=word_str,
                                clean=_clean_word(word_str),
                                start=float(w.get("start", 0)) / 1000.0,
                                end=float(w.get("end", 0)) / 1000.0,
                                speaker=f"Speaker {w.get('speaker', utt.get('speaker', '0'))}",
                            )
                        )
                else:
                    # Fallback if no word-level timestamps in utterance
                    utt_text = utt.get("text", "")
                    u_start = float(utt.get("start", 0)) / 1000.0
                    u_end = float(utt.get("end", 0)) / 1000.0
                    u_words = utt_text.split()
                    count = len(u_words)
                    duration_per_word = (u_end - u_start) / max(1, count)
                    for i, w in enumerate(u_words):
                        words.append(
                            AlignedWord(
                                word=w,
                                clean=_clean_word(w),
                                start=u_start + i * duration_per_word,
                                end=u_start + (i + 1) * duration_per_word,
                                speaker=utt_spk,
                            )
                        )
            if words:
                return words

        # 3. transcribe_cpp / Whisper format (segments)
        if isinstance(diarization, dict) and "segments" in diarization:
            for seg in diarization.get("segments", []):
                seg_spk = f"Speaker {seg.get('speaker', '0')}"
                seg_text = seg.get("text", "")
                s_start = float(seg.get("start", 0.0))
                s_end = float(seg.get("end", s_start + 1.0))
                s_words = seg_text.split()
                count = len(s_words)
                duration_per_word = (s_end - s_start) / max(1, count)
                for i, w in enumerate(s_words):
                    words.append(
                        AlignedWord(
                            word=w,
                            clean=_clean_word(w),
                            start=s_start + i * duration_per_word,
                            end=s_start + (i + 1) * duration_per_word,
                            speaker=seg_spk,
                        )
                    )
    except Exception:
        # Any parse error falls back to empty list -> sequential pacing
        pass

    return words


def align_chunk_timestamps(
    chunks: list[AssessmentChunk],
    diarization: Any = None,
    transcript: str = "",
) -> list[tuple[float, float, str]]:
    """Align or estimate (start_time, end_time, speaker) for every chunk."""
    normalized_words = extract_normalized_words(diarization)
    results: list[tuple[float, float, str]] = []

    current_time_cursor = 0.5  # Start with half-second intro pause
    word_search_idx = 0

    for chunk in chunks:
        # 1. Use explicit attributes if chunk already carries valid timestamps
        start_t = getattr(chunk, "start_time", None)
        end_t = getattr(chunk, "end_time", None)
        spk = getattr(chunk, "speaker", None)

        if start_t is not None and end_t is not None and end_t > start_t:
            spk_label = spk or "Speaker 0"
            results.append((float(start_t), float(end_t), spk_label))
            current_time_cursor = float(end_t) + 0.2
            continue

        chunk_text = getattr(chunk, "text", "") or ""
        tokens = [_clean_word(w) for w in chunk_text.split()]
        tokens = [t for t in tokens if t]

        # 2. Match against normalized diarization words
        matched = False
        if normalized_words and tokens:
            prefix_len = min(4, len(tokens))
            prefix = tokens[:prefix_len]

            for i in range(word_search_idx, max(0, len(normalized_words) - prefix_len + 1)):
                window = [normalized_words[i + k].clean for k in range(prefix_len)]
                if window == prefix:
                    matched_start = normalized_words[i].start
                    end_idx = min(len(normalized_words) - 1, i + len(tokens) - 1)
                    matched_end = max(matched_start + 1.0, normalized_words[end_idx].end)

                    spk_candidates = [normalized_words[k].speaker for k in range(i, end_idx + 1)]
                    detected_spk = (
                        Counter(spk_candidates).most_common(1)[0][0]
                        if spk_candidates
                        else "Speaker 0"
                    )

                    results.append((matched_start, matched_end, spk or detected_spk))
                    current_time_cursor = matched_end + 0.2
                    word_search_idx = end_idx + 1
                    matched = True
                    break

        if not matched:
            # 3. Fallback: Pace sequentially proportional to word count (~2.5 words/sec)
            word_count = len(chunk_text.split())
            est_duration = max(2.2, word_count / 2.5)
            s_time = current_time_cursor
            e_time = s_time + est_duration
            detected_spk = spk or "Speaker 0"
            results.append((round(s_time, 2), round(e_time, 2), detected_spk))
            current_time_cursor = e_time + 0.25

    return results


# ---------------------------------------------------------------------------
# Style Selection & Inline Tagging
# ---------------------------------------------------------------------------


def _speaker_dialogue_style(speaker: str) -> tuple[str, str]:
    """Map speaker string to ASS style name and primary color code."""
    spk_lower = speaker.lower()
    if "1" in spk_lower:
        return "Dialogue_Speaker1", ASS_SPEAKER_1
    elif "2" in spk_lower:
        return "Dialogue_Speaker2", ASS_SPEAKER_2
    elif "3" in spk_lower:
        return "Dialogue_Speaker3", ASS_SPEAKER_3
    return "Dialogue_Speaker0", ASS_SPEAKER_0


def _stylize_dialogue_entities(
    text: str, entities: list[tuple[str, str]], base_color: str = ASS_WHITE
) -> str:
    """Wrap recognized named entities with their respective ASS color tags."""
    if not entities:
        return text

    # Sort entities by length descending to prevent substring collisions
    sorted_entities = sorted(entities, key=lambda e: len(e[0]), reverse=True)
    out = text

    for ent_text, label in sorted_entities:
        color = ENTITY_ASS_COLORS.get(label.upper())
        if not color or not ent_text:
            continue
        # Replace occurrences with colored badge, reverting to base_color
        replacement = f"{{\\c{color}\\b1}}{ent_text}{{\\b0\\c{base_color}}}"
        out = out.replace(ent_text, replacement)

    return out


# ---------------------------------------------------------------------------
# Core ASS Subtitle Exporter
# ---------------------------------------------------------------------------


def generate_ass_script(
    result: AssessmentResult,
    title: str | None = None,
    script_info: dict[str, str] | None = None,
) -> str:
    """Generate a complete, valid, fancy Advanced SubStation Alpha (.ass) subtitle script."""
    doc_title = title or "Audio Overview Assessment"
    chunks = getattr(result, "chunks", [])

    # Resolve diarization: check result attribute first, then audio_metadata JSON
    diarization = getattr(result, "diarization", None)
    if not diarization and getattr(result, "audio_metadata", None):
        try:
            meta = json.loads(result.audio_metadata)
            json_path = meta.get("diarization_saved_to")
            if json_path and os.path.exists(json_path):
                with open(json_path, encoding="utf-8") as f:
                    diarization = json.load(f)
        except Exception:
            pass

    # Align timestamps for all chunks
    aligned = align_chunk_timestamps(
        chunks, diarization=diarization, transcript=getattr(result, "transcript", "")
    )

    # 1. Script Info Header
    info_lines = [
        "[Script Info]",
        "; Script generated by NotebookLM Audio Assessment Exporter",
        f"Title: {doc_title}",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "PlayResX: 1920",
        "PlayResY: 1080",
    ]
    if script_info:
        for k, v in script_info.items():
            info_lines.append(f"{k}: {v}")
    info_lines.append("")

    # 2. V4+ Styles Definition
    styles_lines = [
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # Default / Fallback
        f"Style: Default,Arial,32,{ASS_WHITE},&H000000FF&,{ASS_DARK_SHADOW},{ASS_HEADER_BG},0,0,0,0,100,100,0,0,1,2,2,2,40,40,40,1",
        # Dialogue Styles (Bottom-Center, Alignment 2)
        f"Style: Dialogue_Speaker0,Arial,34,{ASS_SPEAKER_0},&H000000FF&,{ASS_DARK_SHADOW},{ASS_HEADER_BG},0,0,0,0,100,100,0,0,1,2,2,2,60,60,45,1",
        f"Style: Dialogue_Speaker1,Arial,34,{ASS_SPEAKER_1},&H000000FF&,{ASS_DARK_SHADOW},{ASS_HEADER_BG},0,0,0,0,100,100,0,0,1,2,2,2,60,60,45,1",
        f"Style: Dialogue_Speaker2,Arial,34,{ASS_SPEAKER_2},&H000000FF&,{ASS_DARK_SHADOW},{ASS_HEADER_BG},0,0,0,0,100,100,0,0,1,2,2,2,60,60,45,1",
        f"Style: Dialogue_Speaker3,Arial,34,{ASS_SPEAKER_3},&H000000FF&,{ASS_DARK_SHADOW},{ASS_HEADER_BG},0,0,0,0,100,100,0,0,1,2,2,2,60,60,45,1",
        # Fact-Check HUD Styles (Top-Right, Alignment 9)
        f"Style: FactCheck_Pass,Arial,20,{ASS_FC_PASS},&H000000FF&,{ASS_DARK_SHADOW},{ASS_BOX_BG},-1,0,0,0,100,100,0,0,1,2,1,9,40,50,35,1",
        f"Style: FactCheck_Fail,Arial,20,{ASS_FC_FAIL},&H000000FF&,{ASS_DARK_SHADOW},{ASS_BOX_BG},-1,0,0,0,100,100,0,0,1,2,1,9,40,50,35,1",
        f"Style: FactCheck_Bypass,Arial,20,{ASS_FC_BYPASS},&H000000FF&,{ASS_DARK_SHADOW},{ASS_BOX_BG},-1,0,0,0,100,100,0,0,1,2,1,9,40,50,35,1",
        f"Style: FactCheck_Unverified,Arial,20,{ASS_FC_UNVERIFIED},&H000000FF&,{ASS_DARK_SHADOW},{ASS_BOX_BG},-1,0,0,0,100,100,0,0,1,2,1,9,40,50,35,1",
        # Linguistic / SFL Annotations HUD Style (Top-Left, Alignment 7)
        f"Style: Annotation_SFL,Arial,18,{ASS_OFFWHITE},&H000000FF&,{ASS_DARK_SHADOW},{ASS_BOX_BG},0,0,0,0,100,100,0,0,1,2,1,7,50,40,35,1",
        # Top Header / Watermark / Intro Banner (Top-Center, Alignment 8)
        f"Style: Assessment_Header,Arial,18,{ASS_OFFWHITE},&H000000FF&,{ASS_DARK_SHADOW},{ASS_HEADER_BG},0,0,0,0,100,100,0,0,1,1,1,8,40,40,15,1",
        "",
    ]

    # 3. Events Section
    events_lines = [
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    total_chunks = len(chunks)
    passed_chunks = sum(1 for c in chunks if getattr(c, "fact_check_passed", None) is True)

    # Title Card / Intro Banner at 00:00:00 to 00:00:04 (or first chunk start)
    first_start = aligned[0][0] if aligned else 0.0
    intro_end = min(4.5, max(2.5, first_start))
    header_text = (
        r"{\an8\fs24\b1\c"
        + ASS_SPEAKER_1
        + r"}NotebookLM Audio Assessment\N"
        + r"{\fs16\c"
        + ASS_OFFWHITE
        + r"}"
        + sanitize_ass_text(doc_title)
        + rf" • Total Claims: {total_chunks} • Verified: {passed_chunks}"
    )
    events_lines.append(
        f"Dialogue: 3,0:00:00.00,{format_ass_timestamp(intro_end)},Assessment_Header,AssessmentInfo,0,0,0,,{header_text}"
    )

    for idx, chunk in enumerate(chunks):
        start_sec, end_sec, spk = aligned[idx]
        start_ts = format_ass_timestamp(start_sec)
        end_ts = format_ass_timestamp(end_sec)

        # -------------------------------------------------------------------
        # Event A: Main Speaker Dialogue Subtitle (Layer 0)
        # -------------------------------------------------------------------
        spk_style, spk_color = _speaker_dialogue_style(spk)
        raw_text = sanitize_ass_text(getattr(chunk, "text", "") or "")

        # Highlight named entities within the dialogue
        entities = getattr(chunk, "entities", []) or []
        styled_body = _stylize_dialogue_entities(raw_text, entities, base_color=ASS_WHITE)

        # Prefix speaker badge
        speaker_badge = rf"{{\b1\c{spk_color}}}[{spk}]{{\b0\c{ASS_WHITE}}} "
        dialogue_event_text = f"{speaker_badge}{styled_body}"

        events_lines.append(
            f"Dialogue: 0,{start_ts},{end_ts},{spk_style},{spk},0,0,0,,{dialogue_event_text}"
        )

        # -------------------------------------------------------------------
        # Event B: Fact-Check HUD Card (Layer 1, Top-Right)
        # -------------------------------------------------------------------
        fc_passed = getattr(chunk, "fact_check_passed", None)
        fc_citations = getattr(chunk, "fact_check_citations", "") or ""
        clean_citations = sanitize_ass_text(fc_citations)
        clause_id = getattr(chunk, "clause_external_id", f"chunk-{idx + 1:03d}")

        if fc_passed is True:
            if "bypassed" in clean_citations.lower() or "subjective" in clean_citations.lower():
                fc_style = "FactCheck_Bypass"
                badge = rf"{{\b1\c{ASS_FC_BYPASS}}}ℹ FACT-CHECK: BYPASSED (SUBJECTIVE){{\b0}}"
            else:
                fc_style = "FactCheck_Pass"
                badge = rf"{{\b1\c{ASS_FC_PASS}}}✓ FACT-CHECK: VERIFIED{{\b0}}"
        elif fc_passed is False:
            fc_style = "FactCheck_Fail"
            badge = rf"{{\b1\c{ASS_FC_FAIL}}}✗ FACT-CHECK: CONTRADICTION{{\b0}}"
        else:
            fc_style = "FactCheck_Unverified"
            badge = rf"{{\b1\c{ASS_FC_UNVERIFIED}}}? FACT-CHECK: UNVERIFIED{{\b0}}"

        # Truncate evidence string cleanly if very verbose for video display
        if len(clean_citations) > 130:
            evidence_snippet = clean_citations[:127] + "…"
        else:
            evidence_snippet = clean_citations or "No citation data recorded."

        fc_hud_text = (
            rf"{{\an9}}{badge}\N"
            rf"{{\fs15\c{ASS_WHITE}}}Evidence: {evidence_snippet}\N"
            rf"{{\fs13\c{ASS_MUTED}}}[Clause {clause_id}]"
        )
        events_lines.append(
            f"Dialogue: 1,{start_ts},{end_ts},{fc_style},FactCheck,0,0,0,,{fc_hud_text}"
        )

        # -------------------------------------------------------------------
        # Event C: SFL Linguistic Annotations HUD (Layer 2, Top-Left)
        # -------------------------------------------------------------------
        chunk_sfl = getattr(chunk, "sfl", None)
        if chunk_sfl:
            sfl_formatted = format_sfl(chunk_sfl)
            ideational = sfl_formatted["ideational"]
            interpersonal = sfl_formatted["interpersonal"]

            participants = ", ".join(ideational.get("participants", [])) or "none"
            processes = ", ".join(ideational.get("processes", [])) or "none"
            tenor = ", ".join(interpersonal.get("tenor", [])) or "conversational"
            mood = ", ".join(interpersonal.get("mood", [])) or "declarative"
            modality = ", ".join(interpersonal.get("modality", [])) or "neutral"

            # Truncate long SFL items so they stay sleek
            if len(participants) > 35:
                participants = participants[:32] + "…"
            if len(tenor) > 30:
                tenor = tenor[:27] + "…"

            sfl_hud_text = (
                rf"{{\an7\fscx92\fscy92}}{{\b1\c{ASS_SFL_TITLE}}}SFL METAFUNCTIONS{{\b0}}\N"
                rf"{{\fs15\c{ASS_SFL_LABEL}}}Tenor: {{\c{ASS_SFL_TENOR}}}{tenor}\N"
                rf"{{\c{ASS_SFL_LABEL}}}Mood: {{\c{ASS_SFL_MOOD}}}{mood}  {{\c{ASS_SFL_LABEL}}}Modality: {{\c{ASS_SFL_MODALITY}}}{modality}\N"
                rf"{{\c{ASS_SFL_LABEL}}}Participants: {{\c{ASS_WHITE}}}{participants}\N"
                rf"{{\c{ASS_SFL_LABEL}}}Processes: {{\c{ASS_OFFWHITE}}}{processes}"
            )
        else:
            # Fallback annotations: Entities and Topic ID
            ent_summary = (
                ", ".join(f"{name} ({kind})" for name, kind in entities[:3]) if entities else "none"
            )
            top_id = getattr(chunk, "topic_id", -1)
            topic_str = str(top_id) if top_id != -1 else "general"
            sfl_hud_text = (
                rf"{{\an7\fscx92\fscy92}}{{\b1\c{ASS_SFL_TITLE}}}ANNOTATIONS{{\b0}}\N"
                rf"{{\fs15\c{ASS_SFL_LABEL}}}Topic: {{\c{ASS_SFL_MOOD}}}{topic_str}\N"
                rf"{{\c{ASS_SFL_LABEL}}}Entities: {{\c{ASS_WHITE}}}{ent_summary}"
            )

        events_lines.append(
            f"Dialogue: 2,{start_ts},{end_ts},Annotation_SFL,SFL,0,0,0,,{sfl_hud_text}"
        )

    return "\n".join(info_lines + styles_lines + events_lines) + "\n"


def save_assessment_ass(
    result: AssessmentResult,
    output_path: str,
    title: str | None = None,
) -> str:
    """Export assessment to an .ass file on disk. Creates parent directories if missing."""
    content = generate_ass_script(result, title=title)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path
