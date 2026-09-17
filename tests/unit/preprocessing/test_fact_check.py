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


def test_framework_available_false_when_path_missing():
    adapter = FactCheckAdapter()
    adapter.framework_path = "/definitely/does/not/exist"
    assert adapter.framework_available is False


@patch("os.path.exists")
def test_framework_available_true_when_path_present(mock_exists):
    mock_exists.return_value = True
    adapter = FactCheckAdapter()
    assert adapter.framework_available is True
