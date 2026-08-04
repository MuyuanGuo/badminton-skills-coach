#!/usr/bin/env python3
"""Cross-platform repository-wide writer lock for update pipelines."""

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "data" / "processing" / ".project-update.lock"
LOCK_OWNER_ENV = "BSC_PROJECT_UPDATE_LOCK_HELD"


def _lock_nonblocking(handle):
    if os.name == "nt":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write("\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(  # type: ignore[attr-defined]
            handle.fileno(), msvcrt.LK_NBLCK, 1  # type: ignore[attr-defined]
        )
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def acquire_project_update_lock(root=ROOT):
    """Hold one lock across Douyin, Bilibili, rebuild, install, and git writes."""

    if os.environ.get(LOCK_OWNER_ENV) == "1":
        return None
    root = Path(root)
    path = root / "data" / "processing" / ".project-update.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        _lock_nonblocking(handle)
    except (BlockingIOError, OSError) as error:
        handle.close()
        raise RuntimeError(
            "Another project update writer holds "
            "data/processing/.project-update.lock"
        ) from error
    return handle
