"""Render README diagrams as PNG so GitHub can preview them."""

from PIL import Image, ImageDraw, ImageFont

OUT = __file__.replace("render_readme_images.py", "")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = (
        ("C:/Windows/Fonts/georgia.ttf", "C:/Windows/Fonts/georgiab.ttf"),
        ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    )
    for regular, heavy in names:
        try:
            return ImageFont.truetype(heavy if bold else regular, size)
        except OSError:
            continue
    return ImageFont.load_default()


def banner() -> None:
    img = Image.new("RGB", (1200, 280), "#14081f")
    d = ImageDraw.Draw(img)
    d.ellipse((-40, -80, 300, 160), fill="#2a1233")
    d.ellipse((900, 140, 1280, 400), fill="#102433")
    d.polygon([(0, 220), (200, 190), (400, 240), (700, 180), (1200, 200), (1200, 280), (0, 280)], fill="#1d0e2c")
    d.text((600, 58), "SILVER EUW  -  LIVE PATCH  -  ONE CLICK", fill="#f5c542", font=font(22, True), anchor="mt")
    d.text((600, 118), "Markov Kai'Sa", fill="#ff4ecd", font=font(72, True), anchor="mt")
    d.text((600, 210), "stagewise Markov item paths  -  delta over raw WR  -  Empirical Bayes", fill="#d8c7ff", font=font(20), anchor="mt")
    img.save(OUT + "banner.png", "PNG")


def formula() -> None:
    img = Image.new("RGB", (980, 220), "#1b1030")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 980, 8), fill="#3de0ff")
    d.text((40, 28), "OBJECTIVE", fill="#f5c542", font=font(18, True))
    d.text((40, 88), "U  =  (p-tilde - p_avg)  -  lambda * CI95", fill="#f4f0ff", font=font(34, True))
    d.text((40, 160), "choose the path that maximizes U after the n-floor, not raw winrate", fill="#b9a7e0", font=font(18))
    img.save(OUT + "formula-u.png", "PNG")


def pipeline() -> None:
    img = Image.new("RGB", (1100, 210), "#120818")
    d = ImageDraw.Draw(img)
    boxes = [
        (28, "#2a1050", "#c084fc", "#f5c542", "Lolalytics", "Actually-Built"),
        (220, "#10283a", "#3de0ff", "#3de0ff", "shrink", "Empirical Bayes"),
        (412, "#2a1030", "#ff4ecd", "#ff4ecd", "score", "delta then U"),
        (604, "#1a2040", "#f5c542", "#f5c542", "joint search", "top cores x late"),
    ]
    last = (814, 258, "#14201c", "#4ade80", "#4ade80", "League item set", "7 slots + late swaps")
    title = font(16, True)
    sub = font(14)
    for x, fill, stroke, title_c, t1, t2 in boxes:
        d.rounded_rectangle((x, 58, x + 150, 146), radius=14, fill=fill, outline=stroke, width=2)
        d.text((x + 75, 88), t1, fill=title_c, font=title, anchor="mm")
        d.text((x + 75, 116), t2, fill="#d8c7ff", font=sub, anchor="mm")
        d.line((x + 150, 102, x + 184, 102), fill="#3de0ff", width=3)
    x, w, fill, stroke, title_c, t1, t2 = last
    d.rounded_rectangle((x, 58, x + w, 146), radius=14, fill=fill, outline=stroke, width=2)
    d.text((x + w / 2, 88), t1, fill=title_c, font=title, anchor="mm")
    d.text((x + w / 2, 116), t2, fill="#d8c7ff", font=sub, anchor="mm")
    img.save(OUT + "pipeline.png", "PNG")


if __name__ == "__main__":
    banner()
    formula()
    pipeline()
    print("wrote PNG diagrams")
