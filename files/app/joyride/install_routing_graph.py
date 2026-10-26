"""Install the reviewed private TEST graph; retain immutable files for rollback."""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import urllib.request

BUILD = "metro-20261026-v3"
# History enrichment retains topology identity so existing route bindings stay valid.
GRAPH_BUILD = "metro-20261025-v2"
SIZE = 1206992896
SHA256 = "9dcfaa2629a6a9d8a2903d5fd917b51b6fddbe55af49861a9d58ee098ad62886"
URL = ("https://gitlab.joyfullee.me/api/v4/projects/83/packages/generic/"
       "joyride-routing-private/metro-20261026-v3/" + SHA256 + ".sqlite3")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("redirect_denied")


def verify(path):
    if path.stat().st_size != SIZE:
        raise ValueError("graph_size_mismatch")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != SHA256:
        raise ValueError("graph_checksum_mismatch")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        # Share the hash-warmed file cache rather than duplicating the complete
        # graph in SQLite's heap while checking indexes in several key orders.
        db.execute("PRAGMA mmap_size=1342177280")
        db.execute("PRAGMA cache_size=-8192")
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("graph_integrity_failed")
        metadata = {key: json.loads(value) for key, value in db.execute("SELECT * FROM metadata")}
    if metadata["graph_build"] != GRAPH_BUILD or metadata["unresolved_migrations"]:
        raise ValueError("graph_metadata_mismatch")


def select(root, name, target):
    temporary = root / ("." + name)
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, root / name)


def install(root=Path("/data/private/routing")):
    if os.environ.get("RUNTIME_ENV") != "test":
        raise ValueError("test_only")
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    current = root / "current.sqlite3"
    if current.exists() and not current.is_symlink():
        raise ValueError("retain_unmanaged_graph_before_selection")
    destination = root / (BUILD + "-" + SHA256 + ".sqlite3")
    if not destination.exists():
        # Stage on the same filesystem. Renaming and symlink selection need no
        # second graph copy; leave 256 MiB headroom and never remove old data.
        if shutil.disk_usage(root).free < SIZE + 256 * 1024 * 1024:
            raise ValueError("insufficient_graph_staging_space")
        token = Path("/package-reader/GITLAB_READ_API_TOKEN").read_text().strip()
        request = urllib.request.Request(URL, headers={"PRIVATE-TOKEN": token})
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=root, prefix=".download-", delete=False) as output:
                temporary = Path(output.name)
                with urllib.request.build_opener(NoRedirect).open(request, timeout=120) as response:
                    remaining = SIZE
                    unsynced = 0
                    while remaining:
                        chunk = response.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("graph_download_truncated")
                        output.write(chunk)
                        remaining -= len(chunk)
                        unsynced += len(chunk)
                        # CephFS dirty pages count against the container limit.
                        # Bound writeback before they grow to the graph's size.
                        if unsynced >= 16 * 1024 * 1024:
                            output.flush()
                            os.fsync(output.fileno())
                            os.posix_fadvise(output.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
                            unsynced = 0
                    if response.read(1):
                        raise ValueError("graph_download_oversize")
                output.flush()
                os.fsync(output.fileno())
            verify(temporary)
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    else:
        verify(destination)
    # A fresh pod's fsGroup walk may add group write permissions to PVC files.
    destination.chmod(0o400)
    if current.is_symlink() and os.readlink(current) != destination.name:
        select(root, "previous.sqlite3", os.readlink(current))
    select(root, "current.sqlite3", destination.name)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print("private routing graph checksum, integrity and selection verified")


if __name__ == "__main__":
    try:
        install()
    except Exception:
        # Never leak credentials, private payloads or exception text into logs.
        raise SystemExit("private_routing_graph_install_failed") from None
