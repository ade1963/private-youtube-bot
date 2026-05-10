from __future__ import annotations

import json
import traceback
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from media_settings import MediaSettings


STATE_VERSION = 1


@dataclass(frozen=True)
class ArtifactRecord:
    key: str
    path: Path
    title: str
    size_bytes: int
    media: str
    created_at: str
    last_accessed_at: str
    url: str
    profile: str

    @classmethod
    def from_dict(cls, key: str, values: dict[str, Any]) -> "ArtifactRecord":
        return cls(
            key=key,
            path=Path(values["path"]),
            title=str(values.get("title", key)),
            size_bytes=int(values.get("size_bytes", 0)),
            media=str(values.get("media", "")),
            created_at=str(values.get("created_at", "")),
            last_accessed_at=str(values.get("last_accessed_at", "")),
            url=str(values.get("url", "")),
            profile=str(values.get("profile", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "title": self.title,
            "size_bytes": self.size_bytes,
            "media": self.media,
            "created_at": self.created_at,
            "last_accessed_at": self.last_accessed_at,
            "url": self.url,
            "profile": self.profile,
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_week_start(today: date | None = None) -> str:
    current = today or date.today()
    monday = current.fromordinal(current.toordinal() - current.weekday())
    return monday.isoformat()


def empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "users": {},
        "artifacts": {},
        "errors": [],
        "stats": {
            "requests": 0,
            "downloads": 0,
            "cache_hits": 0,
            "bytes_sent": 0,
            "errors_total": 0,
        },
    }


class StateStore:
    def __init__(self, path: Path, error_history_limit: int = 100) -> None:
        self.path = path
        self.error_history_limit = error_history_limit
        self.state = empty_state()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        self.state = empty_state()
        self.state.update(loaded)
        self.state.setdefault("users", {})
        self.state.setdefault("artifacts", {})
        self.state.setdefault("errors", [])
        self.state.setdefault("stats", empty_state()["stats"])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(self.state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        temp_path.replace(self.path)

    def get_user_settings(self, chat_id: int, fallback: MediaSettings) -> MediaSettings:
        user = self.state["users"].setdefault(str(chat_id), {})
        return MediaSettings.from_dict(user.get("settings", {}), fallback)

    def set_user_settings(self, chat_id: int, settings: MediaSettings) -> None:
        user = self.state["users"].setdefault(str(chat_id), {})
        user["settings"] = settings.to_dict()

    def reset_user_settings(self, chat_id: int) -> None:
        user = self.state["users"].setdefault(str(chat_id), {})
        user.pop("settings", None)

    def get_week_usage(self, chat_id: int, today: date | None = None) -> int:
        user = self.state["users"].setdefault(str(chat_id), {})
        usage = user.setdefault("usage", {})
        week_start = current_week_start(today)
        if usage.get("week_start") != week_start:
            usage["week_start"] = week_start
            usage["bytes"] = 0
        return int(usage.get("bytes", 0))

    def add_week_usage(self, chat_id: int, size_bytes: int, today: date | None = None) -> int:
        user = self.state["users"].setdefault(str(chat_id), {})
        usage = user.setdefault("usage", {})
        week_start = current_week_start(today)
        if usage.get("week_start") != week_start:
            usage["week_start"] = week_start
            usage["bytes"] = 0
        usage["bytes"] = max(0, int(usage.get("bytes", 0)) + size_bytes)
        return int(usage["bytes"])

    def can_add_week_usage(
        self,
        chat_id: int,
        size_bytes: int,
        limit_bytes: int,
        today: date | None = None,
    ) -> bool:
        return self.get_week_usage(chat_id, today) + size_bytes <= limit_bytes

    def get_artifact(self, key: str) -> ArtifactRecord | None:
        values = self.state["artifacts"].get(key)
        if not values:
            return None
        record = ArtifactRecord.from_dict(key, values)
        if not record.path.exists():
            self.state["artifacts"].pop(key, None)
            return None
        return record

    def set_artifact(self, record: ArtifactRecord) -> None:
        self.state["artifacts"][record.key] = record.to_dict()

    def touch_artifact(self, key: str) -> None:
        artifact = self.state["artifacts"].get(key)
        if artifact:
            artifact["last_accessed_at"] = now_iso()

    def remove_artifact(self, key: str) -> None:
        record = self.get_artifact(key)
        if record and record.path.exists():
            record.path.unlink(missing_ok=True)
        self.state["artifacts"].pop(key, None)

    def cleanup_missing_artifacts(self) -> None:
        missing = [
            key
            for key, values in self.state["artifacts"].items()
            if not Path(values.get("path", "")).exists()
        ]
        for key in missing:
            self.state["artifacts"].pop(key, None)

    def total_artifact_bytes(self) -> int:
        self.cleanup_missing_artifacts()
        return sum(
            int(values.get("size_bytes", 0))
            for values in self.state["artifacts"].values()
        )

    def cleanup_storage(self, max_bytes: int, keep_keys: set[str] | None = None) -> list[ArtifactRecord]:
        keep_keys = keep_keys or set()
        self.cleanup_missing_artifacts()
        total = self.total_artifact_bytes()
        removed: list[ArtifactRecord] = []
        records = [
            ArtifactRecord.from_dict(key, values)
            for key, values in self.state["artifacts"].items()
            if key not in keep_keys
        ]
        records.sort(key=lambda record: record.created_at or "1970-01-01T00:00:00+00:00")

        for record in records:
            if total <= max_bytes:
                break
            total -= record.size_bytes
            if record.path.exists():
                record.path.unlink(missing_ok=True)
            self.state["artifacts"].pop(record.key, None)
            removed.append(record)

        return removed

    def record_request(self) -> None:
        self.state["stats"]["requests"] = int(self.state["stats"].get("requests", 0)) + 1

    def record_download(self) -> None:
        self.state["stats"]["downloads"] = int(self.state["stats"].get("downloads", 0)) + 1

    def record_cache_hit(self) -> None:
        self.state["stats"]["cache_hits"] = int(self.state["stats"].get("cache_hits", 0)) + 1

    def record_bytes_sent(self, size_bytes: int) -> None:
        self.state["stats"]["bytes_sent"] = max(
            0,
            int(self.state["stats"].get("bytes_sent", 0)) + size_bytes,
        )

    def record_error(
        self,
        chat_id: int | None,
        stage: str,
        message: str,
        exc: BaseException | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        error_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
        entry = {
            "id": error_id,
            "created_at": now_iso(),
            "chat_id": chat_id,
            "stage": stage,
            "message": message,
            "exception_type": type(exc).__name__ if exc else None,
            "traceback": "".join(traceback.format_exception(exc)) if exc else "",
            "context": context or {},
        }
        self.state["errors"].append(entry)
        self.state["errors"] = self.state["errors"][-self.error_history_limit :]
        self.state["stats"]["errors_total"] = int(self.state["stats"].get("errors_total", 0)) + 1
        return error_id

    def recent_errors(self, limit: int = 5) -> list[dict[str, Any]]:
        return list(reversed(self.state.get("errors", [])[-limit:]))
