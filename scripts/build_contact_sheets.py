from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = ROOT / "output" / "phase1" / "local_chatgpt_tasks.json"
SHEETS_DIR = ROOT / "output" / "phase1" / "contact_sheets"
OVERVIEWS_DIR = ROOT / "output" / "phase1" / "contact_overviews"
MANIFEST_PATH = ROOT / "output" / "phase1" / "contact_sheet_manifest.json"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
    ):
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _fit(path: Path, size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)


def _sheet(task: dict) -> Image.Image:
    width, height = 1200, 1040
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    title_font = _font(34)
    label_font = _font(23)
    small_font = _font(18)
    draw.text((24, 18), f"{task['task_id']}  {task['video_name']}", fill="#111111", font=title_font)
    draw.text((24, 64), f"文件夹：{task['parent_folder']}", fill="#4b5563", font=label_font)

    cell_w, cell_h = 288, 286
    frame_h = 244
    left, top = 18, 105
    for index, value in enumerate(task["frames"][:12]):
        row, column = divmod(index, 4)
        x = left + column * 296
        y = top + row * 300
        image = _fit(Path(value), (cell_w, frame_h))
        canvas.paste(image, (x, y))
        draw.rectangle((x, y, x + cell_w, y + frame_h), outline="#d1d5db", width=2)
        draw.text((x + 4, y + frame_h + 5), f"画面 {index + 1}", fill="#374151", font=small_font)
    return canvas


def _overview(items: list[dict], index: int) -> Path:
    width, height = 1800, 1640
    canvas = Image.new("RGB", (width, height), "#e5e7eb")
    draw = ImageDraw.Draw(canvas)
    draw.text((24, 12), f"本地 ChatGPT 抽帧复核批次 {index:02d}", fill="#111827", font=_font(32))
    for position, item in enumerate(items):
        row, column = divmod(position, 2)
        x = 20 + column * 890
        y = 62 + row * 780
        with Image.open(item["contact_sheet"]) as source:
            sheet = source.convert("RGB")
            sheet.thumbnail((860, 740), Image.Resampling.LANCZOS)
            canvas.paste(sheet, (x, y))
            draw.rectangle((x, y, x + sheet.width, y + sheet.height), outline="#9ca3af", width=2)
    path = OVERVIEWS_DIR / f"batch-{index:02d}.jpg"
    canvas.save(path, quality=90, optimize=True)
    return path


def main() -> int:
    payload = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    SHEETS_DIR.mkdir(parents=True, exist_ok=True)
    OVERVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    for task in payload["tasks"]:
        path = SHEETS_DIR / f"{task['task_id']}.jpg"
        _sheet(task).save(path, quality=91, optimize=True)
        manifest.append(
            {
                "task_id": task["task_id"],
                "video_name": task["video_name"],
                "parent_folder": task["parent_folder"],
                "contact_sheet": str(path),
            }
        )
    overview_paths = []
    for start in range(0, len(manifest), 4):
        overview_paths.append(str(_overview(manifest[start : start + 4], start // 4 + 1)))
    MANIFEST_PATH.write_text(
        json.dumps(
            {"items": manifest, "overviews": overview_paths},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "contact_sheets": len(manifest),
                "overview_batches": len(overview_paths),
                "manifest": str(MANIFEST_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
