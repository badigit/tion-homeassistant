"""Тесты транспортного слоя клиента: авторизация, повторы, команды."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.tion_magicair import api as tion_api
from custom_components.tion_magicair.api import (
    API_BASE,
    AUTH_URL,
    LOCATION_URL,
    TionApiClient,
    TionAuthError,
    TionCommandError,
    TionConnectionError,
    TionError,
)

from .conftest import BREEZER_GUID, RAW_LOCATION

TOKEN = {"token_type": "Bearer", "access_token": "abc123"}


def _client(hass: HomeAssistant, **kwargs: Any) -> TionApiClient:
    """Клиент на сессии Home Assistant — её и подменяет aioclient_mock."""
    return TionApiClient(
        async_get_clientsession(hass), "owner@example.com", "секрет", **kwargs
    )


async def test_authenticate_saves_token(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Полученный токен отдаётся наружу, чтобы его сохранили."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    saved: list[str] = []

    async def remember(token: str) -> None:
        saved.append(token)

    client = _client(hass, token_callback=remember)
    await client.async_authenticate()

    assert client.token == "Bearer abc123"
    assert saved == ["Bearer abc123"]


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_authenticate_rejects_credentials(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status: int
) -> None:
    """Отказ по учётным данным ведёт в повторный вход, а не в «нет сети»."""
    aioclient_mock.post(AUTH_URL, status=status)

    with pytest.raises(TionAuthError):
        await _client(hass).async_authenticate()


async def test_authenticate_server_error_is_connection(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Пятисотка — это связь, а не пароль."""
    aioclient_mock.post(AUTH_URL, status=502)

    with pytest.raises(TionConnectionError):
        await _client(hass).async_authenticate()


