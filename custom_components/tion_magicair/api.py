"""Асинхронный клиент облака Tion MagicAir.

Модуль намеренно ничего не знает про Home Assistant: сессию ему отдают
снаружи, ошибки он поднимает своими типами, состояние отдаёт дата-классами.
Проверено на api2.magicair.tion.ru: MagicAir (co2mb) и бризер O₂ (tionO2Rf).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from http import HTTPStatus
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_BASE = "https://api2.magicair.tion.ru"
AUTH_URL = f"{API_BASE}/idsrv/oauth2/token"
LOCATION_URL = f"{API_BASE}/location"

# Клиент официального веб-кабинета magicair.tion.ru; другого способа получить
# токен у облака нет.
CLIENT_ID = "cd594955-f5ba-4c20-9583-5990bb29f4ef"
CLIENT_SECRET = "syRxSrT77P"

# Облако отвечает 403 на запрос без узнаваемых заголовков кабинета.
BASE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU",
    "Origin": "https://magicair.tion.ru",
    "Referer": "https://magicair.tion.ru/dashboard/overview",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/46.0.2486.0 Safari/537.36 Edge/13.10586"
    ),
}

DEFAULT_TIMEOUT = 15
TASK_POLL_INTERVAL = 0.5
TASK_ATTEMPTS = 20

# Статусы, после которых ждать больше нечего: облако уже отказалось выполнять
# команду. Без этого списка отказ маскировался десятью секундами опроса, а
# причина из description терялась.
TASK_FAILED_STATUSES = frozenset(
    {"error", "failed", "rejected", "cancelled", "canceled", "timeout", "aborted"}
)

ZONE_MODE_AUTO = "auto"
ZONE_MODE_MANUAL = "manual"

DEFAULT_TARGET_CO2 = 900
DEFAULT_MAX_SPEED = 6

GATE_INSIDE = 0
GATE_MIXED = 1
GATE_OUTSIDE = 2


class TionError(Exception):
    """Базовая ошибка облака Tion."""


class TionAuthError(TionError):
    """Облако не приняло учётные данные или токен."""


class TionConnectionError(TionError):
    """До облака не достучались."""


class TionCommandError(TionError):
    """Облако приняло запрос, но не выполнило команду."""


def _number(value: Any) -> float | None:
    """Привести значение облака к числу; 'NaN' и мусор дают None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    # NaN приходит строкой "NaN" у датчиков, которых в устройстве нет.
    return None if result != result else result


def _flag(value: Any) -> bool | None:
    """Привести значение облака к булеву, сохранив отсутствие как None."""
    return None if value is None else bool(value)


