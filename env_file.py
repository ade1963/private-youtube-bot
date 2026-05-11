from __future__ import annotations

from pathlib import Path


def update_env_list(env_path: Path, key: str, values: set[int]) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{key}={','.join(str(value) for value in sorted(values))}\n"

    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        lines = []

    replaced = False
    updated_lines = []
    for existing_line in lines:
        stripped = existing_line.lstrip()
        if stripped.startswith(f"{key}="):
            updated_lines.append(line)
            replaced = True
        else:
            updated_lines.append(existing_line)

    if not replaced:
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] += "\n"
        updated_lines.append(line)

    env_path.write_text("".join(updated_lines), encoding="utf-8")
