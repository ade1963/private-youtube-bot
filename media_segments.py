from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class SegmentError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaSegment:
    path: Path
    index: int
    total: int

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size


def segment_count(size_bytes: int, max_segment_bytes: int) -> int:
    if max_segment_bytes <= 0:
        raise SegmentError("max segment size must be greater than zero")
    if size_bytes <= 0:
        return 1
    return math.ceil(size_bytes / max_segment_bytes)


def require_ffmpeg_for_segments() -> None:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    raise SegmentError("ffmpeg and ffprobe are required for playable media splitting")


def estimate_segment_time_seconds(
    source: Path,
    max_segment_bytes: int,
    safety_factor: float = 0.92,
) -> int:
    duration = probe_duration_seconds(source)
    if duration <= 0:
        raise SegmentError("could not detect media duration")
    bytes_per_second = source.stat().st_size / duration
    seconds = int((max_segment_bytes * safety_factor) / max(bytes_per_second, 1))
    return max(10, seconds)


def probe_duration_seconds(source: Path) -> float:
    require_ffmpeg_for_segments()
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(source),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SegmentError(result.stderr.strip() or "ffprobe failed")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise SegmentError("ffprobe returned invalid duration") from exc


def split_playable_media(
    source: Path,
    output_dir: Path,
    media: str,
    max_segment_bytes: int,
) -> list[MediaSegment]:
    require_ffmpeg_for_segments()
    output_dir.mkdir(parents=True, exist_ok=True)
    clear_directory(output_dir)

    extension = source.suffix.lower() or (".mp4" if media == "video" else ".mp3")
    segment_seconds = estimate_segment_time_seconds(source, max_segment_bytes)
    pattern = output_dir / f"segment-%03d{extension}"

    if media == "video":
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-map",
            "0",
            "-c",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            str(segment_seconds),
            "-reset_timestamps",
            "1",
            str(pattern),
        ]
    else:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-c",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            str(segment_seconds),
            "-reset_timestamps",
            "1",
            str(pattern),
        ]

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SegmentError(result.stderr.strip() or "ffmpeg segmenting failed")

    paths = sorted(output_dir.glob(f"segment-*{extension}"))
    if not paths:
        raise SegmentError("ffmpeg produced no playable segments")

    oversized = [path for path in paths if path.stat().st_size > max_segment_bytes]
    if oversized:
        # Retry once with a smaller time window; VBR and keyframe placement can make
        # copy-mode segments uneven, especially for video.
        clear_directory(output_dir)
        retry_seconds = max(5, int(segment_seconds * 0.65))
        command[command.index("-segment_time") + 1] = str(retry_seconds)
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise SegmentError(result.stderr.strip() or "ffmpeg segmenting failed")
        paths = sorted(output_dir.glob(f"segment-*{extension}"))
        oversized = [path for path in paths if path.stat().st_size > max_segment_bytes]
        if oversized:
            largest = max(path.stat().st_size for path in oversized)
            raise SegmentError(
                f"could not make playable segments below limit; largest is {largest} bytes"
            )

    total = len(paths)
    return [
        MediaSegment(path=path, index=index, total=total)
        for index, path in enumerate(paths, start=1)
    ]


def clear_directory(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_file():
            child.unlink(missing_ok=True)
