#!/usr/bin/env python3
"""Snapshot retained media config datasets atomically; publish a bounded backup.

Runs on Falcon through Bolt with escalation. Never snapshots or deletes legacy
/srv state. The snapshots contain SQLite databases and their WALs together.
"""
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

APPS = ("nzbget", "ombi", "radarr", "sonarr", "plex")
POOL = "data/crypt/kubernetes"
DEST = Path("/nest/backup/media")


def run(argv):
    return subprocess.check_output(argv, text=True).strip()


def backup(volumes):
    if set(volumes) != set(APPS):
        raise ValueError("Exactly the five media configuration datasets are required")
    datasets = {}
    for app in APPS:
        uid = volumes[app]
        if not isinstance(uid, str) or not re.fullmatch(r"pvc-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", uid):
            raise ValueError("Invalid PVC identity")
        dataset = POOL + "/" + uid
        if run(["zfs", "get", "-H", "-o", "value", "type", dataset]) != "filesystem":
            raise ValueError("Expected a ZFS filesystem")
        datasets[app] = dataset
    if len(set(datasets.values())) != len(APPS):
        raise ValueError("Configuration claims must use separate datasets")
    pending = run(["zfs", "list", "-H", "-t", "snapshot", "-o", "name", "-r", *datasets.values()])
    if any("@media-backup-" in line for line in pending.splitlines()):
        raise ValueError("A previous failed media backup snapshot set requires reconciliation")
    # Refuse a missing backup mount rather than filling Falcon's root dataset.
    if not run(["findmnt", "-n", "-o", "SOURCE", "-T", "/nest/backup"]).startswith("nest/"):
        raise ValueError("The direct Nest backup filesystem is unavailable")
    size = sum(int(run(["zfs", "get", "-Hp", "-o", "value", "logicalreferenced", ds])) for ds in datasets.values())
    headroom = size * 2 + 1024 ** 3
    if shutil.disk_usage("/var/tmp").free < headroom:
        raise ValueError("Insufficient local staging headroom")
    if shutil.disk_usage("/nest/backup").free < size + 1024 ** 3:
        raise ValueError("Insufficient final backup headroom")
    DEST.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DEST, 0o700)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap = "media-backup-" + stamp
    snapshots = [ds + "@" + snap for ds in datasets.values()]
    run(["zfs", "snapshot", *snapshots])
    # Failure preserves this bounded snapshot set for diagnosis, not automatic deletion.
    with tempfile.TemporaryDirectory(prefix="media-backup-", dir="/var/tmp") as tmp:
        staging = Path(tmp)
        for app, ds in datasets.items():
            mount = run(["zfs", "get", "-H", "-o", "value", "mountpoint", ds])
            if mount == "legacy":
                mount = run(["findmnt", "-rn", "-S", ds, "-o", "TARGET"]).splitlines()[0]
            root = Path(mount) / ".zfs" / "snapshot" / snap
            if not root.is_dir():
                raise ValueError("Snapshot path is unavailable")
            run(["tar", "--acls", "--xattrs", "--numeric-owner", "-cf", str(staging / (app + ".tar")), "-C", str(root), "."])
        run(["tar", "-cf", str(staging / "config.tar"), "-C", str(staging), *[app + ".tar" for app in APPS]])
        for app in APPS:
            (staging / (app + ".tar")).unlink()
        archive = staging / ("media-config-" + stamp + ".tar.zst")
        run(["zstd", "-T2", "-3", "--rm", str(staging / "config.tar"), "-o", str(archive)])
        run(["zstd", "-t", str(archive)])
        os.chmod(archive, 0o600)
        run(["rsync", "--checksum", "--chmod=F600", str(archive), str(DEST) + "/"])
        final = DEST / archive.name
        if final.stat().st_size != archive.stat().st_size:
            raise ValueError("Published backup size mismatch")
        # Read the final stored archive, not only the local staging copy.
        run(["zstd", "-t", str(final)])
    for snapshot in snapshots:
        run(["zfs", "destroy", snapshot])
    # This is normal backup retention, never migration rollback or old containers.
    previous = sorted(p for p in DEST.glob("media-config-*.tar.zst") if re.fullmatch(r"media-config-\d{8}T\d{6}Z\.tar\.zst", p.name))
    for expired in previous[:-2]:
        expired.unlink()
    return {"archive": str(final), "datasets": len(datasets), "consistency": "atomic ZFS snapshot with SQLite WAL", "retained_generations": min(len(previous), 2)}


def main():
    os.umask(0o077)
    try:
        data = json.load(sys.stdin)
        with open("/run/lock/nest-media-backup.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = backup(data["volumes"])
        print(json.dumps(result))
    except Exception as exc:
        # Never print application contents or command output.
        print(json.dumps({"_error": {"kind": "nest/media-backup", "msg": str(exc)}}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
