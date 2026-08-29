"""Общие фикстуры тестов Tion MagicAir."""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Разрешить загрузку кастомной интеграции во всех тестах."""


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Не поднимать интеграцию целиком: проверяется только диалог настройки."""
    with patch(
        "custom_components.tion_magicair.async_setup_entry", return_value=True
    ) as mock_setup:
        yield mock_setup


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Подменить клиента облака, который создаёт config flow."""
    with patch(
        "custom_components.tion_magicair.config_flow.TionApiClient", autospec=True
    ) as mock_class:
        client = mock_class.return_value
        client.async_validate = AsyncMock(return_value=None)
        yield client
