"""Render LEGO-like block diagrams for the GitHub README. Rectangles only."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent

CREAM = (246, 241, 231)
SAND = (217, 211, 199)
INK = (26, 26, 26)
CORAL = (232, 90, 60)
CORAL_DK = (176, 58, 38)
TEAL = (44, 74, 74)
WHITE = (255, 252, 246)


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = (
        ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeui.ttf"),
        ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"),
    )
    for heavy, regular in names:
        try:
            return ImageFont.truetype(heavy if bold else regular, size)
        except OSError:
            continue
    return ImageFont.load_default()


def brick(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, color: tuple[int, int, int], studs: int | None = None) -> None:
    draw.rectangle((x, y, x + w - 1, y + h - 1), fill=color)
    if studs is None:
        studs = max(1, w // 16)
    gap = w // studs
    stud_w = max(4, gap // 2)
    stud_h = max(3, h // 7)
    for i in range(studs):
        sx = x + (gap - stud_w) // 2 + i * gap
        if color == CORAL:
            stud = CORAL_DK
        elif color == INK:
            stud = (72, 72, 72)
        else:
            stud = INK
        draw.rectangle((sx, y + 2, sx + stud_w - 1, y + 2 + stud_h), fill=stud)


def hero() -> None:
    img = Image.new("RGB", (960, 420), CREAM)
    d = ImageDraw.Draw(img)
    # ground rail
    d.rectangle((40, 368, 920, 384), fill=SAND)
    d.rectangle((40, 388, 280, 404), fill=CORAL)
    d.rectangle((296, 388, 520, 404), fill=INK)
    d.rectangle((536, 388, 920, 404), fill=SAND)

    # 7-slot buy path as bricks
    slot_w, slot_h = 72, 40
    start_x, start_y = 64, 300
    colors = [CORAL, INK, CORAL, CORAL, TEAL, TEAL, INK]
    for i, color in enumerate(colors):
        brick(d, start_x + i * (slot_w + 12), start_y, slot_w, slot_h, color, studs=2)

    # stacked monogram tower: block M
    ox, oy = 96, 56
    u = 28
    # left pillar
    brick(d, ox, oy, u * 2, u * 6, CORAL, 2)
    # right pillar
    brick(d, ox + u * 6, oy, u * 2, u * 6, CORAL, 2)
    # V join
    brick(d, ox + u * 2, oy + u * 2, u * 2, u * 2, CORAL_DK, 2)
    brick(d, ox + u * 4, oy + u * 2, u * 2, u * 2, CORAL_DK, 2)
    brick(d, ox + u * 3, oy + u * 4, u * 2, u * 2, INK, 1)

    # item stack / decision chain on the right
    rx = 520
    brick(d, rx, 56, 160, 48, INK, 4)
    brick(d, rx + 176, 56, 160, 48, CORAL, 4)
    brick(d, rx + 80, 124, 176, 48, TEAL, 4)
    brick(d, rx + 40, 192, 256, 48, CORAL_DK, 5)
    # connector studs
    d.rectangle((rx + 152, 104, rx + 168, 124), fill=SAND)
    d.rectangle((rx + 152, 172, rx + 168, 192), fill=SAND)

    img.save(OUT / "hero.png")


def icon(name: str, cells: list[tuple[int, int, int, int, tuple[int, int, int]]]) -> None:
    img = Image.new("RGB", (64, 64), CREAM)
    d = ImageDraw.Draw(img)
    for x, y, w, h, color in cells:
        d.rectangle((x, y, x + w - 1, y + h - 1), fill=color)
    img.save(OUT / f"icon-{name}.png")


def icons() -> None:
    icon(
        "live",
        [
            (8, 40, 48, 16, CORAL),
            (16, 24, 32, 12, CORAL_DK),
            (24, 8, 16, 12, INK),
        ],
    )
    icon(
        "rank",
        [
            (8, 36, 16, 20, SAND),
            (24, 24, 16, 32, CORAL),
            (40, 12, 16, 44, INK),
        ],
    )
    icon(
        "utility",
        [
            (12, 12, 12, 40, CORAL),
            (40, 12, 12, 40, CORAL),
            (16, 40, 32, 12, CORAL_DK),
        ],
    )
    icon(
        "slots",
        [
            (6, 24, 6, 16, CORAL),
            (14, 24, 6, 16, INK),
            (22, 24, 6, 16, CORAL),
            (30, 24, 6, 16, CORAL),
            (38, 24, 6, 16, TEAL),
            (46, 24, 6, 16, TEAL),
            (54, 24, 6, 16, INK),
        ],
    )
    icon(
        "check",
        [
            (12, 28, 12, 16, CORAL),
            (24, 36, 28, 12, CORAL_DK),
            (40, 16, 12, 24, INK),
        ],
    )
    icon(
        "prior",
        [
            (10, 14, 44, 16, INK),
            (18, 34, 28, 16, CORAL),
        ],
    )


def architecture() -> None:
    img = Image.new("RGB", (960, 280), CREAM)
    d = ImageDraw.Draw(img)
    boxes = [
        (40, 96, 160, 72, INK, "YOU"),
        (248, 96, 176, 72, CORAL, "LOLALYTICS"),
        (472, 96, 160, 72, TEAL, "SCORE U"),
        (680, 96, 240, 72, CORAL_DK, "ITEM SET"),
    ]
    label = font(16, True)
    for x, y, w, h, color, text in boxes:
        brick(d, x, y, w, h, color, studs=max(2, w // 40))
        d.text((x + w // 2, y + h // 2 + 6), text, fill=WHITE, font=label, anchor="mm")
    for x in (200, 424, 632):
        d.rectangle((x, 126, x + 48, 138), fill=SAND)
    img.save(OUT / "architecture.png")


def formula() -> None:
    img = Image.new("RGB", (960, 160), CREAM)
    d = ImageDraw.Draw(img)
    brick(d, 24, 36, 912, 88, INK, studs=12)
    d.text((480, 80), "U  =  (p-tilde - p_avg)  -  lambda * CI95", fill=WHITE, font=font(26, True), anchor="mm")
    img.save(OUT / "formula-u.png")


if __name__ == "__main__":
    hero()
    icons()
    architecture()
    formula()
    print("wrote block assets")
