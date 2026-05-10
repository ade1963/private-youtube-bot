from __future__ import annotations

from dataclasses import asdict, dataclass

from app import audio_quality, positive_int
from bot_config import BotConfig, VALID_AUDIO_FORMATS, VALID_MEDIA


@dataclass(frozen=True)
class MediaSettings:
    media: str
    video_resolution: int
    audio_quality: str
    audio_format: str

    @classmethod
    def from_config(cls, config: BotConfig) -> "MediaSettings":
        return cls(
            media=config.default_media,
            video_resolution=config.default_video_resolution,
            audio_quality=config.default_audio_quality,
            audio_format=config.default_audio_format,
        )

    @classmethod
    def from_dict(cls, values: dict, fallback: "MediaSettings") -> "MediaSettings":
        return cls(
            media=str(values.get("media", fallback.media)),
            video_resolution=int(values.get("video_resolution", fallback.video_resolution)),
            audio_quality=str(values.get("audio_quality", fallback.audio_quality)),
            audio_format=str(values.get("audio_format", fallback.audio_format)),
        ).validated()

    def validated(self) -> "MediaSettings":
        if self.media not in VALID_MEDIA:
            raise ValueError("media must be audio or video")
        if self.audio_format not in VALID_AUDIO_FORMATS:
            raise ValueError("audio_format must be mp3, m4a, opus, wav, or flac")
        positive_int(str(self.video_resolution))
        audio_quality(self.audio_quality)
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    def update(self, name: str, value: str) -> "MediaSettings":
        normalized_name = name.strip().lower().replace("-", "_")
        normalized_value = value.strip().lower()

        if normalized_name == "media":
            if normalized_value not in VALID_MEDIA:
                raise ValueError("media must be audio or video")
            return MediaSettings(
                media=normalized_value,
                video_resolution=self.video_resolution,
                audio_quality=self.audio_quality,
                audio_format=self.audio_format,
            )

        if normalized_name in {"resolution", "video_resolution"}:
            return MediaSettings(
                media=self.media,
                video_resolution=positive_int(normalized_value),
                audio_quality=self.audio_quality,
                audio_format=self.audio_format,
            )

        if normalized_name in {"audio_quality", "quality"}:
            return MediaSettings(
                media=self.media,
                video_resolution=self.video_resolution,
                audio_quality=audio_quality(normalized_value),
                audio_format=self.audio_format,
            )

        if normalized_name in {"audio_format", "format"}:
            if normalized_value not in VALID_AUDIO_FORMATS:
                raise ValueError("audio_format must be mp3, m4a, opus, wav, or flac")
            return MediaSettings(
                media=self.media,
                video_resolution=self.video_resolution,
                audio_quality=self.audio_quality,
                audio_format=normalized_value,
            )

        raise ValueError(
            "unknown setting; use media, resolution, audio_quality, or audio_format"
        )

    def describe(self) -> str:
        return (
            f"media={self.media}, "
            f"resolution={self.video_resolution}, "
            f"audio_quality={self.audio_quality}, "
            f"audio_format={self.audio_format}"
        )

    def cache_profile(self) -> str:
        if self.media == "audio":
            return f"audio:{self.audio_format}:{self.audio_quality}"
        return f"video:mp4:{self.video_resolution}"
