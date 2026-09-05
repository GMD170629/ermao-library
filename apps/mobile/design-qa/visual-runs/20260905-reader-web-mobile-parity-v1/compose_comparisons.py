from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
ANDROID = ROOT / "iteration-11" / "android" / "reader-controls"
WEB = ROOT / "iteration-04" / "web"
OUTPUT = ROOT / "final" / "comparison"
PANEL_SIZE = (411, 914)
HEADER_HEIGHT = 58
GAP = 16
BACKGROUND = "#E9E4DC"
LABEL = "#26211D"

FORMATS = {
    "epub": {
        "label": "EPUB",
        "android": {
            "controls": "epub-controls.png",
            "toc": "epub-contents.png",
            "notes": "epub-notes.png",
            "appearance": "epub-appearance.png",
            "settings": "epub-settings.png",
        },
    },
    "comic": {
        "label": "漫画",
        "android": {
            "controls": "comic-controls-warm.png",
            "toc": "comic-contents.png",
            "notes": "comic-notes.png",
            "appearance": "comic-appearance.png",
            "settings": "comic-settings.png",
        },
    },
    "pdf": {
        "label": "PDF",
        "android": {
            "controls": "pdf-controls.png",
            "toc": "pdf-contents.png",
            "notes": "pdf-notes.png",
            "appearance": "pdf-appearance.png",
            "settings": "pdf-settings.png",
        },
    },
}

STATES = {
    "controls": ("00-controls.png", "控制栏"),
    "toc": ("01-toc.png", "目录"),
    "notes": ("02-notes.png", "笔记"),
    "appearance": ("03-appearance.png", "外观"),
    "settings": ("04-settings.png", "设置"),
}


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)


def cover(image: Image.Image) -> Image.Image:
    target_ratio = PANEL_SIZE[0] / PANEL_SIZE[1]
    source_ratio = image.width / image.height
    if source_ratio > target_ratio:
        crop_width = round(image.height * target_ratio)
        left = (image.width - crop_width) // 2
        image = image.crop((left, 0, left + crop_width, image.height))
    elif source_ratio < target_ratio:
        crop_height = round(image.width / target_ratio)
        top = (image.height - crop_height) // 2
        image = image.crop((0, top, image.width, top + crop_height))
    return image.resize(PANEL_SIZE, Image.Resampling.LANCZOS)


def centered(draw: ImageDraw.ImageDraw, value: str, center_x: int, y: int, text_font: ImageFont.FreeTypeFont) -> None:
    box = draw.textbbox((0, 0), value, font=text_font)
    draw.text((center_x - (box[2] - box[0]) / 2, y), value, fill=LABEL, font=text_font)


def comparison(android_path: Path, web_path: Path, title: str) -> Image.Image:
    width = PANEL_SIZE[0] * 2 + GAP
    canvas = Image.new("RGB", (width, HEADER_HEIGHT + PANEL_SIZE[1]), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    title_font = font(18)
    detail_font = font(12)
    centered(draw, f"Android · {title}", PANEL_SIZE[0] // 2, 7, title_font)
    centered(draw, "1440×3200 → 411×914", PANEL_SIZE[0] // 2, 33, detail_font)
    web_center = PANEL_SIZE[0] + GAP + PANEL_SIZE[0] // 2
    centered(draw, f"Web 手机端 · {title}", web_center, 7, title_font)
    centered(draw, "411×914", web_center, 33, detail_font)
    with Image.open(android_path).convert("RGB") as image:
        canvas.paste(cover(image), (0, HEADER_HEIGHT))
    with Image.open(web_path).convert("RGB") as image:
        canvas.paste(cover(image), (PANEL_SIZE[0] + GAP, HEADER_HEIGHT))
    return canvas


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for format_name, format_definition in FORMATS.items():
        format_output = OUTPUT / format_name
        format_output.mkdir(parents=True, exist_ok=True)
        comparisons: list[Image.Image] = []
        for state_name, (web_name, state_label) in STATES.items():
            pair = comparison(
                ANDROID / format_definition["android"][state_name],
                WEB / format_name / web_name,
                f'{format_definition["label"]} · {state_label}',
            )
            pair.save(format_output / f"{state_name}-1to1.png", optimize=True)
            comparisons.append(pair)
        overview_gap = 18
        overview = Image.new(
            "RGB",
            (
                comparisons[0].width,
                sum(pair.height for pair in comparisons) + overview_gap * (len(comparisons) - 1),
            ),
            "#D8D2C9",
        )
        y = 0
        for pair in comparisons:
            overview.paste(pair, (0, y))
            y += pair.height + overview_gap
        overview.save(OUTPUT / f"{format_name}-reader-controls-all-1to1.png", optimize=True)


if __name__ == "__main__":
    main()