def _text(value: Any) -> str | None:
    """Привести значение облака к непустой строке."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(slots=True)
class TionLocation:
    """Локация аккаунта — верхний узел дерева, он же хаб для устройств."""

    guid: str
    name: str
    mac: str | None
    is_online: bool | None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> TionLocation:
        """Собрать локацию из ответа /location."""
        return cls(
            guid=raw["guid"],
            name=_text(raw.get("name")) or "Tion",
            mac=_text(raw.get("mac")),
            is_online=_flag((raw.get("connection") or {}).get("is_online")),
        )


@dataclass(slots=True)
class TionZone:
    """Зона (комната): режим и порог CO₂ для автоматики."""

    guid: str
    name: str
    mode: str | None
    target_co2: float | None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> TionZone:
        """Собрать зону из ответа /location."""
        mode = raw.get("mode") or {}
        return cls(
            guid=raw["guid"],
            name=_text(raw.get("name")) or "",
            mode=_text(mode.get("current")),
            target_co2=_number((mode.get("auto_set") or {}).get("co2")),
        )

    def mode_payload(
        self, *, mode: str | None = None, target_co2: float | None = None
    ) -> dict[str, Any]:
        """Построить тело запроса POST /zone/{guid}/mode."""
        new_co2 = target_co2 if target_co2 is not None else self.target_co2

        if mode is not None:
            if mode not in (ZONE_MODE_AUTO, ZONE_MODE_MANUAL):
                raise TionCommandError(f"Неизвестный режим зоны: {mode}")
            new_mode = mode
        else:
            # Режим не меняем — возвращаем облаку его же значение. Подмена на
            # manual молча отключала бы автоматику, например при правке порога
            # CO2 в зоне, режим которой интеграции незнаком.
            new_mode = self.mode or ZONE_MODE_MANUAL

        return {
            "mode": new_mode,
            "co2": int(round(new_co2)) if new_co2 is not None else DEFAULT_TARGET_CO2,
        }


@dataclass(slots=True, kw_only=True)
class TionDevice:
    """Общая часть любого устройства аккаунта."""

    guid: str
    name: str
    type: str
    mac: str | None
    firmware: str | None
    hardware: str | None
    serial_number: str | None
    is_online: bool | None
    signal_level: float | None
    zone: TionZone
    location_guid: str

    @property
    def valid(self) -> bool:
        """Можно ли верить показаниям прямо сейчас."""
        return self.is_online is not False


@dataclass(slots=True, kw_only=True)
class TionMagicAir(TionDevice):
    """Станция MagicAir: CO₂, климат комнаты и, у новых моделей, пыль."""

    co2: float | None
    temperature: float | None
    humidity: float | None
    pm1: float | None
    pm25: float | None
    pm10: float | None
    backlight: float | None
    wifi_signal: float | None


@dataclass(slots=True, kw_only=True)
class TionBreezer(TionDevice):
    """Бризер: приток, нагрев, ресурс фильтра."""

    data_valid: bool | None
    is_on: bool | None
    heater_installed: bool | None
    heater_enabled: bool | None
    speed: float | None
    speed_m3h: float | None
    speed_limit: float | None
    speed_min_set: float | None
    speed_max_set: float | None
    t_in: float | None
    t_out: float | None
    t_set: float | None
    t_min: float | None
    t_max: float | None
    gate: int | None
    run_seconds: float | None
    filter_time_seconds: float | None
    filter_need_replace: bool | None
    error_code: str | None

    @property
    def valid(self) -> bool:
        """Бризер отдельно сообщает, что его телеметрия свежая."""
        return self.is_online is not False and self.data_valid is not False

    @property
    def max_speed(self) -> int:
        """Потолок скорости конкретной модели: у O₂ — 4, у S3/S4 — 6."""
        return int(self.speed_limit) if self.speed_limit else DEFAULT_MAX_SPEED

    def mode_payload(self, **changes: Any) -> dict[str, Any]:
        """Построить тело запроса POST /device/{guid}/mode.

        Облако принимает состояние целиком, поэтому неизменённые поля берутся
        из текущего снимка, а вызывающий передаёт только то, что меняет.
        """
        state: dict[str, Any] = {
            "heater_enabled": self.heater_enabled,
            "t_set": self.t_set,
            "speed": self.speed,
            "speed_min_set": self.speed_min_set,
            "speed_max_set": self.speed_max_set,
            "gate": self.gate,
        }
        # Заслонку, заданную явно, шлём всегда: вызывающий уже перевёл зону в
        # ручной режим, а его снимок зоны об этом ещё не знает.
        gate_explicit = "gate" in changes
        state.update(changes)

        speed = int(round(state["speed"] or 0))
        heater_enabled = bool(state["heater_enabled"])
        t_set = state["t_set"]
        speed_max_set = state["speed_max_set"]

        payload: dict[str, Any] = {
            # Скорости 0 в протоколе нет: выключение задаётся флагом is_on.
            "is_on": speed > 0,
            "speed": speed if speed > 0 else 1,
            "heater_enabled": heater_enabled,
            # heater_mode нужен моделям 4S, остальные его игнорируют.
            "heater_mode": "heat" if heater_enabled else "maintenance",
            "t_set": int(round(t_set)) if t_set is not None else 10,
            "speed_min_set": int(round(state["speed_min_set"] or 0)),
            "speed_max_set": (
                int(round(speed_max_set))
                if speed_max_set is not None
                else self.max_speed
            ),
        }
        # Заслонку облако принимает только в ручном режиме зоны.
        if state["gate"] is not None and (
            gate_explicit or self.zone.mode == ZONE_MODE_MANUAL
        ):
            payload["gate"] = int(state["gate"])
        return payload


@dataclass(slots=True)
class TionSnapshot:
    """Состояние всего аккаунта на момент одного опроса."""

    locations: dict[str, TionLocation] = field(default_factory=dict)
    devices: dict[str, TionMagicAir | TionBreezer] = field(default_factory=dict)


def _classify(device_type: str, data: dict[str, Any]) -> str | None:
    """Определить, чем является устройство: станцией или бризером.

    Сначала по имени типа — так опознаются известные модели (co2mb, co2plus,
    tionO2Rf, breezer3, breezer4, tionLite). Если модель новая, решает состав
    телеметрии: у бризера есть скорость и температура притока, у станции —
    углекислый газ. Список типов в мёртвой библиотеке tion состоял из трёх
    строк, из-за чего Lite и Clever в неё не попадали вовсе.
    """
    lowered = device_type.lower()
    if "co2" in lowered:
        return "magicair"
    if any(word in lowered for word in ("breezer", "o2", "lite", "clever")):
        return "breezer"

    if {"t_in", "speed", "speed_m3h"} & data.keys():
        return "breezer"
    if "co2" in data:
        return "magicair"
    return None


def _parse_device(
    raw: dict[str, Any], zone: TionZone, location_guid: str
) -> TionMagicAir | TionBreezer | None:
    """Разобрать устройство из ответа /location; неизвестное — пропустить."""
    data: dict[str, Any] = raw.get("data") or {}
    device_type = raw.get("type") or ""
    common: dict[str, Any] = {
        "guid": raw["guid"],
        "name": _text(raw.get("name")) or device_type or "Tion",
        "type": device_type,
        "mac": _text(raw.get("mac")),
        "firmware": _text(raw.get("firmware")),
        "hardware": _text(raw.get("hardware")),
        "serial_number": _text(raw.get("serial_number")),
        "is_online": _flag(raw.get("is_online")),
        "signal_level": _number(data.get("signal_level")),
        "zone": zone,
        "location_guid": location_guid,
    }

    kind = _classify(device_type, data)
    if kind == "magicair":
        return TionMagicAir(
            **common,
            co2=_number(data.get("co2")),
            temperature=_number(data.get("temperature")),
            humidity=_number(data.get("humidity")),
            pm1=_number(data.get("pm1")),
            pm25=_number(data.get("pm25")),
            pm10=_number(data.get("pm10")),
            backlight=_number(data.get("backlight")),
            wifi_signal=_number(data.get("wi-fi")),
        )

    if kind == "breezer":
        heater_mode = data.get("heater_mode")
        heater_enabled = _flag(data.get("heater_enabled"))
        if heater_enabled is None:
            heater_enabled = heater_mode == "heat"
        heater_installed = _flag(data.get("heater_installed"))
        if heater_installed is None:
            # 4S поле не отдаёт вовсе. Наличие heater_mode или включённого
            # нагрева доказывает, что нагреватель есть, — иначе у модели
            # пропадал бы режим HEAT (issue #25 апстрима).
            heater_installed = heater_mode is not None or bool(heater_enabled)
        is_on = _flag(data.get("is_on"))
        speed = _number(data.get("speed"))
        if is_on is None:
            # Модель флаг не отдала. Считать её выключенной нельзя: тогда любая
            # команда собиралась бы из снимка со скоростью 0 и физически гасила
            # бы бризер при правке любой другой настройки.
            is_on = bool(speed)
        gate = _number(data.get("gate"))
        return TionBreezer(
            **common,
            data_valid=_flag(data.get("data_valid")),
            is_on=is_on,
            heater_installed=heater_installed,
            heater_enabled=heater_enabled,
            # Облако отдаёт speed 1 даже у выключенного бризера.
            speed=speed if is_on else 0,
            speed_m3h=_number(data.get("speed_m3h")),
            speed_limit=_number(data.get("speed_limit")),
            speed_min_set=_number(data.get("speed_min_set")),
            speed_max_set=_number(data.get("speed_max_set")),
            t_in=_number(data.get("t_in")),
            t_out=_number(data.get("t_out")),
            t_set=_number(data.get("t_set")),
            t_min=_number(raw.get("t_min")),
            t_max=_number(raw.get("t_max")),
            gate=int(gate) if gate is not None else None,
            run_seconds=_number(data.get("run_seconds")),
            filter_time_seconds=_number(data.get("filter_time_seconds")),
            filter_need_replace=_flag(data.get("filter_need_replace")),
            error_code=_text((data.get("errors") or {}).get("code")),
        )

    # Не debug: молча пропущенное устройство выглядит как «интеграция не
    # видит бризер», и разбираться приходится по переписке, а не по логу.
    _LOGGER.warning(
        "Устройство %s не опознано: тип %r, поля телеметрии %s. "
        "Сообщите об этом в issue — по этим данным модель можно поддержать",
        raw.get("name"),
        device_type,
        sorted(data),
    )
    return None


def parse_snapshot(payload: list[dict[str, Any]]) -> TionSnapshot:
    """Разобрать ответ GET /location целиком."""
    snapshot = TionSnapshot()
    for raw_location in payload:
        # Узел без guid опознать нечем: пропускаем его, но не роняем весь опрос
        # голым KeyError мимо иерархии TionError.
        if not isinstance(raw_location, dict) or not raw_location.get("guid"):
            _LOGGER.warning("Пропущена локация без guid: %s", raw_location)
            continue

        location = TionLocation.from_api(raw_location)
        snapshot.locations[location.guid] = location

        for raw_zone in raw_location.get("zones") or []:
            if not isinstance(raw_zone, dict) or not raw_zone.get("guid"):
                _LOGGER.warning("Пропущена зона без guid: %s", raw_zone)
                continue

            zone = TionZone.from_api(raw_zone)
            for raw_device in raw_zone.get("devices") or []:
                if not isinstance(raw_device, dict) or not raw_device.get("guid"):
                    _LOGGER.warning("Пропущено устройство без guid: %s", raw_device)
                    continue

                device = _parse_device(raw_device, zone, location.guid)
                if device is not None:
                    snapshot.devices[device.guid] = device
    return snapshot


class TionApiClient:
    """Клиент облака Tion. Сессию отдаёт вызывающий и он же ею владеет."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        *,
        token: str | None = None,
        token_callback: Callable[[str], Awaitable[None]] | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Создать клиента.

        token — сохранённый ранее токен, чтобы не тратить логин на каждый
        старт; token_callback вызывается, когда токен сменился.
        """
        self._session = session
        self._username = username
        self._password = password
        self._token = token
        self._token_callback = token_callback
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._auth_lock = asyncio.Lock()

    @property
    def token(self) -> str | None:
        """Текущий токен доступа."""
        return self._token

    async def async_authenticate(self, rejected: str | None = None) -> None:
        """Получить новый токен по логину и паролю.

        rejected — токен, который облако только что отвергло. Пока запрос ждал
        блокировку, соседний мог уже обновить токен; повторный логин тогда не
        нужен и вреден: он лишний раз дёргает /oauth2/token и заменяет рабочий
        токен на новый.
        """
        async with self._auth_lock:
            if rejected is not None and self._token not in (None, rejected):
                return

            payload = {
                "username": self._username,
                "password": self._password,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "password",
            }
            try:
                async with self._session.post(
                    AUTH_URL, data=payload, headers=BASE_HEADERS, timeout=self._timeout
                ) as response:
                    if response.status in (
                        HTTPStatus.BAD_REQUEST,
                        HTTPStatus.UNAUTHORIZED,
                        HTTPStatus.FORBIDDEN,
                    ):
                        raise TionAuthError("Облако Tion не приняло почту или пароль")
                    response.raise_for_status()
                    body = await response.json(content_type=None)
            except TimeoutError as err:
                raise TionConnectionError("Облако Tion не ответило вовремя") from err
            except aiohttp.ClientError as err:
                raise TionConnectionError(f"Ошибка связи с облаком Tion: {err}") from err

            try:
                token = f"{body['token_type']} {body['access_token']}"
            except (KeyError, TypeError) as err:
                raise TionAuthError("Облако Tion вернуло ответ без токена") from err

            self._token = token
            if self._token_callback is not None:
                await self._token_callback(token)

    @staticmethod
    async def _read_json(response: Any) -> Any:
        """Разобрать тело ответа, не выпуская наружу чужие исключения."""
        try:
            return await response.json(content_type=None)
        except ValueError as err:
            # Прокси на пути может отдать HTTP 200 с HTML-страницей.
            raise TionConnectionError("Облако Tion вернуло не JSON") from err

    @classmethod
    async def _describe(cls, response: Any) -> str:
        """Вытащить из тела ответа причину отказа, если она там есть."""
        try:
            body = await cls._read_json(response)
        except TionError:
            return ""
        if isinstance(body, dict):
            return str(body.get("description") or body.get("message") or "")
        return ""

    async def async_fetch(self) -> TionSnapshot:
        """Прочитать состояние всего аккаунта."""
        payload = await self._async_request("GET", LOCATION_URL)
        if not isinstance(payload, list):
            raise TionError("Облако Tion вернуло неожиданный ответ на /location")

        snapshot = parse_snapshot(payload)
        if not snapshot.devices:
            raise TionError("В аккаунте Tion нет ни одного известного устройства")
        return snapshot

    async def async_validate(self) -> TionSnapshot:
        """Проверить учётные данные живым обращением к облаку."""
        await self.async_authenticate()
        return await self.async_fetch()

    async def async_send_breezer(self, breezer: TionBreezer, **changes: Any) -> None:
        """Изменить параметры бризера."""
        await self._async_send_mode(
            f"{API_BASE}/device/{breezer.guid}/mode", breezer.mode_payload(**changes)
        )

    async def async_send_zone(
        self,
        zone: TionZone,
        *,
        mode: str | None = None,
        target_co2: float | None = None,
    ) -> None:
        """Изменить режим зоны или порог CO₂ её автоматики."""
        await self._async_send_mode(
            f"{API_BASE}/zone/{zone.guid}/mode",
            zone.mode_payload(mode=mode, target_co2=target_co2),
        )

    async def _async_send_mode(self, url: str, payload: dict[str, Any]) -> None:
        """Поставить команду в очередь облака и дождаться её выполнения."""
        body = await self._async_request("POST", url, json=payload)
        if not isinstance(body, dict) or body.get("status") != "queued":
            description = ""
            if isinstance(body, dict):
                description = body.get("description") or body.get("status") or ""
            raise TionCommandError(
                f"Облако Tion отклонило команду: {description}".strip(": ")
            )

        task_id = body.get("task_id")
        if not task_id:
            raise TionCommandError("Облако Tion не вернуло идентификатор задачи")
        await self._async_wait_for_task(str(task_id))

    async def _async_wait_for_task(self, task_id: str) -> None:
        """Дождаться, пока облако доложит о выполнении команды."""
        url = f"{API_BASE}/task/{task_id}"
        for _ in range(TASK_ATTEMPTS):
            body = await self._async_request("GET", url)
            status = body.get("status") if isinstance(body, dict) else None
            if status == "completed":
                return
            if status in TASK_FAILED_STATUSES:
                reason = ""
                if isinstance(body, dict):
                    reason = str(body.get("description") or "")
                raise TionCommandError(
                    f"Облако Tion не выполнило команду: {reason or status}"
                )
            await asyncio.sleep(TASK_POLL_INTERVAL)
        raise TionCommandError("Облако Tion не подтвердило выполнение команды")

    async def _async_request(
        self, method: str, url: str, *, json: dict[str, Any] | None = None
    ) -> Any:
        """Сходить в облако, обновив токен, если тот протух."""
        if self._token is None:
            await self.async_authenticate()

        # Вторая попытка — единственная, и только после успешного логина.
        for attempt in (1, 2):
            # Токен запоминаем: между отказом и повторным логином его мог
            # обновить соседний запрос, и второй логин был бы лишним.
            used_token = self._token or ""
            headers = {
                **BASE_HEADERS,
                "Content-Type": "application/json",
                "Authorization": used_token,
            }
            try:
                async with self._session.request(
                    method, url, json=json, headers=headers, timeout=self._timeout
                ) as response:
                    status = response.status

                    # 403 облако отдаёт на отозванный токен наравне с 401.
                    # Считать его «нет связи» нельзя: тогда повторный вход не
                    # запустится никогда, а сущности навсегда останутся
                    # недоступными.
                    if status not in (
                        HTTPStatus.UNAUTHORIZED,
                        HTTPStatus.FORBIDDEN,
                    ):
                        if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
                            raise TionConnectionError(
                                f"Облако Tion ответило {status}"
                            )
                        if status >= HTTPStatus.BAD_REQUEST:
                            # Осмысленный отказ на запрос, а не проблема сети.
                            reason = await self._describe(response)
                            raise TionCommandError(
                                f"Облако Tion отклонило запрос ({status})"
                                f"{': ' + reason if reason else ''}"
                            )
                        return await self._read_json(response)
            except TimeoutError as err:
                raise TionConnectionError("Облако Tion не ответило вовремя") from err
            except aiohttp.ClientError as err:
                raise TionConnectionError(f"Ошибка связи с облаком Tion: {err}") from err

            if attempt == 2:
                break
            await self.async_authenticate(rejected=used_token)

        raise TionAuthError("Облако Tion не приняло токен")
