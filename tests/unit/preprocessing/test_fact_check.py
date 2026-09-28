import os
from unittest.mock import MagicMock, patch

import dspy

from notebooklm._preprocessing.fact_check import FactCheckAdapter


def test_fact_check_adapter():
    adapter = FactCheckAdapter()
    adapter.framework_path = "/definitely/does/not/exist"
    res = adapter.check("Some fact.")
    assert res == (True, "")


@patch.object(os.path, "exists", return_value=True)
def test_fact_check_adapter_with_framework(mock_exists):
    mock_agent = MagicMock()
    mock_res = MagicMock(is_valid="True", citations="source-1")
    mock_agent.return_value = mock_res
    with patch.object(dspy, "ReAct", return_value=mock_agent):
        adapter = FactCheckAdapter()
        is_valid, citations = adapter.check("Some fact.")
        assert is_valid is True
        assert citations == "source-1"


def test_framework_available_false_when_path_missing():
    adapter = FactCheckAdapter()
    adapter.framework_path = "/definitely/does/not/exist"
    assert adapter.framework_available is False


@patch.object(os.path, "exists", return_value=True)
def test_framework_available_true_when_path_present(mock_exists):
    adapter = FactCheckAdapter()
    assert adapter.framework_available is True
