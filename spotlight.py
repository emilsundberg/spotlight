#!/usr/bin/env python3
"""One-way, recoverable worktree previews. Requires Python 3.10+ and Git."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid


class SpotlightError(Exception):
    pass


class RetrySnapshot(SpotlightError):
    """A changing source or busy Git checkout can be retried on the next tick."""


def git(root, *args, input=None, allowed=(0,)):
    env = os.environ.copy()
    # Inherited Git overrides must never redirect operations to another index/repo.
    for key in list(env):
        if key.startswith('GIT_'):
            del env[key]
    env['GIT_OPTIONAL_LOCKS'] = '0'
    result = subprocess.run(['git', '-C', str(root), *args], input=input,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if result.returncode not in allowed:
        raise SpotlightError(result.stderr.decode(errors='replace').strip() or 'Git command failed')
    return result.stdout


def git_path(root, name):
    value = os.fsdecode(git(root, 'rev-parse', '--git-path', name)).strip()
    path = Path(value)
    return path if path.is_absolute() else root / path


def worktrees(root):
    records = []
    for block in git(root, 'worktree', 'list', '--porcelain', '-z').split(b'\0\0'):
        fields = {}
        for line in block.split(b'\0'):
            if line:
                key, _, value = line.partition(b' ')
                fields[os.fsdecode(key)] = os.fsdecode(value)
        if fields:
            records.append(fields)
    return records


def base_checkout(location):
    records = worktrees(location)
    if not records or 'bare' in records[0]:
        raise SpotlightError('A non-bare main checkout is required.')
    return Path(records[0]['worktree']).resolve()


def safe_path(root, name):
    parts = PurePosixPath(name).parts
    if (not parts or name.startswith('/') or '..' in parts
            or any(p.casefold() == '.git' for p in parts)):
        raise SpotlightError(f'Unsafe repository path: {name!r}')
    path = root
    for part in parts[:-1]:
        path = path / part
        if path.is_symlink():
            raise SpotlightError(f'Refusing to traverse a symlink: {path}')
    return root.joinpath(*parts)


def sync_directory(path):
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def atomic_bytes(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.spotlight-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temp, path)
        sync_directory(path.parent)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)


def save_json(path, data):
    atomic_bytes(path, (json.dumps(data, sort_keys=True) + '\n').encode())


def repository_ready(root):
    for marker in ('index.lock', 'HEAD.lock', 'MERGE_HEAD', 'CHERRY_PICK_HEAD',
                   'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'sequencer', 'BISECT_START'):
        if git_path(root, marker).exists():
            raise RetrySnapshot(f'Git operation in progress in {root}: {marker}')
    if git(root, 'config', '--bool', 'core.sparseCheckout', allowed=(0, 1)).strip() == b'true':
        raise SpotlightError('Sparse checkouts are not supported.')
    flags = git(root, 'ls-files', '-v', '-z').split(b'\0')
    if any(row and (row[:1].islower() or row.startswith(b'S ')) for row in flags):
        raise SpotlightError('Clear assume-unchanged / skip-worktree flags before using Spotlight.')


def identity(root):
    return {
        'head': git(root, 'rev-parse', 'HEAD').decode().strip(),
        'branch': git(root, 'symbolic-ref', '-q', 'HEAD', allowed=(0, 1)).decode().strip(),
        'index': hashlib.sha256(git(root, 'ls-files', '--stage', '-z')).hexdigest(),
    }


class Spotlight:
    def __init__(self, base):
        self.base = base
        self.root = git_path(base, 'spotlight')
        self.state_path = self.root / 'active.json'
        self.cache = {}

    @contextmanager
    def lock(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (self.root / 'lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def load(self):
        if not self.state_path.exists():
            return None
        return json.loads(self.state_path.read_text())

    def save(self, state):
        save_json(self.state_path, state)

    def objects(self, state):
        return self.root / 'sessions' / state['session'] / 'objects'

    def entry(self, root, name, state):
        path = safe_path(root, name)
        try:
            info = path.lstat()
        except (FileNotFoundError, NotADirectoryError):
            return None
        if stat.S_ISDIR(info.st_mode):
            return {'kind': 'directory'}
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
            raise SpotlightError(f'Unsupported special file: {path}')
        signature = (info.st_ino, info.st_dev, info.st_mtime_ns, info.st_ctime_ns,
                     info.st_size, info.st_mode)
        key = (str(root), name)
        cached = self.cache.get(key)
        if cached and cached[0] == signature:
            return cached[1]
        if stat.S_ISLNK(info.st_mode):
            data = os.fsencode(os.readlink(path))
            kind, mode = 'symlink', 0o777
        else:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, 'rb') as stream:
                data = stream.read()
                after = os.fstat(stream.fileno())
            if (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                    info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns):
                raise RetrySnapshot(f'File changed while reading; retry: {path}')
            kind, mode = 'file', stat.S_IMODE(info.st_mode)
        digest = hashlib.sha256(data).hexdigest()
        blob = self.objects(state) / digest
        if not blob.exists():
            atomic_bytes(blob, data)
        entry = {'kind': kind, 'mode': mode, 'blob': digest}
        self.cache[key] = (signature, entry)
        return entry

    def snapshot(self, root, state):
        repository_ready(root)
        before = identity(root)
        names = set()
        for record in git(root, 'ls-files', '--stage', '-z').split(b'\0'):
            if not record:
                continue
            header, name = record.split(b'\t', 1)
            mode, _, stage = header.split()
            if mode == b'160000':
                raise SpotlightError('Submodules are not supported by Spotlight yet.')
            if stage != b'0':
                raise SpotlightError(f'Resolve merge conflicts in {root} first.')
            names.add(os.fsdecode(name))
        names.update(os.fsdecode(n) for n in git(
            root, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0') if n)
        result = {}
        for name in sorted(names):
            try:
                entry = self.entry(root, name, state)
            except (FileNotFoundError, NotADirectoryError) as error:
                raise RetrySnapshot(f'Source files changed while reading: {root}') from error
            if entry and entry['kind'] != 'directory':
                result[name] = entry
            elif entry:
                # A tracked file may be replaced by a directory containing new files.
                if not any(other.startswith(name + '/') for other in names):
                    raise SpotlightError(f'Unsupported directory or nested repository: {root / name}')
        repository_ready(root)
        if identity(root) != before:
            raise RetrySnapshot(f'Source Git state changed while reading: {root}')
        return result

    def check_identity(self, state):
        repository_ready(self.base)
        if identity(self.base) != state['identity']:
            raise SpotlightError('The base HEAD, branch, or index changed. Restore its original Git '
                                 'state before continuing; Spotlight has kept its recovery data.')

    def observed(self, state, target):
        names = set(state['current']) | set(target)
        if state.get('pending'):
            names |= set(state['pending'])
        return {name: self.entry(self.base, name, state) for name in names}

    def conflicts(self, state, actual):
        conflicts = {}
        for name, entry in actual.items():
            allowed = [state['current'].get(name)]
            if state.get('pending') is not None:
                allowed.append(state['pending'].get(name))
            # Directories are structural, checked for unmanaged contents in preflight.
            if entry and entry['kind'] == 'directory' and None in allowed:
                continue
            if entry not in allowed:
                conflicts[name] = entry
        return conflicts

    def preflight(self, state, target, actual):
        managed = set(state['current']) | set(state.get('pending') or {})
        for name in target:
            path = safe_path(self.base, name)
            for parent in path.parents:
                if parent == self.base:
                    break
                if parent.exists() and not parent.is_dir():
                    relative = parent.relative_to(self.base).as_posix()
                    if relative not in managed or relative in target:
                        raise SpotlightError(f'Unmanaged parent blocks sync: {parent}')
            if path.is_dir() and not path.is_symlink():
                if target[name]['kind'] == 'symlink':
                    raise SpotlightError(f'Directory-to-symlink transitions are not supported: {name!r}')
                for folder, dirs, files in os.walk(path, followlinks=False):
                    for child in files + [d for d in dirs if (Path(folder) / d).is_symlink()]:
                        relative = (Path(folder) / child).relative_to(self.base).as_posix()
                        if relative not in managed or relative in target:
                            raise SpotlightError(f'Unmanaged directory contents block sync: {relative}')
        new_names = set(target) - set(state['original']) - managed
        if new_names:
            ignored = git(self.base, 'check-ignore', '--no-index', '-z', '--stdin',
                          input=b''.join(os.fsencode(n) + b'\0' for n in sorted(new_names)),
                          allowed=(0, 1))
            if ignored:
                raise SpotlightError('Source files collide with base ignore rules: ' +
                                     ', '.join(repr(os.fsdecode(n)) for n in ignored.split(b'\0') if n))

    def write_entry(self, state, name, entry):
        path = safe_path(self.base, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir() and not path.is_symlink():
            # Preflight proved all remaining contents were managed and removed.
            for folder, dirs, _ in os.walk(path, topdown=False):
                for directory in dirs:
                    (Path(folder) / directory).rmdir()
            path.rmdir()
        data = (self.objects(state) / entry['blob']).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['blob']:
            raise SpotlightError('Recovery object checksum mismatch; no overwrite performed.')
        if entry['kind'] == 'symlink':
            temp = path.parent / ('.spotlight-' + uuid.uuid4().hex)
            try:
                os.symlink(os.fsdecode(data), temp)
                os.replace(temp, path)
                sync_directory(path.parent)
            finally:
                if os.path.lexists(temp):
                    temp.unlink()
        else:
            atomic_bytes(path, data, entry['mode'])

    def apply(self, state, target, save_conflicts=False):
        self.check_identity(state)
        actual = self.observed(state, target)
        conflicts = self.conflicts(state, actual)
        if conflicts and not save_conflicts:
            raise SpotlightError('Base edits or file collisions detected: ' +
                                 ', '.join(repr(n) for n in sorted(conflicts)[:8]) +
                                 '. Move those edits aside, or use off --save-conflicts to back them up.')
        self.preflight(state, target, actual)
        if conflicts:
            if any(e and e['kind'] == 'directory' for e in conflicts.values()):
                raise SpotlightError('Move conflicting directories aside before detaching.')
            backup = self.root / 'recovered' / (time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
            for name, entry in conflicts.items():
                if entry:
                    # Store symlink targets as ordinary bytes, never follow restored links.
                    destination = safe_path(backup / 'files', name)
                    atomic_bytes(destination, (self.objects(state) / entry['blob']).read_bytes(), 0o600)
            save_json(backup / 'manifest.json', conflicts)
            print(f'Base edits saved to {backup}', flush=True)
        # Write-ahead journal permits recovery after any partially completed file update.
        # Rebase the journal on observed files so recovery can itself be interrupted
        # without forgetting additions from an earlier, partially applied target.
        state['current'] = {name: entry for name, entry in actual.items()
                            if entry and entry['kind'] != 'directory'}
        state['pending'] = target
        self.save(state)
        for name in sorted(actual, key=lambda n: (-n.count('/'), n)):
            entry = actual[name]
            if entry and entry['kind'] != 'directory' and name not in target:
                path = safe_path(self.base, name)
                if self.entry(self.base, name, state) != entry:
                    raise SpotlightError(f'Base changed during sync: {name!r}')
                path.unlink()
                sync_directory(path.parent)
                parent = path.parent
                while parent != self.base:
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
        for name, entry in sorted(target.items()):
            if actual.get(name) != entry:
                # Recheck immediately before writes to catch ordinary concurrent edits.
                now = self.entry(self.base, name, state)
                previous = actual.get(name)
                if now != previous and not (previous and previous['kind'] == 'directory' and now is None):
                    raise SpotlightError(f'Base changed during sync: {name!r}')
                self.write_entry(state, name, entry)
        state['current'] = target
        state['pending'] = None
        state['error'] = None
        state['waiting'] = None
        state['updated_at'] = time.time()
        self.save(state)

    def source(self, value):
        records = worktrees(self.base)
        path = Path(value).expanduser().resolve()
        matches = [Path(r['worktree']).resolve() for r in records
                   if Path(r['worktree']).resolve() == path or r.get('branch') == 'refs/heads/' + value]
        if len(matches) != 1 or not matches[0].is_dir():
            raise SpotlightError('Choose an existing worktree path or its exact branch name; see spotlight list.')
        source = matches[0]
        if source == self.base or self.base in source.parents or source in self.base.parents:
            raise SpotlightError('Source and base must be separate, non-nested worktrees.')
        return source

    def on(self, value, once, interval):
        source = self.source(value)
        state = self.load()
        if state and state.get('pending') is not None:
            raise SpotlightError('An interrupted sync needs recovery. Run spotlight off first.')
        fresh = state is None
        if fresh:
            repository_ready(self.base)
            if git(self.base, 'status', '--porcelain', '--untracked-files=all'):
                raise SpotlightError('Base checkout must be clean, including non-ignored untracked files. '
                                     'Commit or stash your own work before attaching.')
            state = {'version': 1, 'session': uuid.uuid4().hex, 'base': str(self.base),
                     'identity': identity(self.base), 'original': {}, 'current': {}, 'pending': None}
            state['original'] = self.snapshot(self.base, state)
            state['current'] = state['original']
        target = self.snapshot(source, state)
        # Preflight before changing the active source or stopping a working watcher.
        self.check_identity(state)
        actual = self.observed(state, target)
        if self.conflicts(state, actual):
            raise SpotlightError('Base edits or file collisions detected. Resolve them or run off --save-conflicts.')
        self.preflight(state, target, actual)
        state.update(source=str(source), token=uuid.uuid4().hex, watcher_pid=None,
                     interval=interval, error=None)
        self.save(state)
        self.apply(state, target)
        if not once:
            log = self.root / 'watcher.log'
            with log.open('ab') as output:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                            '--base', str(self.base), '_watch', state['token']],
                                           stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                           start_new_session=True, close_fds=True)
            state['watcher_pid'] = process.pid
            self.save(state)
        print(f"Spotlighting {source}\nBase: {self.base}\n" +
              ('Snapshot only; use spotlight sync to refresh.' if once else 'Watching for changes in the background.'))

    def sync(self):
        state = self.load()
        if not state:
            raise SpotlightError('Spotlight is off.')
        if state.get('pending') is not None:
            raise SpotlightError('An interrupted sync needs recovery. Run spotlight off.')
        source = self.source(state['source'])
        target = self.snapshot(source, state)
        self.apply(state, target)

    def off(self, save_conflicts):
        state = self.load()
        if not state:
            print('Spotlight is already off.')
            return
        self.apply(state, state['original'], save_conflicts)
        self.state_path.unlink()
        sync_directory(self.root)
        shutil.rmtree(self.root / 'sessions' / state['session'])
        print(f'Restored {self.base}. Spotlight is off.')

    def watch(self, token):
        lease = self.root / ('watcher-' + token + '.lock')
        try:
            with lease.open('a') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.watch_loop(token)
        finally:
            lease.unlink(missing_ok=True)

    def watch_loop(self, token):
        while True:
            with self.lock():
                state = self.load()
                if not state or state['token'] != token:
                    return
                if state.get('error'):
                    return
                try:
                    self.sync()
                except RetrySnapshot as error:
                    state = self.load()
                    state['waiting'] = str(error)
                    self.save(state)
                except (SpotlightError, OSError) as error:
                    state = self.load()
                    state['error'] = str(error)
                    self.save(state)
                    print(f'Spotlight paused: {error}', flush=True)
                    return
                interval = state['interval']
            time.sleep(interval)

    def status(self, as_json):
        state = self.load()
        result = {'active': bool(state), 'base': str(self.base)}
        if state:
            alive = False
            lease = self.root / ('watcher-' + state['token'] + '.lock')
            if lease.exists():
                with lease.open('a') as stream:
                    try:
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        alive = True
            result.update(source=state['source'], watching=alive and not state.get('error'),
                          error=state.get('error'), waiting=state.get('waiting'),
                          recovery_required=state.get('pending') is not None,
                          updated_at=state.get('updated_at'), recovery_directory=str(self.root))
        if as_json:
            print(json.dumps(result))
        elif not state:
            print(f'Spotlight is off. Base: {self.base}')
        else:
            print(f"Source: {result['source']}\nBase: {self.base}\n" +
                  ('Watching' if result['watching'] else 'Paused / snapshot only'))
            if result['error']:
                print(f"Reason: {result['error']}")
            if result['waiting']:
                print(f"Waiting: {result['waiting']}")
            if result['recovery_required']:
                print('Interrupted sync. Run spotlight off to restore.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=Path.cwd(),
                        help='Any directory in the repository (defaults to current directory).')
    parser.add_argument('--version', action='version', version='spotlight 0.1.0')
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('list', help='List registered worktrees')
    listing.add_argument('--json', action='store_true')
    attach = commands.add_parser('on', help='Mirror a worktree and watch it; also switches source')
    attach.add_argument('worktree', help='Worktree path or exact branch name')
    attach.add_argument('--once', action='store_true', help='Mirror once without a background watcher')
    attach.add_argument('--interval', type=float, default=1.0, help='Polling interval in seconds (default: 1)')
    status = commands.add_parser('status', help='Show active source and watcher state')
    status.add_argument('--json', action='store_true')
    commands.add_parser('sync', help='Refresh an active preview once')
    for name in ('off', 'recover'):
        detach = commands.add_parser(name, help='Stop watching and restore the original base files')
        detach.add_argument('--save-conflicts', action='store_true',
                            help='Back up edits to mirrored base files before restoring')
    watcher = commands.add_parser('_watch', help='Internal background watcher (started by on)')
    watcher.add_argument('token')
    args = parser.parse_args(argv)
    try:
        base = base_checkout(args.base.resolve())
        spotlight = Spotlight(base)
        if args.command == '_watch':
            spotlight.watch(args.token)
            return 0
        with spotlight.lock():
            if args.command == 'list':
                records = worktrees(base)
                if args.json:
                    print(json.dumps(records))
                else:
                    for record in records:
                        branch = record.get('branch', '(detached)').removeprefix('refs/heads/')
                        marker = ' [base]' if Path(record['worktree']).resolve() == base else ''
                        print(f"{record['worktree']}  {branch}{marker}")
            elif args.command == 'on':
                if not 0.1 <= args.interval <= 3600:
                    raise SpotlightError('Interval must be between 0.1 and 3600 seconds.')
                spotlight.on(args.worktree, args.once, args.interval)
            elif args.command == 'status':
                spotlight.status(args.json)
            elif args.command == 'sync':
                spotlight.sync()
                print('Spotlight refreshed.')
            else:
                spotlight.off(args.save_conflicts)
        return 0
    except (SpotlightError, OSError, ValueError) as error:
        print(f'spotlight: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
