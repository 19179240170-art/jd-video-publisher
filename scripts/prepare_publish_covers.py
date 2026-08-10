from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from phase1.media import _resolve_binary


MIN_BYTES = 204_800
MAX_BYTES = 5 * 1024 * 1024


def suitable(path: Path) -> bool:
    return path.is_file() and MIN_BYTES <= path.stat().st_size <= MAX_BYTES


def main() -> int:
    batch_path = ROOT / "output" / "phase2" / "approved_batch.json"
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    task_ids = [str(item["task_id"]) for item in batch["records"]]
    output_dir = ROOT / "output" / "phase2" / "covers"
    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = _resolve_binary(None, "ffmpeg")
    covers: dict[str, str] = {}
    generated = 0

    for task_id in task_ids:
        result_path = (
            ROOT / "output" / "phase1" / "tasks" / task_id / "result.json"
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        existing = [
            Path(value)
            for value in result.get("frames", [])
            if suitable(Path(value))
        ]
        if existing:
            covers[task_id] = str(existing[0])
            continue

        video_path = Path(result["video_path"])
        duration = float(
            result.get("video_metadata", {}).get("duration_seconds") or 1
        )
        timestamp = max(0.1, min(duration * 0.18, duration - 0.1))
        cover_path = output_dir / f"{task_id}.jpg"
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            "scale='min(1080,iw)':-2",
            "-q:v",
            "1",
            str(cover_path),
        ]
        subprocess.run(command, check=True, capture_output=True)
        if not suitable(cover_path):
            png_path = output_dir / f"{task_id}.png"
            png_command = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                "scale='min(1080,iw)':-2",
                str(png_path),
            ]
            subprocess.run(png_command, check=True, capture_output=True)
            cover_path = png_path
        if not suitable(cover_path):
            raise RuntimeError(
                f"{task_id}生成的封面大小不合规："
                f"{cover_path.stat().st_size}字节"
            )
        covers[task_id] = str(cover_path)
        generated += 1

    manifest_path = ROOT / "output" / "phase2" / "cover_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "approved_tasks": len(task_ids),
                "generated": generated,
                "covers": covers,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "approved_tasks": len(task_ids),
                "covers_ready": len(covers),
                "generated": generated,
                "manifest": str(manifest_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
