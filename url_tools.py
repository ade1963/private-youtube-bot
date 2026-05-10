from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


URL_PATTERN = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:!?)]]}'\""
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


class UrlError(ValueError):
    pass


def extract_url(text: str) -> str:
    match = URL_PATTERN.search(text or "")
    if not match:
        raise UrlError("Send a YouTube link.")
    return match.group(0).strip().rstrip(TRAILING_PUNCTUATION)


def is_youtube_host(host: str) -> bool:
    return host.lower() in YOUTUBE_HOSTS


def youtube_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if host in {"youtu.be", "www.youtu.be"} and path_parts:
        return path_parts[0]

    if not is_youtube_host(host):
        return None

    if parsed.path == "/watch":
        values = parse_qs(parsed.query).get("v")
        return values[0] if values else None

    if path_parts and path_parts[0] in {"shorts", "embed", "live"} and len(path_parts) > 1:
        return path_parts[1]

    return None


def clean_url(text: str) -> str:
    raw_url = extract_url(text)
    parsed = urlparse(raw_url)
    host = parsed.netloc.lower()

    if is_youtube_host(host):
        video_id = youtube_video_id(raw_url)
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

    query = parse_qs(parsed.query, keep_blank_values=True)
    clean_query = {
        key: values
        for key, values in query.items()
        if not key.lower().startswith("utm_") and key.lower() not in {"si", "feature"}
    }
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "",
            urlencode(clean_query, doseq=True),
            "",
        )
    )


def cache_identity(cleaned_url: str) -> str:
    video_id = youtube_video_id(cleaned_url)
    if video_id:
        return f"youtube:{video_id}"
    return "url:" + hashlib.sha256(cleaned_url.encode("utf-8")).hexdigest()[:32]
