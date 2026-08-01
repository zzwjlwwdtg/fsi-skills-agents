"""Crash-safe helpers for small local state files."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: str | Path, value: Any, *, indent: int = 2) -> None:
    """Atomically replace *path* with durable UTF-8 JSON.

    The temporary file is created beside the destination so os.replace() stays
    on one filesystem. Readers therefore see either the old complete document
    or the new complete document, never a truncated in-place write.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as tmp:
            tmp_name = tmp.name
            json.dump(value, tmp, indent=indent, ensure_ascii=False)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, destination)
        tmp_name = None
    finally:
        if tmp_name is not None:
            try:
                Path(tmp_name).unlink()
            except OSError:
                pass
