
from .assessment import AssessmentResult


def generate_markdown_report(result: AssessmentResult) -> str:
    """Generate a detailed Markdown report from AssessmentResult."""

    lines = []
    lines.append("# Audio Overview Assessment Report\n")

    # Check SFL Metrics
    sfl = getattr(result, "sfl_metrics", None)
    if sfl:
        lines.append("## SFL Analysis")
        if "error" in sfl:
            lines.append(f"> **Warning:** {sfl['error']}\n")

        profiles = sfl.get("profiles", {})
        if profiles:
            lines.append("### Speaker Profiles")
            for sp, data in profiles.items():
                dominant = data.get('dominant_tenor', 'unknown')
                lines.append(f"- **{sp}**: {data.get('utterances', 0)} utterances, Dominant Tenor: {dominant}")
            lines.append("")

        anomalies = sfl.get("anomalies", [])
        if anomalies:
            lines.append("### Semantic Anomalies")
            for a in anomalies:
                lines.append(f"- **{a['speaker']}**: {a['issue']} (Segment {a['segment_index']})")
                lines.append(f"  > *\"{a.get('text', '')}\"*")
            lines.append("")

    # Fact Checking Results
    lines.append("## Fact-Checking Verdicts")
    lines.append("")
    has_failed_facts = False

    for c in result.chunks:
        if c.fact_check_passed is False:
            has_failed_facts = True
            lines.append(f"- **Failed Fact Check** in chunk {c.clause_external_id}:")
            lines.append(f"  > {c.text}")
            if getattr(c, "fact_check_citations", None):
                lines.append(f"  > **Citations:** {c.fact_check_citations}")

    if not has_failed_facts:
        lines.append("No fact-check failures detected.")

    lines.append("\n## Data Quality")
    if has_failed_facts or (sfl and sfl.get("anomalies")):
        lines.append("> [!WARNING]")
        lines.append("> The audio overview contains flagged semantic anomalies or failed fact checks. Please review the highlighted sections.")
    else:
        lines.append("> [!NOTE]")
        lines.append("> The audio overview passed basic checks.")

    return "\n".join(lines)
