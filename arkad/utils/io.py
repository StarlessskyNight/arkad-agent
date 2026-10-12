"""Secure file writes (chmod 600) and atomic saves for JSON stores."""
import os, pathlib
from ..constants import CONFIG_DIR, FILE_PERMISSION


def _open_private(path: pathlib.Path, flags: int, mode: int = FILE_PERMISSION) -> int:
    """``os.open`` + force ``mode`` on the fd before any data is written.

    ``O_CREAT``'s mode only applies to a brand-new file — a pre-existing
    file keeps its old permissions — so fchmod covers both cases. Raises
    OSError: a secret must never land in a file whose mode we failed to
    lock down (the old write-then-chmod version swallowed this).
    """
    fd = os.open(path, flags, mode)
    try:
        os.fchmod(fd, mode)
    except OSError:
        os.close(fd)
        raise
    return fd


def _secure_write(path: pathlib.Path, data: str):
    """Write ``data`` to ``path`` so the file is 0600 from its first byte.

    No write-then-chmod window: the fd is created 0600 (and any looser
    pre-existing mode tightened) *before* any data is written, in the same
    file — no temp-file dance needed for these small secret/config writes.
    Raises OSError on open/permission/write failure; callers that want to
    surface it already catch it (e.g. web/providers_api.save_key).
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd = _open_private(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(data)


def _atomic_write(path: pathlib.Path, data: str) -> None:
    """Write ``data`` to ``path`` atomically: a private (0600) temp file in
    the same directory + ``os.replace``. A crash mid-write can never
    truncate or corrupt the destination, and the result is 0600 either way.
    """
    tmp = path.with_name(path.name + ".tmp")
    fd = _open_private(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _quarantine_corrupt(path: pathlib.Path) -> None:
    """Move an unparsable store file to ``<name>.corrupt`` (single most
    recent backup — an older one gets overwritten) so the next save cannot
    silently erase the user's data. Never raises: loading must stay non-fatal.
    """
    try:
        os.replace(path, path.with_name(path.name + ".corrupt"))
    except OSError:
        pass
