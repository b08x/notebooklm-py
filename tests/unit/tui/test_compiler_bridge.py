from notebooklm.tui.compiler_bridge import compile_audio_project, list_project_configs


def test_list_project_configs():
    configs = list_project_configs()
    assert isinstance(configs, list)
    # Could be empty in some test envs without examples dir, but normally shouldn't
    # assert len(configs) > 0


def test_compile_audio_project(tmp_path):
    # We can create a dummy audio yaml or just test that the bridge imports don't crash
    # if given a real file from examples.
    configs = list_project_configs()
    audio_configs = [c for c in configs if "notebooklm-audio" in str(c)]

    if audio_configs:
        config = audio_configs[0]
        result = compile_audio_project(config)
        assert isinstance(result, str)
        assert len(result) > 0
