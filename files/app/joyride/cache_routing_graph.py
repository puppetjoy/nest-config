"""Stage the pinned TEST routing graph onto node-local storage."""
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import tempfile

_INSTALLER = Path(__file__).with_name("install_routing_graph.py")
_SPEC = importlib.util.spec_from_file_location("joyride_routing_graph_installer", _INSTALLER)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("installer_unavailable")
_installer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_installer)

SOURCE = Path("/data/private/routing/current.sqlite3")
DESTINATION = Path("/routing-cache/graph.sqlite3")
CHUNK_SIZE = 1024 * 1024
SYNC_INTERVAL = 16 * 1024 * 1024


def stage(source=SOURCE, destination=DESTINATION):
    """Verify or atomically create the pinned node-local copy."""
    if os.environ.get("RUNTIME_ENV") != "test":
        raise ValueError("test_only")
    source, destination = Path(source), Path(destination)
    selection = source
    source = selection.resolve(strict=True)
    if destination.is_symlink():
        raise ValueError("destination_invalid")
    if destination.exists():
        _installer.verify(destination)
        return

    fd = None
    temporary = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(source, flags)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size != _installer.SIZE:
            raise ValueError("source_invalid")
        fdstat = before
        tmp_fd, tmp_name = tempfile.mkstemp(prefix="." + destination.name + "-", dir=destination.parent)
        temporary = Path(tmp_name)
        digest = hashlib.sha256()
        count = 0
        dirty = 0
        with os.fdopen(tmp_fd, "wb") as output:
            while True:
                chunk = os.read(fd, min(CHUNK_SIZE, _installer.SIZE - count + 1))
                if not chunk:
                    break
                count += len(chunk)
                if count > _installer.SIZE:
                    raise ValueError("source_invalid")
                digest.update(chunk)
                output.write(chunk)
                dirty += len(chunk)
                if dirty >= SYNC_INTERVAL:
                    output.flush()
                    os.fsync(output.fileno())
                    if hasattr(os, "posix_fadvise"):
                        os.posix_fadvise(output.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
                    dirty = 0
            output.flush()
            os.fsync(output.fileno())
        after = os.fstat(fd)
        current = os.stat(source, follow_symlinks=False)
        if (count != _installer.SIZE or digest.hexdigest() != _installer.SHA256 or
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) !=
                (fdstat.st_dev, fdstat.st_ino, fdstat.st_size, fdstat.st_mtime_ns) or
                (current.st_dev, current.st_ino) != (fdstat.st_dev, fdstat.st_ino) or
                selection.resolve(strict=True) != source):
            raise ValueError("source_changed")
        _installer.verify(temporary)
        temporary.chmod(0o400)
        os.replace(temporary, destination)
        temporary = None
    finally:
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        stage()
    except Exception:
        raise SystemExit("local_routing_graph_stage_failed") from None
