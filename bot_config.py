from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from app import audio_quality, positive_int


SIZE_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt]?i?b?)?\s*$", re.IGNORECASE)
SIZE_MULTIPLIERS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gib": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
    "tib": 1024**4,
}
VALID_MEDIA = {"audio", "video"}
VALID_AUDIO_FORMATS = {"mp3", "m4a", "opus", "wav", "flac"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BotConfig:
    env_path: Path
    token: str
    allowed_chat_ids: set[int]
    admin_chat_ids: set[int]
    data_dir: Path
    download_dir: Path
    max_storage_bytes: int
    weekly_user_limit_bytes: int
    telegram_part_size_bytes: int
    max_upload_parts: int
    default_media: str
    default_video_resolution: int
    default_audio_quality: str
    default_audio_format: str
    error_history_limit: int


def parse_size(value: str) -> int:
    match = SIZE_PATTERN.match(value or "")
    if not match:
        raise ConfigError(f"Invalid size value: {value!r}")

    number = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    if suffix not in SIZE_MULTIPLIERS:
        raise ConfigError(f"Invalid size suffix in value: {value!r}")

    parsed = int(number * SIZE_MULTIPLIERS[suffix])
    if parsed < 0:
        raise ConfigError("Size values must be non-negative")
    return parsed


def parse_chat_ids(value: str) -> set[int]:
    if not value:
        return set()

    chat_ids: set[int] = set()
    for part in re.split(r"[\s,;]+", value.strip()):
        if not part:
            continue
        try:
            chat_ids.add(int(part))
        except ValueError as exc:
            raise ConfigError(f"Invalid chat id: {part!r}") from exc
    return chat_ids


def _read_positive_int(name: str, default: str) -> int:
    try:
        return positive_int(os.getenv(name, default))
    except Exception as exc:
        raise ConfigError(f"{name} must be a positive integer") from exc


def _read_audio_quality(name: str, default: str) -> str:
    try:
        return audio_quality(os.getenv(name, default))
    except Exception as exc:
        raise ConfigError(f"{name} must be 0-10 or a bitrate like 192") from exc


def load_config(env_path: str | Path = ".env") -> BotConfig:
    resolved_env_path = Path(env_path).expanduser().resolve()
    load_dotenv(resolved_env_path, override=True)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("TELEGRAM_BOT_TOKEN is required")

    allowed_chat_ids = parse_chat_ids(os.getenv("ALLOWED_CHAT_IDS", ""))
    admin_chat_ids = parse_chat_ids(os.getenv("ADMIN_CHAT_IDS", ""))
    if not allowed_chat_ids:
        raise ConfigError("ALLOWED_CHAT_IDS must contain at least one chat id")
    if not admin_chat_ids:
        raise ConfigError("ADMIN_CHAT_IDS must contain at least one admin chat id")

    default_media = os.getenv("DEFAULT_MEDIA", "audio").strip().lower()
    if default_media not in VALID_MEDIA:
        raise ConfigError("DEFAULT_MEDIA must be audio or video")

    default_audio_format = os.getenv("DEFAULT_AUDIO_FORMAT", "mp3").strip().lower()
    if default_audio_format not in VALID_AUDIO_FORMATS:
        raise ConfigError("DEFAULT_AUDIO_FORMAT must be mp3, m4a, opus, wav, or flac")

    data_dir = Path(os.getenv("BOT_DATA_DIR", "data")).expanduser().resolve()
    download_dir = Path(os.getenv("DOWNLOAD_DIR", "downloads")).expanduser().resolve()
    telegram_part_size_bytes = parse_size(os.getenv("TELEGRAM_PART_SIZE_BYTES", "50MB"))
    if telegram_part_size_bytes <= 0:
        raise ConfigError("TELEGRAM_PART_SIZE_BYTES must be greater than zero")

    return BotConfig(
        env_path=resolved_env_path,
        token=token,
        allowed_chat_ids=allowed_chat_ids | admin_chat_ids,
        admin_chat_ids=admin_chat_ids,
        data_dir=data_dir,
        download_dir=download_dir,
        max_storage_bytes=parse_size(os.getenv("MAX_STORAGE_BYTES", "1GB")),
        weekly_user_limit_bytes=parse_size(os.getenv("WEEKLY_USER_LIMIT_BYTES", "1GB")),
        telegram_part_size_bytes=min(telegram_part_size_bytes, parse_size("49MB")),
        max_upload_parts=_read_positive_int("MAX_UPLOAD_PARTS", "3"),
        default_media=default_media,
        default_video_resolution=_read_positive_int("DEFAULT_VIDEO_RESOLUTION", "720"),
        default_audio_quality=_read_audio_quality("DEFAULT_AUDIO_QUALITY", "96"),
        default_audio_format=default_audio_format,
        error_history_limit=_read_positive_int("ERROR_HISTORY_LIMIT", "100"),
    )
