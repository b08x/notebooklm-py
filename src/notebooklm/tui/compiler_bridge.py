import importlib.util
import sys
from pathlib import Path
from typing import Any


def list_project_configs() -> list[Path]:
    root = Path(__file__).resolve().parents[3]
    examples_dir = root / "examples"

    configs = []

    # Audio projects (if any exist)
    audio_projects = examples_dir / "notebooklm-audio" / "projects"
    if audio_projects.exists():
        configs.extend(list(audio_projects.glob("*.yaml")))

    # Video projects
    video_projects = examples_dir / "notebooklm-video" / "projects"
    if video_projects.exists():
        configs.extend(list(video_projects.glob("*.yaml")))

    return configs


def _load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def compile_video_project(project_file: str | Path) -> Any:
    root = Path(__file__).resolve().parents[3]
    video_dir = root / "examples" / "notebooklm-video"

    sys_path_added = str(video_dir) not in sys.path
    if sys_path_added:
        sys.path.insert(0, str(video_dir))

    # Audio and video projects ship different ``compiler`` packages under the
    # same name; pop the package too so an audio compile earlier in the session
    # cannot shadow this import.
    for stale in ("compiler", "compiler.prompt", "compiler.loaders", "compiler.models"):
        sys.modules.pop(stale, None)

    from compiler.prompt import compile_from_yaml

    result = compile_from_yaml(project_file, prompts_root=video_dir / "compiler" / "prompts")

    if sys_path_added:
        sys.path.remove(str(video_dir))
    return result


def _with_audio_compiler():
    """Import the examples/ audio compiler under a stable name, one package at a time.

    Adds ``examples/notebooklm-audio`` to ``sys.path`` briefly, clears any
    previously loaded ``compiler.*`` modules (video and audio projects ship
    different ``compiler`` packages, so a stale one must not win), and returns
    the imported ``compiler.prompt`` module. The modules stay importable via
    the package's own absolute ``__path__`` after ``sys.path`` is restored.
    """
    root = Path(__file__).resolve().parents[3]
    audio_dir = root / "examples" / "notebooklm-audio"

    sys_path_added = str(audio_dir) not in sys.path
    if sys_path_added:
        sys.path.insert(0, str(audio_dir))

    # Video and audio projects ship different ``compiler`` packages under the
    # same name; pop the package too so a video compile earlier in the session
    # cannot shadow this import.
    for stale in (
        "compiler",
        "compiler.prompt",
        "compiler.loaders",
        "compiler.models",
        "compiler.auto_bind",
    ):
        sys.modules.pop(stale, None)

    try:
        from compiler import prompt as audio_prompt
    finally:
        if sys_path_added:
            sys.path.remove(str(audio_dir))

    return audio_prompt


def compile_audio_project(project_file: str | Path) -> str:
    return _with_audio_compiler().compile_from_yaml(project_file)


def load_audio_project(project_file: str | Path) -> Any:
    """Load an audio project YAML into an in-memory ``AudioProjectConfig``."""
    _with_audio_compiler()
    from compiler.loaders import load_audio_config

    return load_audio_config(project_file)


def create_audio_config(
    notebook_id: str | None = None, title: str | None = None, **kwargs: Any
) -> Any:
    """Create an in-memory ``AudioProjectConfig`` directly for a notebook."""
    _with_audio_compiler()
    from compiler.loaders import create_audio_config as _create

    return _create(notebook_id=notebook_id, title=title, **kwargs)


def compile_audio_config(config: Any) -> str:
    """Compile an already-loaded ``AudioProjectConfig`` into its prompt text."""
    return _with_audio_compiler().compile_audio_prompt(config)


async def auto_populate_audio_config(client: Any, notebook_id: str, config: Any) -> Any:
    """Run chat-based RAG extraction against a notebook to populate an ``AudioProjectConfig``."""
    _with_audio_compiler()
    from compiler.auto_bind import auto_populate_from_notebook

    return await auto_populate_from_notebook(client, notebook_id, config, verbose=False)
