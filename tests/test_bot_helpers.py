from datetime import date

from bot_config import load_config, parse_chat_ids, parse_size
from media_settings import MediaSettings
from state_store import ArtifactRecord, StateStore, current_week_start, now_iso
from url_tools import cache_identity, clean_url


def test_parse_size_accepts_human_units():
    assert parse_size("1GB") == 1024**3
    assert parse_size("1.5 MB") == int(1.5 * 1024**2)
    assert parse_size("42") == 42


def test_parse_chat_ids_accepts_common_separators():
    assert parse_chat_ids("1, 2;3\n4") == {1, 2, 3, 4}


def test_load_config_reads_telegram_upload_limit(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=token",
                "ALLOWED_CHAT_IDS=1",
                "ADMIN_CHAT_IDS=1",
                "TELEGRAM_MAX_UPLOAD_BYTES=25MB",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = load_config(env_path)

    assert config.telegram_max_upload_bytes == 25 * 1024**2


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
