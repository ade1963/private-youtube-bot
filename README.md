# Private YouTube Bot

Small Python Telegram bot and CLI for downloading YouTube audio or video with
[`yt-dlp`](https://github.com/yt-dlp/yt-dlp).

This project is meant for a small trusted group, for example 10-20 people on a
personal VPS. It is not designed as a public download service: there is no
database, no payment/account system, and no large-scale queue management. It is
intentionally simple and file-based.

## Features

- Telegram bot for downloading YouTube audio or video.
- Standalone CLI downloader in `app.py`.
- Allowlist access by Telegram chat ID.
- Admin commands for users, stats, cleanup, and error diagnostics.
- No database. Runtime state is stored as JSON under `data/`.
- URL cleanup before downloading.
- Cache reuse when the same cleaned URL and quality profile already exists.
- Total artifact storage cap, with oldest cached artifacts removed first.
- Weekly per-user download quota, reset every Monday.
- Per-user defaults for media type, video resolution, audio quality, and audio format.
- Oversized audio/video is split into playable media segments with FFmpeg.
- Full error diagnostics are stored for admin review.

## Requirements

- Python 3.11 or newer
- FFmpeg and FFprobe available on `PATH`
- A Telegram bot token from BotFather

Install Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On Linux/VPS the activation command is usually:

```bash
source .venv/bin/activate
```

## Configuration

Copy the example file and edit it:

```powershell
Copy-Item .env.example .env
```

Linux:

```bash
cp .env.example .env
```

Main settings:

```text
TELEGRAM_BOT_TOKEN=123456:replace-me
ALLOWED_CHAT_IDS=111111111,222222222
ADMIN_CHAT_IDS=111111111

MAX_STORAGE_BYTES=1GB
WEEKLY_USER_LIMIT_BYTES=1GB

TELEGRAM_PART_SIZE_BYTES=50MB
MAX_UPLOAD_PARTS=3

DEFAULT_MEDIA=audio
DEFAULT_VIDEO_RESOLUTION=720
DEFAULT_AUDIO_QUALITY=96
DEFAULT_AUDIO_FORMAT=mp3

BOT_DATA_DIR=data
DOWNLOAD_DIR=downloads
ERROR_HISTORY_LIMIT=100
```

Notes:

- `ALLOWED_CHAT_IDS` contains users who can use the bot.
- `ADMIN_CHAT_IDS` contains users who can run admin commands.
- Admins are allowed automatically, even if they are not repeated in `ALLOWED_CHAT_IDS`.
- `MAX_STORAGE_BYTES` limits cached files on disk.
- `WEEKLY_USER_LIMIT_BYTES` limits each user per week.
- `TELEGRAM_PART_SIZE_BYTES` is capped internally to 49 MB to stay below the public Telegram Bot API upload limit.
- `MAX_UPLOAD_PARTS=3` means one artifact can be sent as up to three playable media segments.

## Run The Bot

```powershell
python bot.py
```

The bot uses long polling. For a VPS, run it under `systemd`, `tmux`, `screen`,
Docker, or any process supervisor you prefer.

## User Commands

```text
/settings
/set media audio
/set media video
/set resolution 720
/set audio_quality 96
/set audio_format mp3
/resetsettings
```

Users can also just send a YouTube URL. The bot cleans the URL, downloads with
that user's current defaults, and sends the result.

## Admin Commands

```text
/stats
/errors
/errors 10
/cleanup
/adduser 333333333 Alice
/users
```

`/adduser <chat_id> [nickname]` updates two places:

- `.env`, by adding the chat ID to `ALLOWED_CHAT_IDS`
- `data/users.json`, by storing the nickname and who added the user

The bot updates its in-memory allowlist immediately after `/adduser`.

## Storage, Cache, And Quotas

Downloaded artifacts are stored in `DOWNLOAD_DIR`, usually `downloads/`.
Metadata, errors, user settings, and cache events are stored in `BOT_DATA_DIR`,
usually `data/`.

The cache key is based on:

- cleaned URL
- media type
- video resolution, for video
- audio format and audio quality, for audio

If a matching artifact exists, the bot sends the cached file instead of
downloading again. Cache sends are recorded in `data/state.json` and summarized
in `/stats`.

Storage cleanup is simple: if cached artifacts exceed `MAX_STORAGE_BYTES`, the
oldest artifacts are removed first.

Weekly quota is counted per user and resets on Monday according to the VPS local
date.

## Large Files

Telegram's public Bot API has a small upload limit. To handle larger downloads,
the bot can split audio/video into playable media segments using FFmpeg.

Example:

```text
TELEGRAM_PART_SIZE_BYTES=50MB
MAX_UPLOAD_PARTS=3
```

With these settings the bot may send up to three playable audio/video messages
for one artifact. It does not send raw binary chunks. If the artifact cannot fit
within the configured segment count, it is removed from cache and the user gets
a clear error.

## Errors

Errors are stored in `data/state.json` with:

- error ID
- chat ID
- stage
- message
- exception type
- traceback
- request context

Admins can inspect recent errors:

```text
/errors
/errors 10
```

## CLI Usage

Download MP3 audio:

```powershell
python app.py "https://www.youtube.com/watch?v=VIDEO_ID" --media audio --audio-quality 96
```

Download MP4 video up to 720p:

```powershell
python app.py "https://www.youtube.com/watch?v=VIDEO_ID" --media video --resolution 720
```

Download multiple URLs:

```powershell
python app.py "URL_1" "URL_2" --media audio --audio-quality 128
```

Allow playlist downloads in CLI mode:

```powershell
python app.py "PLAYLIST_URL" --media video --resolution 1080 --playlist
```

For login or age-restricted videos, try browser cookies:

```powershell
python app.py "URL" --media audio --cookies-from-browser chrome
```

CLI options:

```text
url                         one or more YouTube URLs
--media audio|video         audio creates MP3 by default; video creates MP4
--resolution 480|720|1080   maximum video height
--audio-quality 0-10|96     MP3 quality, either VBR 0-10 or bitrate
--audio-format mp3|m4a|opus|wav|flac
--output-dir downloads      output folder
--playlist                  allow playlist downloads
--cookies-from-browser      brave, chrome, chromium, edge, firefox, opera, safari, vivaldi
--keep-original             keep source files after post-processing
```

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```
