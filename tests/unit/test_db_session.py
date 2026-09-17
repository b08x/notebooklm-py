from unittest.mock import MagicMock, patch

import pytest

from notebooklm.db.session import get_db_session


@pytest.mark.asyncio
async def test_get_db_session():
    with patch("notebooklm.db.session.async_session_maker") as mock_maker:
        mock_session = MagicMock()
        mock_maker.return_value.__aenter__.return_value = mock_session

        generator = get_db_session()
        session = await anext(generator)

        assert session is mock_session
        mock_maker.assert_called_once()
