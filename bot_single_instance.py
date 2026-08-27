import fcntl
import os
from pathlib import Path

_lock_handle = None


def acquire_single_instance_lock():
    """Keep one SanaShop polling process per bot host.

    The open file descriptor is intentionally kept globally for the lifetime of
    the process so the advisory lock is released automatically on exit/crash.
    """
    global _lock_handle
    if _lock_handle is not None:
        return _lock_handle

    path = Path(os.environ.get("BOT_LOCK_PATH", "/var/lib/sanashop-bot/runtime.lock"))
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError(
            "Another SanaShop bot process is already running on this server."
        ) from exc

    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    os.fchmod(handle.fileno(), 0o600)
    _lock_handle = handle
    return handle
