from rich.layout import Layout
from rich.panel import Panel

class AssessmentView:
    def __init__(self, state):
        self.state = state

    def __rich__(self) -> Layout:
        layout = Layout()
        layout.split_row(
            Layout(name="left"),
            Layout(name="right")
        )
        
        assessment_state = getattr(self.state, "assessment_state", {})
        audio_meta = assessment_state.get("audio_metadata", "No Audio Metadata Available.")
        sys_inst = assessment_state.get("system_instructions", "No System Instructions Available.")
        chunks = assessment_state.get("chunks", ["No Source Chunks Available."])
        llm_score = assessment_state.get("llm_score", "LLM Score Pending...")
        
        left_text = f"Audio Output Metadata:\n{audio_meta}\n\nSystem Instructions:\n{sys_inst}\n\nSuggested Score:\n{llm_score}\n\n[Press Enter to confirm or edit score]"
        left_panel = Panel(left_text, title="Assessment Controls")
        
        chunks_text = "\n\n".join(chunks)
        
        # Support scrolling by splitting into lines and taking a slice
        scroll_offset = assessment_state.get("scroll_offset", 0)
        lines = chunks_text.split("\n")
        visible_lines = lines[scroll_offset:scroll_offset + 30]  # Arbitrary visible limit
        display_text = "\n".join(visible_lines)
        
        right_panel = Panel(display_text, title=f"Contextualized Source Chunks (Scroll: {scroll_offset})")
        
        layout["left"].update(left_panel)
        layout["right"].update(right_panel)
        
        return layout
