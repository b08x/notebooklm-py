from unittest.mock import AsyncMock, patch

from notebooklm._types.notebooks import Notebook
from notebooklm.tui.cache import TUICache
from notebooklm.tui.state import TUIState
from notebooklm.tui.views import notebook_list
from notebooklm.tui.views.notebook_list import load_notebooks_sync


def test_load_notebooks_sync_success(tmp_path):
    state = TUIState()
    state.tui_cache = TUICache(cache_path=tmp_path / "tui_cache.json")

    mock_nbs = [
        Notebook(id="nb-1", title="Alpha"),
        Notebook(id="nb-2", title="Beta"),
    ]

    with patch.object(notebook_list, "fetch_notebooks", new_callable=AsyncMock) as m:
        m.return_value = mock_nbs
        load_notebooks_sync(state)

    assert state.notebooks == mock_nbs
    assert state.selected_notebook == "nb-1"
    assert state.error_message is None

    # Cached
    assert len(state.tui_cache.get_notebooks()) == 2


def test_load_notebooks_sync_failure_with_cache_fallback(tmp_path):
    cache = TUICache(cache_path=tmp_path / "tui_cache.json")
    cached_nbs = [Notebook(id="cached-1", title="Cached Notebook")]
    cache.save_notebooks(cached_nbs)

    state = TUIState()
    state.tui_cache = cache

    with patch.object(notebook_list, "fetch_notebooks", new_callable=AsyncMock) as m:
        m.side_effect = RuntimeError("Network unreachable")
        load_notebooks_sync(state)

    # Falls back to cache
    assert len(state.notebooks) == 1
    assert state.notebooks[0].id == "cached-1"
    assert state.selected_notebook == "cached-1"
    assert "Network unreachable" in (state.error_message or "")


def test_load_notebooks_sync_failure_preserves_existing_notebooks(tmp_path):
    state = TUIState()
    state.notebooks = [Notebook(id="nb-existing", title="Existing")]
    state.selected_notebook = "nb-existing"

    with patch.object(notebook_list, "fetch_notebooks", new_callable=AsyncMock) as m:
        m.side_effect = RuntimeError("503 Service Unavailable")
        load_notebooks_sync(state)

    # Existing notebooks must not be wiped out!
    assert len(state.notebooks) == 1
    assert state.notebooks[0].id == "nb-existing"
    assert "503 Service Unavailable" in (state.error_message or "")


def test_load_notebooks_sync_failure_no_cache(tmp_path):
    state = TUIState()
    state.tui_cache = TUICache(cache_path=tmp_path / "tui_cache.json")

    with patch.object(notebook_list, "fetch_notebooks", new_callable=AsyncMock) as m:
        m.side_effect = RuntimeError("Auth expired")
        load_notebooks_sync(state)

    assert state.notebooks == []
    assert state.selected_notebook is None
    assert "Auth expired" in (state.error_message or "")
