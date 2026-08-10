from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv"}


def discover_videos(root: Path) -> tuple[list[Path], list[Path]]:
    ready: list[Path] = []
    skipped: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in VIDEO_EXTENSIONS and path.stat().st_size > 0:
            ready.append(path)
        elif path.suffix.lower() == ".nas_pro_downloading" or path.stat().st_size == 0:
            skipped.append(path)
    return ready, skipped


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_binary(explicit: str | None, name: str) -> str:
    if explicit:
        candidate = Path(explicit)
        if candidate.exists():
            return str(candidate)
        resolved = shutil.which(explicit)
        if resolved:
            return resolved
    resolved = shutil.which(name)
    if resolved:
        return resolved
    winget_root = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    candidates = sorted(winget_root.glob(f"Gyan.FFmpeg*/*/bin/{name}.exe"), reverse=True)
    if candidates:
        return str(candidates[0])
    raise FileNotFoundError(f"找不到 {name}，请先安装 FFmpeg")


def probe_video(path: Path, ffprobe: str | None = None) -> dict:
    binary = _resolve_binary(ffprobe, "ffprobe")
    command = [
        binary,
        "-v", "error",
        "-show_entries", "format=duration:stream=index,codec_type,width,height,avg_frame_rate",
        "-of", "json",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    payload = json.loads(result.stdout)
    duration = float(payload.get("format", {}).get("duration") or 0)
    video_stream = next((stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"), {})
    return {
        "duration_seconds": round(duration, 3),
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "avg_frame_rate": video_stream.get("avg_frame_rate", ""),
    }


def extract_frames(
    video_path: Path,
    output_dir: Path,
    count: int = 10,
    ffmpeg: str | None = None,
    max_width: int = 960,
) -> tuple[list[Path], dict]:
    metadata = probe_video(video_path)
    duration = metadata["duration_seconds"]
    if duration <= 0:
        raise ValueError(f"无法读取视频时长：{video_path}")
    binary = _resolve_binary(ffmpeg, "ffmpeg")
    output_dir.mkdir(parents=True, exist_ok=True)

    count = max(3, min(int(count), 20))
    fractions = [(index + 0.5) / count for index in range(count)]
    timestamps = [min(max(duration * fraction, 0.05), max(0.05, duration - 0.05)) for fraction in fractions]
    frames: list[Path] = []
    for index, timestamp in enumerate(timestamps, start=1):
        output_path = output_dir / f"frame-{index:02d}.jpg"
        command = [
            binary,
            "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{timestamp:.3f}",
            "-i", str(video_path),
            "-frames:v", "1",
            "-vf", f"scale='min({max_width},iw)':-2",
            "-q:v", "4",
            str(output_path),
        ]
        subprocess.run(command, capture_output=True, check=True)
        if output_path.exists() and output_path.stat().st_size:
            frames.append(output_path)

    cover_candidates = sorted(video_path.parent.glob("*封面*.jpg"))
    if cover_candidates:
        cover_path = output_dir / "cover.jpg"
        shutil.copy2(cover_candidates[0], cover_path)
        frames.insert(0, cover_path)
    return frames, metadata
