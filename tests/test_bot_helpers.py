import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from bot_config import load_config, parse_chat_ids, parse_size
from bot import TelegramYtdlpBot
from env_file import update_env_list
from file_parts import part_count, write_file_part
from media_settings import MediaSettings
from state_store import ArtifactRecord, StateStore, current_week_start, now_iso
from user_registry import UserRegistry
from url_tools import cache_identity, clean_url


def _make_bot(tmp_path, weekly_limit=1024**3):
    config = MagicMock()
    config.telegram_part_size_bytes = 50 * 1024**2
    config.max_upload_parts = 3
    config.weekly_user_limit_bytes = weekly_limit
    config.data_dir = tmp_path
    config.error_history_limit = 100

    bot = TelegramYtdlpBot.__new__(TelegramYtdlpBot)
    bot.config = config
    bot.state = StateStore(tmp_path / "state.json")
    bot.state_lock = asyncio.Lock()
    return bot


def _make_record(tmp_path, media="video", size=100):
    path = tmp_path / f"artifact.{'mp4' if media == 'video' else 'mp3'}"
    path.write_bytes(b"x" * size)
    return ArtifactRecord(
        key="testkey",
        path=path,
        title="Test",
        size_bytes=size,
        media=media,
        created_at=now_iso(),
        last_accessed_at=now_iso(),
        url="https://example.com/v",
        profile=f"{media}:mp4:720" if media == "video" else "audio:mp3:192",
    )


def test_parse_size_accepts_human_units():
    assert parse_size("1GB") == 1024**3
    assert parse_size("1.5 MB") == int(1.5 * 1024**2)
    assert parse_size("42") == 42


def test_parse_chat_ids_accepts_common_separators():
    assert parse_chat_ids("1, 2;3\n4") == {1, 2, 3, 4}


def test_load_config_reads_telegram_part_settings(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=token",
                "ALLOWED_CHAT_IDS=1",
                "ADMIN_CHAT_IDS=1",
                "TELEGRAM_PART_SIZE_BYTES=25MB",
                "MAX_UPLOAD_PARTS=4",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = load_config(env_path)

    assert config.telegram_part_size_bytes == 25 * 1024**2
    assert config.max_upload_parts == 4
    assert config.default_audio_quality == "96"


def test_telegram_part_size_is_capped_at_50mb(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=token",
                "ALLOWED_CHAT_IDS=1",
                "ADMIN_CHAT_IDS=1",
                "TELEGRAM_PART_SIZE_BYTES=100MB",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = load_config(env_path)

    assert config.telegram_part_size_bytes == 50 * 1024**2


def test_clean_url_normalizes_watch_links():
    assert (
        clean_url("https://www.youtube.com/watch?v=abc123&utm_source=x&list=playlist")
        == "https://www.youtube.com/watch?v=abc123"
    )


def test_clean_url_normalizes_short_links():
    assert (
        clean_url("<https://youtu.be/abc123?si=tracking>")
        == "https://www.youtube.com/watch?v=abc123"
    )


def test_cache_identity_uses_video_id():
    assert cache_identity("https://www.youtube.com/watch?v=abc123") == "youtube:abc123"


def test_update_env_list_preserves_other_lines(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("TOKEN=x\nALLOWED_CHAT_IDS=1\nOTHER=y\n", encoding="utf-8")

    update_env_list(env_path, "ALLOWED_CHAT_IDS", {3, 1, 2})

    assert env_path.read_text(encoding="utf-8").splitlines() == [
        "TOKEN=x",
        "ALLOWED_CHAT_IDS=1,2,3",
        "OTHER=y",
    ]


def test_user_registry_stores_nickname(tmp_path):
    registry = UserRegistry(tmp_path / "users.json")

    registry.add_user(123, "Alice", added_by=1)
    reloaded = UserRegistry(tmp_path / "users.json")

    assert reloaded.chat_ids() == {123}
    assert reloaded.list_users()[0].nickname == "Alice"


def test_write_file_part_creates_binary_chunk(tmp_path):
    source = tmp_path / "source.bin"
    target = tmp_path / "target.part"
    source.write_bytes(b"abcdef")

    write_file_part(source, target, offset=2, size_bytes=3)

    assert target.read_bytes() == b"cde"
    assert part_count(101, 50) == 3


def test_media_settings_update_validates_values():
    settings = MediaSettings("audio", 720, "192", "mp3")

    assert settings.update("media", "video").media == "video"
    assert settings.update("resolution", "1080").video_resolution == 1080
    assert settings.update("audio_quality", "320").audio_quality == "320"


def test_week_start_is_monday():
    assert current_week_start(date(2026, 5, 10)) == "2026-05-04"
    assert current_week_start(date(2026, 5, 11)) == "2026-05-11"


def test_week_usage_resets_on_new_week(tmp_path):
    store = StateStore(tmp_path / "state.json")

    store.add_week_usage(123, 100, today=date(2026, 5, 10))
    assert store.get_week_usage(123, today=date(2026, 5, 10)) == 100
    assert store.get_week_usage(123, today=date(2026, 5, 11)) == 0


def test_cleanup_storage_removes_oldest_artifacts(tmp_path):
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    first.write_bytes(b"a" * 80)
    second.write_bytes(b"b" * 80)

    store = StateStore(tmp_path / "state.json")
    old_time = "2026-05-01T00:00:00+00:00"
    new_time = now_iso()
    store.set_artifact(
        ArtifactRecord(
            key="first",
            path=first,
            title="first",
            size_bytes=80,
            media="audio",
            created_at=old_time,
            last_accessed_at=old_time,
            url="https://example.com/1",
            profile="audio:mp3:192",
        )
    )
    store.set_artifact(
        ArtifactRecord(
            key="second",
            path=second,
            title="second",
            size_bytes=80,
            media="audio",
            created_at=new_time,
            last_accessed_at=new_time,
            url="https://example.com/2",
            profile="audio:mp3:192",
        )
    )

    removed = store.cleanup_storage(100)

    assert [record.key for record in removed] == ["first"]
    assert not first.exists()
    assert second.exists()


def test_cache_hit_does_not_charge_weekly_usage(tmp_path):
    bot = _make_bot(tmp_path)
    record = _make_record(tmp_path, media="video", size=100)
    bot.state.set_artifact(record)

    message = MagicMock()
    message.reply_video = AsyncMock()

    asyncio.run(bot.send_artifact(123, message, record, from_cache=True))

    assert bot.state.get_week_usage(123) == 0


def test_fresh_download_charges_weekly_usage(tmp_path):
    bot = _make_bot(tmp_path)
    record = _make_record(tmp_path, media="audio", size=200)
    bot.state.set_artifact(record)

    message = MagicMock()
    message.reply_audio = AsyncMock()

    asyncio.run(bot.send_artifact(123, message, record, from_cache=False))

    assert bot.state.get_week_usage(123) == 200
