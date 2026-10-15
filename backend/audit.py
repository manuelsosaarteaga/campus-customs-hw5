"""Append-only audit trail: output/audit_trail.json, a JSON array with one entry per agent-loop step.

Entries are only ever added. Each write splices the new entry in before the closing "]" under an
exclusive file lock, so earlier entries are never rewritten and the file survives restarts and
repeated runs.
"""

import fcntl
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from models import AuditEvent

log = logging.getLogger("campus_customs.audit")

AUDIT_PATH = Path(__file__).resolve().parent.parent / "output" / "audit_trail.json"
_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def append_audit_event(event: AuditEvent, path: Path = AUDIT_PATH) -> None:
    """Append one entry without touching earlier ones. Never raises: auditing must not stop a ticket run."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        block = json.dumps(event.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2)
        block = "\n".join("  " + line for line in block.splitlines())
        with _lock:  # threads in this process
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
            with os.fdopen(fd, "r+b") as f:
                fcntl.flock(f, fcntl.LOCK_EX)  # other processes
                try:
                    _splice(f, block, path)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        log.exception("Could not write audit entry")


def _splice(f, block: str, path: Path) -> None:
    f.seek(0, os.SEEK_END)
    size = f.tell()
    if size == 0:
        f.write(f"[\n{block}\n]\n".encode())
        return
    # Find the closing "]" by scanning back over trailing whitespace.
    pos, tail = size, b""
    while pos > 0:
        step = min(4096, pos)
        pos -= step
        f.seek(pos)
        tail = f.read(step) + tail
        if tail.strip():
            break
    stripped = tail.rstrip()
    if not stripped.endswith(b"]"):
        # Not a JSON array we wrote: keep it (never delete) and start a fresh file.
        backup = path.with_name(f"{path.stem}.corrupt-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
        f.close()
        path.rename(backup)
        log.error("Audit file was not a JSON array; moved to %s", backup.name)
        path.write_text(f"[\n{block}\n]\n", encoding="utf-8")
        return
    before = stripped[:-1].rstrip()  # everything up to the last entry's "}" (or the opening "[")
    f.seek(pos + len(before))
    f.truncate()
    separator = "\n" if before.endswith(b"[") else ",\n"
    f.write(f"{separator}{block}\n]\n".encode())
