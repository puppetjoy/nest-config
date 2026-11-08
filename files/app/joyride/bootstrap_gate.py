"""Single-writer bootstrap receipt; readers wait in init, never a liveness loop.

The baked BACKEND_REVISION binds readers to the same immutable application
source. BOOTSTRAP_CONTRACT binds the exact Nest initializer recipe. Neither is
an application API, health bypass, graph scan or runtime release selector.
"""
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile
import time


def receipt_path(root, revision, contract):
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or not re.fullmatch(r'[0-9a-f]{64}', contract):
        raise ValueError('bootstrap_identity_required')
    installer = os.environ.get('ROUTING_INSTALLER_SHA256', '')
    if not re.fullmatch(r'[0-9a-f]{64}', installer):
        raise ValueError('bootstrap_installer_identity_required')
    script = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    key = hashlib.sha256(':'.join((revision, contract, installer, script)).encode()).hexdigest()
    return root / key


def publish(path):
    # Runs only after every mutating init succeeded. Concurrent compatible surge
    # writers can publish the same receipt; no mutable current pointer is used.
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write('bootstrap-complete\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def ready(path):
    try:
        return path.is_file() and not path.is_symlink() and path.read_text() == 'bootstrap-complete\n'
    except FileNotFoundError:
        return False


def main(mode):
    path = receipt_path(Path('/data/.bootstrap'), os.environ.get('BACKEND_REVISION', ''),
                        os.environ.get('BOOTSTRAP_CONTRACT', ''))
    if mode == 'publish':
        publish(path)
    elif mode == 'wait':
        while not ready(path):
            time.sleep(2)
    else:
        raise ValueError('bootstrap_mode_required')


if __name__ == '__main__':
    main(sys.argv[1])
