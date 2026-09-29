from ..state import TUIState

# The compiler view should be rendered by renderers/main.py when state.current_view == View.COMPILER
# It just displays the YAML configs and a preview.
# Audio YAMLs compile (and later generate) through tui/views/compiler_gen.py;
# video YAMLs keep the synchronous preview-only behavior.


def load_compiler_configs(state: TUIState) -> None:
    from ..compiler_bridge import list_project_configs

    configs = list_project_configs()
    state.compiler_state["configs"] = configs
    if configs and "selected_config" not in state.compiler_state:
        state.compiler_state["selected_config"] = 0


def compile_selected(state: TUIState) -> None:
    from ..compiler_bridge import compile_video_project

    configs = state.compiler_state.get("configs", [])
    selected_idx = state.compiler_state.get("selected_config", 0)

    if not configs or selected_idx >= len(configs):
        return

    project_file = configs[selected_idx]

    if "notebooklm-video" in str(project_file):
        try:
            result = compile_video_project(project_file)
            state.compiler_state["preview"] = (
                f"Video Prompt:\n\n{result.style_prompt}\n\nInstructions:\n\n{result.instructions}"
            )
        except Exception as e:
            state.compiler_state["preview"] = f"Error compiling {project_file.name}: {e}"
        return

    # Audio project: compile against the selected sidebar notebook in the
    # background (facts 1–3); compiler_gen handles the compile and its state.
    from .compiler_gen import start_compile

    start_compile(state, project_file)
