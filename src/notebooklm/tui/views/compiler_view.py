from ..state import TUIState

# The compiler view should be rendered by renderers/main.py when state.current_view == View.COMPILER
# It presents a direct compile dashboard for the active notebook with extraction controls.


def load_compiler_configs(state: TUIState) -> None:
    from ..compiler_bridge import list_project_configs

    configs = [c for c in list_project_configs() if "notebooklm-video" not in str(c)]
    state.compiler_state["configs"] = configs
    state.compiler_state.setdefault("template", "mr-and-mrs-language-model")
    state.compiler_state.setdefault("audio_format", "default")
    state.compiler_state.setdefault("audio_length", "default")


def compile_selected(state: TUIState) -> None:
    from ..compiler_bridge import compile_video_project

    configs = state.compiler_state.get("configs", [])
    selected_idx = state.compiler_state.get("selected_config")

    if (
        selected_idx is not None
        and configs
        and selected_idx < len(configs)
        and "notebooklm-video" in str(configs[selected_idx])
    ):
        project_file = configs[selected_idx]
        try:
            result = compile_video_project(project_file)
            state.compiler_state["preview"] = (
                f"Video Prompt:\n\n{result.style_prompt}\n\nInstructions:\n\n{result.instructions}"
            )
        except Exception as e:
            state.compiler_state["preview"] = f"Error compiling {project_file.name}: {e}"
        return

    # Audio compile against the selected sidebar notebook directly
    from .compiler_gen import start_compile

    project_file = (
        configs[selected_idx]
        if selected_idx is not None
        and configs
        and selected_idx < len(configs)
        and "notebooklm-video" not in str(configs[selected_idx])
        else None
    )
    start_compile(state, project_file)
