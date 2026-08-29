"""Нарисовать иконку интеграции для custom_components/tion_magicair/brand/.

Знак собственный и нейтральный: мотив воздушного потока, без товарного знака
Tion и без элементов фирменного стиля Home Assistant — последнее запрещено
правилами brands, первое просто не наше.

Требования brands: PNG, квадрат 1:1, 256x256 и 512x512, минимум пустого поля
по краям. Рисуем с четырёхкратным разрешением и уменьшаем — так края выходят
гладкими без сглаживания вручную.

Запуск: uv run python scripts/make_brand.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "tion_magicair" / "brand"

SIZE = 512
SUPERSAMPLE = 4

BACKGROUND = (14, 92, 122, 255)  # глубокий сине-зелёный, читается на любом фоне
STROKE = (255, 255, 255, 255)


def _draw(canvas: int) -> Image.Image:
    """Отрисовать знак на холсте заданного размера."""
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Скруглённый квадрат во весь холст: пустого поля по краям нет.
    radius = int(canvas * 0.22)
    draw.rounded_rectangle((0, 0, canvas - 1, canvas - 1), radius=radius, fill=BACKGROUND)

    width = round(canvas * 0.072)
    half = width / 2
    left = canvas * 0.17
    curl_r = canvas * 0.105

    def cap(x: float, y: float) -> None:
        """Круглый торец линии."""
        draw.ellipse((x - half, y - half, x + half, y + half), fill=STROKE)

    def stroke(y: float, end_x: float) -> None:
        """Горизонтальная линия потока с круглыми торцами."""
        draw.line((left, y, end_x, y), fill=STROKE, width=width)
        cap(left, y)
        cap(end_x, y)

    # Верхняя линия уходит завитком вверх, нижняя — вниз, средняя самая длинная.
    # Читается как поток воздуха слева направо.
    top_y, mid_y, bottom_y = canvas * 0.32, canvas * 0.50, canvas * 0.68
    top_x, bottom_x = canvas * 0.68, canvas * 0.60

    stroke(mid_y, canvas * 0.83)

    # Завиток вверх: линия приходит в нижнюю точку окружности (90°) и обходит
    # её по часовой стрелке, оставляя разрыв справа.
    stroke(top_y, top_x)
    box = (top_x - curl_r, top_y - 2 * curl_r, top_x + curl_r, top_y)
    draw.arc(box, start=90, end=350, fill=STROKE, width=width)

    # Завиток вниз: вход в верхнюю точку окружности (270°).
    stroke(bottom_y, bottom_x)
    box = (bottom_x - curl_r, bottom_y, bottom_x + curl_r, bottom_y + 2 * curl_r)
    draw.arc(box, start=270, end=530, fill=STROKE, width=width)

    return image


def main() -> None:
    """Сохранить icon.png и icon@2x.png."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    big = _draw(SIZE * SUPERSAMPLE)
    for name, size in (("icon@2x.png", 512), ("icon.png", 256)):
        image = big.resize((size, size), Image.LANCZOS)
        path = OUT_DIR / name
        image.save(path, format="PNG", optimize=True)
        print(f"{path.name}: {size}x{size}, {path.stat().st_size} байт")


if __name__ == "__main__":
    main()
