"""Unit tests for ``examples/notebooklm-audio/runner.py`` (facts 13–14).

The runner lives outside the package, so it is loaded from its file path; its
import-time ``sys.path`` inserts make the ``compiler`` package resolvable.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from notebooklm.types import AudioFormat, AudioLength

RUNNER_PATH = Path(__file__).resolve().parents[2] / "examples" / "notebooklm-audio" / "runner.py"


@pytest.fixture(scope="module")
def runner():
    spec = importlib.util.spec_from_file_location("notebooklm_audio_runner_test", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audio_config(runner):
    """A real ``AudioProjectConfig`` via the compiler's own loader."""
    from compiler.loaders import load_audio_config

    yaml = RUNNER_PATH.parent / "projects" / "custom-telemetry-session.yaml"
    return load_audio_config(yaml)


# ---------------------------------------------------------------------------
# Format / length mapping (fact 14)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [
        ("deep-dive", AudioFormat.DEEP_DIVE),
        ("brief", AudioFormat.BRIEF),
        ("critique", AudioFormat.CRITIQUE),
        ("debate", AudioFormat.DEBATE),
        ("default", None),
        ("", None),
    ],
)
def test_runner_to_audio_enums_formats(runner, fmt, expected):
    assert runner.to_audio_enums(fmt, "default")[0] is expected


@pytest.mark.parametrize(
    ("length", "expected"),
    [
        ("short", AudioLength.SHORT),
        ("default", None),
        ("long", AudioLength.LONG),
        ("", None),
    ],
)
def test_runner_to_audio_enums_lengths(runner, length, expected):
    assert runner.to_audio_enums("deep-dive", length)[1] is expected


def test_runner_to_audio_enums_matches_tui_mapping(runner):
    """The duplicated helper must agree with the TUI's mapping (plan Step 2)."""
    from notebooklm.tui.views.compiler_gen import to_audio_enums as tui_mapping

    for fmt in ("deep-dive", "brief", "critique", "debate", "default", "bogus"):
        for length in ("short", "default", "long", "bogus"):
            try:
                expected = tui_mapping(fmt, length)
            except ValueError:
                with pytest.raises(ValueError):
                    runner.to_audio_enums(fmt, length)
                continue
            assert runner.to_audio_enums(fmt, length) == expected


# ---------------------------------------------------------------------------
# --emit (fact 13)
# ---------------------------------------------------------------------------


def test_emit_prints_only_the_compiled_prompt(runner, audio_config, monkeypatch, capsys):
    async def fake_auto_populate(client, notebook_id, config, verbose=True):
        assert verbose is False, "--emit must run auto-bind with verbose=False"
        return config

    class _CM:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(runner, "auto_populate_from_notebook", fake_auto_populate)
    monkeypatch.setattr(runner, "NotebookLMClient", SimpleNamespace(from_storage=lambda: _CM()))

    import asyncio

    asyncio.run(runner.emit_compiled_prompt(audio_config, "nb-1"))

    captured = capsys.readouterr()
    compiled = runner.compile_audio_prompt(audio_config)
    assert captured.out.strip() == compiled
    # No banner lines on stdout — it is piped straight into `--prompt-file -`.
    assert "Auto-Bind" not in captured.out
    assert "───" not in captured.out
    assert captured.err  # diagnostics went to stderr


def test_main_emit_without_notebook_exits(runner, monkeypatch):
    yaml = RUNNER_PATH.parent / "projects" / "custom-telemetry-session.yaml"
    monkeypatch.setattr(sys, "argv", ["runner.py", str(yaml), "--emit"])
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# --execute passes the enums through (fact 14)
# ---------------------------------------------------------------------------


def test_execute_passes_format_and_length_enums(runner, audio_config, monkeypatch, tmp_path):
    import asyncio

    audio_config.audio_format = "deep-dive"
    audio_config.audio_length = "long"

    generate_calls: list[dict] = []

    async def fake_auto_populate(client, notebook_id, config, verbose=True):
        return config

    class _Artifacts:
        async def generate_audio(
            self, notebook_id, instructions=None, audio_format=None, audio_length=None, **kw
        ):
            generate_calls.append(
                {
                    "instructions": instructions,
                    "audio_format": audio_format,
                    "audio_length": audio_length,
                }
            )
            return SimpleNamespace(task_id="task-1")

        async def wait_for_completion(self, notebook_id, task_id, **kw):
            return SimpleNamespace(is_complete=True, task_id=task_id)

        async def download_audio(self, notebook_id, output_path, artifact_id=None, **kw):
            Path(output_path).write_bytes(b"mp3")
            return output_path

    class _Client:
        artifacts = _Artifacts()

    class _CM:
        async def __aenter__(self):
            return _Client()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(runner, "auto_populate_from_notebook", fake_auto_populate)
    monkeypatch.setattr(runner, "NotebookLMClient", SimpleNamespace(from_storage=lambda: _CM()))

    out = tmp_path / "out.mp3"
    asyncio.run(runner.execute_audio_pipeline(audio_config, str(out), notebook_id="nb-1"))

    assert generate_calls[0]["audio_format"] is AudioFormat.DEEP_DIVE
    assert generate_calls[0]["audio_length"] is AudioLength.LONG
    assert generate_calls[0]["instructions"] == runner.compile_audio_prompt(audio_config)
    assert out.read_bytes() == b"mp3"
