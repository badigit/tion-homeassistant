"""Собрать значок интеграции из официального знака Tion.

Практика Home Assistant — брать фирменный знак вендора как есть: правила
brands прямо говорят, что изображения служат только для опознания продукта и
не означают одобрения. Видоизменять знак не нужно и вредно: получилось бы
похожее до смешения производное вместо честной ссылки на оригинал.

Источник: https://cdn-server.tiondev.ru/img/about/logo.webp — квадрат 300x300,
знак «TION.» на фирменном градиенте, без пустых полей по краям.

icon@2x.png не выпускаем: официального изображения крупнее 300 пикселей Tion
не публикует (favicon.png на tion.ru — синий кружок-заглушка, favicon.ico
магикэйра — одноцветный силуэт), а растянуть 300 до 512 значило бы выдать за
hDPI-версию картинку без единой лишней детали. Home Assistant в этом случае
обходится одним icon.png.

Запуск: uv run python scripts/make_brand.py
"""

from __future__ import annotations

import io
from pathlib import Path
import urllib.request

from PIL import Image

SOURCE_URL = "https://cdn-server.tiondev.ru/img/about/logo.webp"
OUT_DIR = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "tion_magicair"
    / "brand"
)
ICON_SIZE = 256


def _fetch(url: str) -> bytes:
    """Скачать исходное изображение."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main() -> None:
    """Сохранить icon.png."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    source = Image.open(io.BytesIO(_fetch(SOURCE_URL))).convert("RGBA")
    if source.width != source.height:
        raise SystemExit(f"Ожидался квадрат, получено {source.size}")

    icon = source.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
    path = OUT_DIR / "icon.png"
    icon.save(path, format="PNG", optimize=True)
    print(f"{path.name}: {ICON_SIZE}x{ICON_SIZE}, {path.stat().st_size} байт")
    print(f"источник: {source.size[0]}x{source.size[1]} из {SOURCE_URL}")


if __name__ == "__main__":
    main()
