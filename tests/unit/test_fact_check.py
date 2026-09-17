import os
from unittest.mock import MagicMock, patch

from notebooklm._preprocessing.fact_check import FactCheckAdapter


def test_fact_check_routing():
    adapter = FactCheckAdapter()

    # Mock framework availability to test ReAct
    adapter.framework_path = "/tmp"  # assuming it exists or we mock it

    with patch("os.path.exists", return_value=True), \
         patch("notebooklm._preprocessing.fact_check.dspy.ReAct") as mock_react, \
         patch.dict(os.environ, {"EXA_API_KEY": "test_key"}):

        # Create a mock agent that returns a mock result
        mock_agent = MagicMock()
        mock_res = MagicMock()
        mock_res.is_valid = "False"
        mock_res.citations = "Found on Wikipedia"
        mock_agent.return_value = mock_res
        mock_react.return_value = mock_agent

        is_valid, citations = adapter.check("The earth is flat")

        assert is_valid is False
        assert citations == "Found on Wikipedia"

        # Verify ReAct was called
        mock_react.assert_called_once()
