from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any

from app import QuietLogger, build_video_format
from bot_config import BotConfig
from media_settings import MediaSettings
from state_store import ArtifactRecord, now_iso
from url_tools import cache_identity


SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._ -]+")


class DownloadFailure(RuntimeError):
    pass


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    raise DownloadFailure(
        "ffmpeg and ffprobe are required. Install FFmpeg and add both binaries to PATH."
    )


def make_cache_key(cleaned_url: str, settings: MediaSettings) -> str:
    key_source = f"{cache_identity(cleaned_url)}|{settings.cache_profile()}"
    return hashlib.sha256(key_source.encode("utf-8")).hexdigest()[:32]


def safe_filename(value: str, fallback: str = "download") -> str:
    cleaned = SAFE_FILENAME_PATTERN.sub("_", value).strip(" ._")
    return cleaned[:180] or fallback


def artifact_filename(record: ArtifactRecord) -> str:
    suffix = record.path.suffix or ".bin"
    return f"{safe_filename(record.title, record.key)}{suffix}"


def _yt_dlp_options(config: BotConfig, settings: MediaSettings, key: str) -> dict[str, Any]:
    options: dict[str, Any] = {
        "outtmpl": str(config.download_dir / f"{key}.%(ext)s"),
        "noplaylist": True,
        "logger": QuietLogger(),
        "progress_hooks": [],
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
    }

    if settings.media == "audio":
        options.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": settings.audio_format,
                        "preferredquality": settings.audio_quality,
                    }
                ],
            }
        )
        return options

    options.update(
        {
            "format": build_video_format(settings.video_resolution),
            "merge_output_format": "mp4",
        }
    )
    return options


def _find_downloaded_file(download_dir: Path, key: str, settings: MediaSettings) -> Path:
    expected_suffix = f".{settings.audio_format}" if settings.media == "audio" else ".mp4"
    exact = download_dir / f"{key}{expected_suffix}"
    if exact.exists():
        return exact

    candidates = [
        path
        for path in download_dir.glob(f"{key}.*")
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
    ]
    if not candidates:
        raise DownloadFailure("yt-dlp finished but no output file was found")
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def existing_artifact_file(config: BotConfig, key: str, settings: MediaSettings) -> Path | None:
    suffix = f".{settings.audio_format}" if settings.media == "audio" else ".mp4"
    path = config.download_dir / f"{key}{suffix}"
    return path if path.exists() else None


def download_artifact(
    cleaned_url: str,
    settings: MediaSettings,
    config: BotConfig,
) -> ArtifactRecord:
    require_ffmpeg()
    config.download_dir.mkdir(parents=True, exist_ok=True)
    key = make_cache_key(cleaned_url, settings)

    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ModuleNotFoundError as exc:
        raise DownloadFailure(
            "yt-dlp is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    options = _yt_dlp_options(config, settings, key)
    try:
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(cleaned_url, download=True)
    except DownloadError as exc:
        raise DownloadFailure(str(exc)) from exc

    output_path = _find_downloaded_file(config.download_dir, key, settings)
    title = str(info.get("title") or key) if isinstance(info, dict) else key
    created_at = now_iso()
    return ArtifactRecord(
        key=key,
        path=output_path.resolve(),
        title=title,
        size_bytes=output_path.stat().st_size,
        media=settings.media,
        created_at=created_at,
        last_accessed_at=created_at,
        url=cleaned_url,
        profile=settings.cache_profile(),
    )
