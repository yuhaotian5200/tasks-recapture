"""Filesystem helpers. Writes stay inside the task directory."""

from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from tasks_recapture.errors import ConflictError, StoreError

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only off POSIX
    fcntl = None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_inside(root: Path, path: Path) -> Path:
    """Resolve `path` and require it to stay inside `root`.

    Symlinks are refused so a card cannot redirect a write outside the library.
    """
    root_resolved = root.resolve()
    if path.is_symlink():
        raise StoreError(f"refusing to follow a symlink: {path.name}")
    if path.exists():
        resolved = path.resolve()
    else:
        parent = path.parent
        if parent.is_symlink():
            raise StoreError(f"refusing to follow a symlink: {parent.name}")
        resolved = parent.resolve() / path.name
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise StoreError("path escapes the task directory")
    return resolved


def atomic_write(path: Path, text: str, expected_sha256: str | None = None) -> str:
    """Write `text` via a temp file in the same directory, then rename it.

    When `expected_sha256` is set, the current file must still have that hash.
    After the rename, the file is read back and must match `text` exactly.
    """
    if path.is_symlink():
        raise StoreError(f"refusing to write through a symlink: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        current = path.read_text(encoding="utf-8")
        current_hash = sha256_text(current)
        if expected_sha256 is not None and current_hash != expected_sha256:
            raise ConflictError(
                f"{path.name} changed after it was read; the new contents were kept"
            )
        mode = path.stat().st_mode & 0o777
    else:
        if expected_sha256 is not None:
            raise ConflictError(f"{path.name} is missing; nothing was written")
        mode = 0o644

    tmp_name = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=".card-", suffix=".tmp", dir=str(path.parent)
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
        tmp_name = None
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    written = path.read_text(encoding="utf-8")
    if written != text:
        raise StoreError(f"read-back verification failed for {path.name}")
    return sha256_text(written)


@contextmanager
def directory_lock(root: Path):
    """Exclusive lock for one task library. Requires POSIX fcntl."""
    if fcntl is None:
        raise StoreError("file locking needs a POSIX fcntl module")
    meta = root / ".tasks-recapture"
    meta.mkdir(parents=True, exist_ok=True)
    lock_path = meta / "lock"
    handle = lock_path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
