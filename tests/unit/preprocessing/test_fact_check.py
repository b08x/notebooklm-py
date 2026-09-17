from unittest.mock import patch

from notebooklm._preprocessing.fact_check import FactCheckAdapter


def test_fact_check_adapter():
    adapter = FactCheckAdapter()
    res = adapter.check("Some fact.")
    assert res is True

@patch("os.path.exists")
def test_fact_check_adapter_with_framework(mock_exists):
    mock_exists.return_value = True
    adapter = FactCheckAdapter()
    res = adapter.check("Some fact.")
    assert res is True
