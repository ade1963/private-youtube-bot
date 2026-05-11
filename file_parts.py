from __future__ import annotations

import math
from pathlib import Path


def part_count(size_bytes: int, part_size_bytes: int) -> int:
    if size_bytes <= 0:
        return 1
    return math.ceil(size_bytes / part_size_bytes)


def write_file_part(
    source: Path,
    target: Path,
    offset: int,
    size_bytes: int,
    buffer_size: int = 1024 * 1024,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    remaining = size_bytes
    with source.open("rb") as input_file, target.open("wb") as output_file:
        input_file.seek(offset)
        while remaining > 0:
            chunk = input_file.read(min(buffer_size, remaining))
            if not chunk:
                break
            output_file.write(chunk)
            remaining -= len(chunk)
