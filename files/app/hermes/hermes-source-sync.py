#!/usr/bin/env python3
"""Converge the core ref without discarding Puppet-owned tool overlays.

Only the explicit managed paths may be temporarily restored to Git content.
A durable journal is written first; interrupted transactions roll back before
another fetch. Unknown tracked edits and staged changes fail closed.
"""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


# Keep in step with the source tool File resources in install.pp. These are
# overlays, not patches: their exact pre-transition state wins over either ref.
OVERLAYS = tuple('tools/' + name for name in (
    'agent_request_tool.py', 'google_photos_tool.py', 'google_workspace_tool.py',
    'oauth_browser_tool.py', 'secure_browser_oauth_tool.py',
    'secure_browser_tool.py', 'firefox_ui_bridge.py',
    'secure_browser_local_bidi.py', 'secure_browser_bidi.py',
    'secure_browser_legacy_support.py', 'shopping_browser_tool.py',
))


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()


def snapshot(repo):
    result = {}
    for name in OVERLAYS:
        path = repo / name
        if path.parent.is_symlink() or not path.parent.is_dir():
            raise RuntimeError('overlay parent must be a real directory: ' + name)
        if path.is_symlink():
            info = path.lstat()
            result[name] = {'link': os.readlink(path), 'uid': info.st_uid, 'gid': info.st_gid}
        elif path.exists():
            if not path.is_file():
                raise RuntimeError('overlay must be a file or symlink: ' + name)
            info = path.stat()
            result[name] = {'data': base64.b64encode(path.read_bytes()).decode(),
                            'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        else:
            result[name] = None
    return result


def restore(repo, files):
    for name, saved in files.items():
        path = repo / name
        if path.parent.is_symlink():
            raise RuntimeError('refusing symlink overlay parent: ' + name)
        if path.is_symlink() or path.exists():
            path.unlink()
        if saved is None:
            continue
        if 'link' in saved:
            path.symlink_to(saved['link'])
            if (path.lstat().st_uid, path.lstat().st_gid) != (saved['uid'], saved['gid']):
                os.lchown(path, saved['uid'], saved['gid'])
        else:
            path.write_bytes(base64.b64decode(saved['data']))
            os.chmod(path, saved['mode'])
            if (path.stat().st_uid, path.stat().st_gid) != (saved['uid'], saved['gid']):
                os.chown(path, saved['uid'], saved['gid'])


def uncover(repo):
    """Remove only journaled overlay paths, then expose their current Git base."""
    for name in OVERLAYS:
        path = repo / name
        if path.parent.is_symlink():
            raise RuntimeError('refusing symlink overlay parent: ' + name)
        if path.exists() or path.is_symlink():
            path.unlink()
    tracked = git(repo, 'ls-files', '-z', '--', *OVERLAYS).split('\0')
    tracked = [name for name in tracked if name]
    if tracked:
        git(repo, 'restore', '--source=HEAD', '--worktree', '--', *tracked)


def save_journal(path, state):
    temporary = path.with_suffix('.new')
    with temporary.open('w') as stream:
        os.chmod(temporary, 0o600)
        json.dump(state, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def rollback(repo, journal, state):
    if git(repo, 'rev-parse', 'HEAD') not in (state['head'], state['target']):
        raise RuntimeError('source moved outside interrupted transaction; preserve journal for inspection')
    uncover(repo)
    git(repo, 'checkout', '--detach', state['head'])
    if state['branch_value']:
        git(repo, 'update-ref', state['branch'], state['branch_value'])
    else:
        git(repo, 'update-ref', '-d', state['branch'])
    if state['symbolic']:
        git(repo, 'symbolic-ref', 'HEAD', state['symbolic'])
    restore(repo, state['files'])
    journal.unlink()


def sync(repo, ref, commit=None):
    repo = repo.resolve()
    git_dir = Path(git(repo, 'rev-parse', '--absolute-git-dir'))
    journal = git_dir / 'nest-source-transition.json'
    with (git_dir / 'nest-source-transition.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if any((git_dir / name).exists() for name in (
                'index.lock', 'MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD',
                'rebase-merge', 'rebase-apply', 'sequencer')):
            raise RuntimeError('Git operation in progress; preserve state for inspection')
        if journal.exists():
            rollback(repo, journal, json.loads(journal.read_text()))
        git(repo, 'check-ref-format', 'refs/heads/' + ref)
        if git(repo, 'diff', '--cached', '--name-only'):
            raise RuntimeError('staged source changes are not managed overlays')
        changed = set(filter(None, git(repo, 'diff', '--name-only', '-z').split('\0')))
        if changed - set(OVERLAYS):
            raise RuntimeError('unmanaged tracked source changes: ' + ', '.join(sorted(changed - set(OVERLAYS))))
        git(repo, 'fetch', 'origin')
        remote_branch = subprocess.run(
            ['git', '-C', str(repo), 'rev-parse', '--verify', 'refs/remotes/origin/' + ref + '^{commit}'],
            capture_output=True, text=True)
        rolling = (remote_branch.stdout.strip() if remote_branch.returncode == 0
                   else git(repo, 'rev-parse', '--verify', 'refs/tags/' + ref + '^{commit}'))
        target = git(repo, 'rev-parse', '--verify', commit + '^{commit}') if commit else rolling
        if commit:
            git(repo, 'merge-base', '--is-ancestor', target, rolling)
        head = git(repo, 'rev-parse', 'HEAD')
        symbolic = subprocess.run(['git', '-C', str(repo), 'symbolic-ref', '--quiet', 'HEAD'],
                                  capture_output=True, text=True).stdout.strip()
        branch = 'refs/heads/' + ref
        desired_symbolic = branch if not commit and remote_branch.returncode == 0 else ''
        if head == target and symbolic == desired_symbolic:
            return
        # Refuse branch rewinds/divergence during normal rolling convergence.
        # Explicit pinned commits provide the managed rollback control.
        if desired_symbolic:
            git(repo, 'merge-base', '--is-ancestor', head, target)
        previous = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--verify', branch],
                                  capture_output=True, text=True)
        state = {'head': head, 'target': target, 'symbolic': symbolic, 'branch': branch,
                 'branch_value': previous.stdout.strip() if previous.returncode == 0 else '',
                 'files': snapshot(repo)}
        save_journal(journal, state)
        try:
            uncover(repo)
            git(repo, 'checkout', '--detach', target)
            restore(repo, state['files'])
            if desired_symbolic:
                git(repo, 'update-ref', branch, target)
                git(repo, 'symbolic-ref', 'HEAD', branch)
        except BaseException:
            rollback(repo, journal, state)
            raise
        journal.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('ref')
    parser.add_argument('--commit')
    args = parser.parse_args()
    sync(args.source, args.ref, args.commit)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stderr.decode(errors='replace') if error.stderr else str(error), file=sys.stderr)
        sys.exit(1)
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
