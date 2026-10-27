"""Writes that other readers and writers cannot see half-done.

* :func:`atomic_write_text` — temp file in the same directory, ``fsync``, ``os.replace``: a reader (or a ``git add``
  racing the writer) sees the old file or the new one, never a torn one, and a crash leaves the old file intact.
* :func:`file_lock` — an exclusive advisory lock on ``<path>.lock`` between PROCESSES on one machine (``fcntl.flock``;
  released by the kernel if the holder dies). Threads of one process need their own :class:`threading.Lock` on top:
  ``flock`` locks belong to the open file description, so two threads each opening the lock file do exclude each other,
  but a process-wide lock also saves the open/close.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

try:  # not on Windows: there the lock degrades to a no-op (the daemon only runs on Linux runners)
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


def atomic_write_text(path: str | Path, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def file_lock(path: str | Path) -> Iterator[None]:
    """Exclusive lock for read-modify-write of ``path`` across processes."""

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_name(p.name + ".lock"), "a+b") as lock:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
