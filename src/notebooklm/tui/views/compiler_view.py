from ..state import TUIState

# The compiler view should be rendered by renderers/main.py when state.current_view == View.COMPILER
# It just displays the YAML configs and a preview.
# For simplicity in TUI, maybe we just list configs and allow compiling, updating state.compiler_state


def load_compiler_configs(state: TUIState) -> None:
    from ..compiler_bridge import list_project_configs

    configs = list_project_configs()
    state.compiler_state["configs"] = configs
    if configs and "selected_config" not in state.compiler_state:
        state.compiler_state["selected_config"] = 0


def compile_selected(state: TUIState) -> None:
    from ..compiler_bridge import compile_audio_project, compile_video_project

    configs = state.compiler_state.get("configs", [])
    selected_idx = state.compiler_state.get("selected_config", 0)

    if not configs or selected_idx >= len(configs):
        return

    project_file = configs[selected_idx]

    try:
        if "notebooklm-video" in str(project_file):
            result = compile_video_project(project_file)
            state.compiler_state["preview"] = (
                f"Video Prompt:\n\n{result.style_prompt}\n\nInstructions:\n\n{result.instructions}"
            )
        else:
            result = compile_audio_project(project_file)
            state.compiler_state["preview"] = result
    except Exception as e:
        state.compiler_state["preview"] = f"Error compiling {project_file.name}: {e}"
