import importlib.util
import sys
from pathlib import Path
from typing import Any


def list_project_configs() -> list[Path]:
    root = Path(__file__).resolve().parent.parent.parent.parent.parent
    examples_dir = root / "examples"

    configs = []

    # Video projects
    video_projects = examples_dir / "notebooklm-video" / "projects"
    if video_projects.exists():
        configs.extend(list(video_projects.glob("*.yaml")))

    # Audio projects
    audio_projects = examples_dir / "notebooklm-audio" / "projects"
    if audio_projects.exists():
        configs.extend(list(audio_projects.glob("*.yaml")))

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
    root = Path(__file__).resolve().parent.parent.parent.parent.parent
    video_dir = root / "examples" / "notebooklm-video"

    # We need to make sure the loaders and models inside video_dir/compiler are resolvable
    # since prompt.py does relative imports. Actually, if we add it to sys.path briefly and remove it?
    # No, relative imports (e.g. from .loaders import x) work if the module is loaded as part of a package.
    # Easiest way: add to sys.path, import under a unique name or clear sys.modules['compiler'].

    sys_path_added = str(video_dir) not in sys.path
    if sys_path_added:
        sys.path.insert(0, str(video_dir))

    if "compiler.prompt" in sys.modules:
        del sys.modules["compiler.prompt"]
    if "compiler.loaders" in sys.modules:
        del sys.modules["compiler.loaders"]
    if "compiler.models" in sys.modules:
        del sys.modules["compiler.models"]

    from compiler.prompt import compile_from_yaml

    result = compile_from_yaml(project_file, prompts_root=video_dir / "compiler" / "prompts")

    if sys_path_added:
        sys.path.remove(str(video_dir))
    return result


def compile_audio_project(project_file: str | Path) -> str:
    root = Path(__file__).resolve().parent.parent.parent.parent.parent
    audio_dir = root / "examples" / "notebooklm-audio"

    sys_path_added = str(audio_dir) not in sys.path
    if sys_path_added:
        sys.path.insert(0, str(audio_dir))

    if "compiler.prompt" in sys.modules:
        del sys.modules["compiler.prompt"]
    if "compiler.loaders" in sys.modules:
        del sys.modules["compiler.loaders"]
    if "compiler.models" in sys.modules:
        del sys.modules["compiler.models"]

    from compiler.prompt import compile_from_yaml

    result = compile_from_yaml(project_file)

    if sys_path_added:
        sys.path.remove(str(audio_dir))
    return result
