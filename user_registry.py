from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from state_store import now_iso


@dataclass(frozen=True)
class UserRecord:
    chat_id: int
    nickname: str
    added_by: int
    created_at: str

    @classmethod
    def from_dict(cls, chat_id: str, values: dict[str, Any]) -> "UserRecord":
        return cls(
            chat_id=int(chat_id),
            nickname=str(values.get("nickname", "")),
            added_by=int(values.get("added_by", 0)),
            created_at=str(values.get("created_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "nickname": self.nickname,
            "added_by": self.added_by,
            "created_at": self.created_at,
        }


class UserRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.users: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            self.users = json.load(handle)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(self.users, handle, ensure_ascii=False, indent=2, sort_keys=True)
        temp_path.replace(self.path)

    def chat_ids(self) -> set[int]:
        return {int(chat_id) for chat_id in self.users}

    def add_user(self, chat_id: int, nickname: str, added_by: int) -> UserRecord:
        record = UserRecord(
            chat_id=chat_id,
            nickname=nickname.strip() or f"user-{chat_id}",
            added_by=added_by,
            created_at=now_iso(),
        )
        self.users[str(chat_id)] = record.to_dict()
        self.save()
        return record

    def list_users(self) -> list[UserRecord]:
        return [
            UserRecord.from_dict(chat_id, values)
            for chat_id, values in sorted(self.users.items(), key=lambda item: int(item[0]))
        ]
