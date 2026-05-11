# YouTube Downloader

Small Python CLI and private Telegram bot for downloading YouTube audio or video
through `yt-dlp`.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Install FFmpeg too, and make sure `ffmpeg.exe` and `ffprobe.exe` are on your `PATH`.
`yt-dlp` needs FFmpeg for MP3 conversion and for merging separate video/audio streams into MP4.

## Telegram Bot

Copy `.env.example` to `.env`, then set:

```text
TELEGRAM_BOT_TOKEN=...
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
```

Run the bot:

```powershell
python bot.py
```

The bot is private. Only chat IDs in `ALLOWED_CHAT_IDS` and `ADMIN_CHAT_IDS`
can use it. State is stored in `data/state.json`; there is no database.

User commands:

```text
/settings
/set media audio
/set media video
/set resolution 720
/set audio_quality 96
/set audio_format mp3
/resetsettings
```

Admin commands:

```text
/stats
/errors
/errors 10
/cleanup
/adduser 333333333 Alice
/users
```

Behavior:

- Incoming messages are scanned for a URL and YouTube URLs are normalized before
  download. Tracking and playlist noise is stripped for normal video links.
- Cached artifacts are reused when the same cleaned URL and quality profile are
  requested again.
- Total cached file storage is capped by `MAX_STORAGE_BYTES`; oldest artifacts
  are removed first.
- Per-user weekly usage is capped by `WEEKLY_USER_LIMIT_BYTES`; the week resets
  on Monday according to the VPS local date.
- Files are sent as one or more binary parts. `TELEGRAM_PART_SIZE_BYTES` is
  capped at 50 MB, and `MAX_UPLOAD_PARTS` defaults to 3. Artifacts larger than
  that combined limit are removed from cache.
- Admins can add users with `/adduser <chat_id> [nickname]`. Chat IDs are
  written back to `.env`; nicknames are stored in `data/users.json`.
- Cache sends are written to `data/state.json`, logged, shown to the user as a
  cache hit, and summarized in `/stats`.
- Errors are recorded with stack traces in `data/state.json`; admins can inspect
  recent diagnostics with `/errors`.

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
python app.py "URL_1" "URL_2" --media audio --audio-quality 320
```

Allow playlist downloads:

```powershell
python app.py "PLAYLIST_URL" --media video --resolution 1080 --playlist
```

For login or age-restricted videos, try browser cookies:

```powershell
python app.py "URL" --media audio --cookies-from-browser chrome
```

## Options

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
