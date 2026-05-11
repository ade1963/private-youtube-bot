from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_TEMPLATE = "%(title).200B [%(id)s].%(ext)s"


class QuietLogger:
    def debug(self, message: str) -> None:
        pass

    def info(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        print(f"Warning: {message}", file=sys.stderr)

    def error(self, message: str) -> None:
        print(message, file=sys.stderr)


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc

    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def audio_quality(value: str) -> str:
    if not value:
        raise argparse.ArgumentTypeError("must not be empty")

    if value.isdigit():
        parsed = int(value)
        if 0 <= parsed <= 10:
            return value
        if parsed >= 32:
            return value

    raise argparse.ArgumentTypeError(
        "use 0-10 for VBR quality, or a bitrate like 128, 192, 320"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download YouTube audio or video with yt-dlp."
    )
    parser.add_argument("url", nargs="+", help="YouTube URL(s) to download")
    parser.add_argument(
        "-m",
        "--media",
        choices=("audio", "video"),
        default="audio",
        help="download audio as MP3 or video as MP4 (default: audio)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default="downloads",
        help="folder where files are saved (default: downloads)",
    )
    parser.add_argument(
        "--resolution",
        type=positive_int,
        default=720,
        help="maximum video height, e.g. 480, 720, 1080 (default: 720)",
    )
    parser.add_argument(
        "--audio-quality",
        type=audio_quality,
        default="96",
        help="MP3 quality: 0-10 VBR, or bitrate like 96/128/320 (default: 96)",
    )
    parser.add_argument(
        "--audio-format",
        choices=("mp3", "m4a", "opus", "wav", "flac"),
        default="mp3",
        help="audio output format (default: mp3)",
    )
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="allow playlist downloads; by default only one video is downloaded",
    )
    parser.add_argument(
        "--cookies-from-browser",
        choices=("brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi"),
        help="read cookies from a local browser profile for age/login-restricted videos",
    )
    parser.add_argument(
        "--keep-original",
        action="store_true",
        help="keep source files after post-processing",
    )
    return parser


def build_video_format(max_height: int) -> str:
    return (
        f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/"
        f"b[height<={max_height}][ext=mp4]/"
        f"bv*[height<={max_height}]+ba/"
        f"b[height<={max_height}]/"
        "bv*+ba/b"
    )


def progress_hook(status: dict[str, Any]) -> None:
    state = status.get("status")

    if state == "downloading":
        filename = Path(status.get("filename") or "").name
        percent = status.get("_percent_str", "").strip()
        speed = status.get("_speed_str", "").strip()
        eta = status.get("_eta_str", "").strip()
        details = " ".join(part for part in (percent, speed, f"ETA {eta}" if eta else "") if part)
        print(f"\rDownloading {filename} {details}".rstrip(), end="", flush=True)
        return

    if state == "finished":
        print("\nDownload finished. Processing...")


def build_options(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    options: dict[str, Any] = {
        "outtmpl": str(output_dir / DEFAULT_OUTPUT_TEMPLATE),
        "noplaylist": not args.playlist,
        "keepvideo": args.keep_original,
        "logger": QuietLogger(),
        "progress_hooks": [progress_hook],
        "windowsfilenames": True,
    }

    if args.cookies_from_browser:
        options["cookiesfrombrowser"] = (args.cookies_from_browser,)

    if args.media == "audio":
        options.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": args.audio_format,
                        "preferredquality": args.audio_quality,
                    }
                ],
            }
        )
    else:
        options.update(
            {
                "format": build_video_format(args.resolution),
                "merge_output_format": "mp4",
            }
        )

    return options


def ensure_runtime_ready(media: str) -> None:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return

    raise SystemExit(
        "ffmpeg and ffprobe are required for MP3 conversion and MP4 merging.\n"
        "Install FFmpeg, then make sure ffmpeg.exe and ffprobe.exe are on PATH."
    )


def run_download(args: argparse.Namespace) -> int:
    ensure_runtime_ready(args.media)

    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "yt-dlp is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    options = build_options(args)

    try:
        with YoutubeDL(options) as downloader:
            return downloader.download(args.url)
    except DownloadError as exc:
        print(f"\nDownload failed: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_download(args)


if __name__ == "__main__":
    raise SystemExit(main())