async def test_authenticate_timeout(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Молчание облака не должно выглядеть как неверный пароль."""
    aioclient_mock.post(AUTH_URL, exc=TimeoutError)

    with pytest.raises(TionConnectionError):
        await _client(hass).async_authenticate()


async def test_authenticate_body_without_token(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Ответ без токена — тоже отказ авторизации."""
    aioclient_mock.post(AUTH_URL, json={"unexpected": True})

    with pytest.raises(TionAuthError):
        await _client(hass).async_authenticate()


async def test_fetch_parses_devices(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Обычное чтение состояния аккаунта."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, json=RAW_LOCATION)

    snapshot = await _client(hass).async_fetch()

    assert set(snapshot.locations) == {RAW_LOCATION[0]["guid"]}
    assert BREEZER_GUID in snapshot.devices


async def test_fetch_rejects_unexpected_body(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Не список — значит облако ответило не тем, чем должно."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, json={"error": "nope"})

    with pytest.raises(TionError):
        await _client(hass).async_fetch()


async def test_fetch_without_devices(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Пустой аккаунт — повод сказать об этом, а не поднять ноль сущностей."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, json=[{"guid": "loc", "name": "Дом", "zones": []}])

    with pytest.raises(TionError):
        await _client(hass).async_fetch()


class _Response:
    """Ответ-заглушка с интерфейсом aiohttp."""

    def __init__(self, status: int, payload: Any, delay: float = 0) -> None:
        self.status = status
        self._payload = payload
        self._delay = delay

    async def json(self, content_type: Any = None) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientResponseError(None, (), status=self.status)

    async def __aenter__(self) -> _Response:
        # Уступаем управление: без этого две корутины выполняются строго
        # последовательно и гонку за токеном воспроизвести нельзя.
        await asyncio.sleep(self._delay)
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _SequencedSession:
    """Сессия, отдающая заранее заданную очередь ответов.

    Мокер aiohttp из Home Assistant всегда возвращает первое совпадение по
    адресу и очередь не держит, а здесь нужен именно порядок: 401, затем
    логин, затем успешный повтор.
    """

    def __init__(self, responses: list[_Response]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, str | None]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        headers = kwargs.get("headers") or {}
        self.calls.append((method, url, headers.get("Authorization")))
        return self._responses.pop(0)

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append(("POST", url, None))
        return self._responses.pop(0)


async def test_expired_token_is_refreshed() -> None:
    """Протухший токен обновляется прозрачно, ровно одна повторная попытка."""
    session = _SequencedSession(
        [
            _Response(401, None),  # запрос со старым токеном
            _Response(200, TOKEN),  # логин
            _Response(200, RAW_LOCATION),  # повтор
        ]
    )
    client = TionApiClient(
        session, "owner@example.com", "секрет", token="Bearer протухший"
    )

    snapshot = await client.async_fetch()

    assert BREEZER_GUID in snapshot.devices
    assert client.token == "Bearer abc123"
    # Ровно три обращения, и повтор ушёл уже с новым токеном.
    assert len(session.calls) == 3
    assert session.calls[0][2] == "Bearer протухший"
    assert session.calls[2][2] == "Bearer abc123"


async def test_permanent_401_gives_up(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Если и свежий токен не принят — это отказ авторизации."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, status=401)

    with pytest.raises(TionAuthError):
        await _client(hass, token="Bearer протухший").async_fetch()


async def test_fetch_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Обрыв связи не превращается в отказ авторизации."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, exc=TimeoutError)

    with pytest.raises(TionConnectionError):
        await _client(hass).async_fetch()


async def test_validate(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Проверка учётных данных — это логин плюс чтение устройств."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, json=RAW_LOCATION)

    assert (await _client(hass).async_validate()).devices


async def _prepared(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> tuple[TionApiClient, Any]:
    """Клиент со свежим снимком: из него берётся бризер для команд."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, json=RAW_LOCATION)
    client = _client(hass)
    snapshot = await client.async_fetch()
    return client, snapshot.devices[BREEZER_GUID]


async def test_send_breezer_waits_for_task(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Команда считается выполненной только после подтверждения задачи."""
    client, breezer = await _prepared(hass, aioclient_mock)
    aioclient_mock.post(
        f"{API_BASE}/device/{BREEZER_GUID}/mode",
        json={"status": "queued", "task_id": "task-1"},
    )
    aioclient_mock.get(f"{API_BASE}/task/task-1", json={"status": "completed"})

    await client.async_send_breezer(breezer, speed=3)

    sent = aioclient_mock.mock_calls[2][2]
    assert sent["speed"] == 3
    assert sent["is_on"] is True


async def test_send_zone(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Режим зоны уходит вместе с текущим порогом CO2."""
    client, breezer = await _prepared(hass, aioclient_mock)
    aioclient_mock.post(
        f"{API_BASE}/zone/{breezer.zone.guid}/mode",
        json={"status": "queued", "task_id": "task-2"},
    )
    aioclient_mock.get(f"{API_BASE}/task/task-2", json={"status": "completed"})

    await client.async_send_zone(breezer.zone, mode="auto")

    assert aioclient_mock.mock_calls[2][2] == {"mode": "auto", "co2": 900}


async def test_send_rejected_by_cloud(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Облако не поставило команду в очередь — это ошибка команды."""
    client, breezer = await _prepared(hass, aioclient_mock)
    aioclient_mock.post(
        f"{API_BASE}/device/{BREEZER_GUID}/mode",
        json={"status": "rejected", "description": "устройство занято"},
    )

    with pytest.raises(TionCommandError, match="занято"):
        await client.async_send_breezer(breezer)


async def test_task_never_completes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Задача, которую облако не подтвердило, не выдаётся за успех."""
    monkeypatch.setattr(tion_api, "TASK_ATTEMPTS", 2)
    monkeypatch.setattr(tion_api, "TASK_POLL_INTERVAL", 0)

    client, breezer = await _prepared(hass, aioclient_mock)
    aioclient_mock.post(
        f"{API_BASE}/device/{BREEZER_GUID}/mode",
        json={"status": "queued", "task_id": "task-3"},
    )
    aioclient_mock.get(f"{API_BASE}/task/task-3", json={"status": "pending"})

    with pytest.raises(TionCommandError):
        await client.async_send_breezer(breezer)


class _RaceSession:
    """Сессия, отвергающая всё, кроме последнего выданного токена."""

    def __init__(self) -> None:
        self.logins = 0
        self.seen: list[str | None] = []
        self.valid_token: str | None = None

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.logins += 1
        self.valid_token = f"Bearer t{self.logins}"
        # Логин намеренно медленный: пока он идёт, второй запрос обязан успеть
        # получить свой 401 и упереться в блокировку.
        return _Response(
            200, {"token_type": "Bearer", "access_token": f"t{self.logins}"}, delay=0.05
        )

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        auth = (kwargs.get("headers") or {}).get("Authorization")
        self.seen.append(auth)
        if auth != self.valid_token:
            return _Response(401, None)
        return _Response(200, RAW_LOCATION)


async def test_concurrent_401_logs_in_once() -> None:
    """Два запроса, одновременно получившие 401, логинятся один раз.

    Прошлая версия теста проверяла только итоговый токен и оставалась зелёной
    ровно при том поведении, которое отрицает её название. Здесь считается
    число обращений к endpoint авторизации, и пустой Authorization во второй
    попытке тоже не проходит.
    """
    session = _RaceSession()
    client = TionApiClient(
        session, "owner@example.com", "секрет", token="Bearer протухший"
    )

    first, second = await asyncio.gather(client.async_fetch(), client.async_fetch())

    assert BREEZER_GUID in first.devices
    assert BREEZER_GUID in second.devices
    assert session.logins == 1
    assert "" not in session.seen
