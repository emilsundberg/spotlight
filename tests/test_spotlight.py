import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

CLI = Path(__file__).resolve().parents[1] / 'spotlight.py'
spec = importlib.util.spec_from_file_location('spotlight', CLI)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SpotlightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'base checkout'
        self.source = self.root / 'agent worktree'
        self.other = self.root / 'other worktree'
        self.base.mkdir()
        self.git(self.base, 'init', '-b', 'main')
        self.git(self.base, 'config', 'user.name', 'Spotlight Test')
        self.git(self.base, 'config', 'user.email', 'test@example.invalid')
        self.write(self.base, '.gitignore', '.env\nnode_modules/\nruntime/\n')
        self.write(self.base, 'app.txt', 'original\n')
        self.write(self.base, 'delete.txt', 'keep me\n')
        self.git(self.base, 'add', '.')
        self.git(self.base, 'commit', '-m', 'initial')
        self.git(self.base, 'worktree', 'add', '-b', 'feature', str(self.source))
        self.git(self.base, 'worktree', 'add', '-b', 'other', str(self.other))
        self.original_identity = module.identity(self.base)
        self.write(self.base, '.env', 'BASE_SECRET=local\n')
        self.write(self.base, 'node_modules/cache', 'base dependencies\n')
        self.addCleanup(self.stop_watcher)

    def stop_watcher(self):
        state = self.base / '.git/spotlight/active.json'
        if state.exists():
            state.unlink()
        # Watchers exit on their next iteration; don't remove the repo while they are reading it.
        time.sleep(0.12)

    def git(self, root, *args):
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return result.stdout

    def write(self, root, name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def cli(self, *args, success=True, cwd=None):
        result = subprocess.run([sys.executable, str(CLI), *map(str, args)],
                                cwd=cwd or self.base, capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def assert_clean(self):
        self.assertEqual(self.git(self.base, 'status', '--porcelain'), b'')
        self.assertEqual(module.identity(self.base), self.original_identity)
        self.assertEqual((self.base / '.env').read_text(), 'BASE_SECRET=local\n')
        self.assertEqual((self.base / 'node_modules/cache').read_text(), 'base dependencies\n')

    def test_attach_edits_untracked_deletions_and_restore(self):
        self.write(self.source, 'app.txt', 'committed\n')
        self.git(self.source, 'commit', '-am', 'feature commit')
        self.write(self.source, 'app.txt', 'unsaved to git\n')
        self.write(self.source, 'new dir/new\nfile.txt', 'new file\n')
        self.write(self.source, '.env', 'SOURCE_SECRET=hidden\n')
        (self.source / 'delete.txt').unlink()
        source_status = self.git(self.source, 'status', '--porcelain')
        source_identity = module.identity(self.source)
        self.cli('on', self.source, '--once')
        self.assertEqual((self.base / 'app.txt').read_text(), 'unsaved to git\n')
        self.assertFalse((self.base / 'delete.txt').exists())
        self.assertTrue((self.base / 'new dir/new\nfile.txt').exists())
        self.assertEqual(module.identity(self.base), self.original_identity)
        self.assertEqual(module.identity(self.source), source_identity)
        self.assertEqual(self.git(self.source, 'status', '--porcelain'), source_status)
        self.cli('off')
        self.assertFalse((self.base / 'new dir').exists())
        self.assert_clean()

    def test_switch_by_branch_from_source_and_restore_original(self):
        self.write(self.source, 'app.txt', 'first')
        self.write(self.source, 'only-first', 'one')
        self.write(self.other, 'app.txt', 'second')
        self.cli('on', 'feature', '--once', cwd=self.source)
        self.cli('on', 'other', '--once')
        self.assertEqual((self.base / 'app.txt').read_text(), 'second')
        self.assertFalse((self.base / 'only-first').exists())
        self.cli('off', cwd=self.other)
        self.assert_clean()

    def test_dirty_base_and_untracked_base_refused(self):
        self.write(self.base, 'app.txt', 'local work')
        self.cli('on', 'feature', '--once', success=False)
        self.assertEqual((self.base / 'app.txt').read_text(), 'local work')
        self.git(self.base, 'restore', 'app.txt')
        self.write(self.base, 'unknown', 'untracked work')
        self.cli('on', 'feature', '--once', success=False)
        self.assertEqual((self.base / 'unknown').read_text(), 'untracked work')

    def test_conflict_pauses_and_off_saves_edits(self):
        self.write(self.source, 'app.txt', 'preview')
        self.cli('on', 'feature', '--once')
        self.write(self.base, 'app.txt', 'user edit')
        self.write(self.source, 'app.txt', 'next preview')
        self.cli('sync', success=False)
        self.cli('off', success=False)
        self.assertEqual((self.base / 'app.txt').read_text(), 'user edit')
        self.cli('off', '--save-conflicts')
        backups = list((self.base / '.git/spotlight/recovered').glob('*/files/app.txt'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), 'user edit')
        self.assert_clean()

    def test_deleted_base_edit_recorded_in_backup(self):
        self.cli('on', 'feature', '--once')
        (self.base / 'app.txt').unlink()
        self.cli('off', '--save-conflicts')
        manifest = next((self.base / '.git/spotlight/recovered').glob('*/manifest.json'))
        self.assertEqual(json.loads(manifest.read_text()), {'app.txt': None})
        self.assert_clean()

    def test_ignored_collision_refused_even_if_force_tracked_in_source(self):
        self.write(self.source, '.env', 'source secret')
        self.git(self.source, 'add', '-f', '.env')
        self.cli('on', 'feature', '--once', success=False)
        self.assert_clean()
        self.assertFalse((self.base / '.git/spotlight/active.json').exists())

    def test_ignored_new_file_never_installed(self):
        self.write(self.source, 'runtime/new.txt', 'runtime')
        self.git(self.source, 'add', '-f', 'runtime/new.txt')
        self.cli('on', 'feature', '--once', success=False)
        self.assertFalse((self.base / 'runtime').exists())

    def test_unrelated_base_untracked_files_survive_detach(self):
        self.cli('on', 'feature', '--once')
        self.write(self.base, 'notes.txt', 'new local notes')
        self.cli('off')
        self.assertEqual((self.base / 'notes.txt').read_text(), 'new local notes')

    def test_symlink_and_executable_and_binary_roundtrip(self):
        executable = self.write(self.source, 'run.sh', '#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
        os.symlink('app.txt', self.source / 'link')
        (self.source / 'binary').write_bytes(bytes(range(256)))
        self.cli('on', 'feature', '--once')
        self.assertEqual(os.readlink(self.base / 'link'), 'app.txt')
        self.assertEqual((self.base / 'run.sh').stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.base / 'binary').read_bytes(), bytes(range(256)))
        self.cli('off')
        self.assertFalse(os.path.lexists(self.base / 'link'))
        self.assert_clean()

    def test_symlink_parent_cannot_write_outside_base(self):
        outside = self.root / 'outside'
        outside.mkdir()
        self.cli('on', 'feature', '--once')
        os.symlink(outside, self.base / 'escape')
        self.write(self.source, 'escape/file', 'bad')
        self.cli('sync', success=False)
        self.assertFalse((outside / 'file').exists())
        (self.base / 'escape').unlink()
        self.cli('off')
        self.assert_clean()

    def test_file_directory_transitions(self):
        (self.source / 'app.txt').unlink()
        self.write(self.source, 'app.txt/nested', 'inside')
        self.cli('on', 'feature', '--once')
        self.assertEqual((self.base / 'app.txt/nested').read_text(), 'inside')
        self.cli('off')
        self.assert_clean()

    def test_directory_with_unmanaged_content_not_removed(self):
        (self.source / 'app.txt').unlink()
        self.write(self.source, 'app.txt/nested', 'inside')
        self.cli('on', 'feature', '--once')
        self.write(self.base, 'app.txt/local', 'local content')
        self.cli('off', '--save-conflicts', success=False)
        self.assertEqual((self.base / 'app.txt/local').read_text(), 'local content')
        (self.base / 'app.txt/local').unlink()
        self.cli('off')
        self.assert_clean()

    def test_index_change_refuses_restore(self):
        self.write(self.source, 'app.txt', 'preview')
        self.cli('on', 'feature', '--once')
        self.git(self.base, 'add', 'app.txt')
        self.cli('off', success=False)
        self.assertEqual((self.base / 'app.txt').read_text(), 'preview')
        self.git(self.base, 'reset', 'HEAD', '--', 'app.txt')
        self.cli('off')
        self.assert_clean()

    def test_interrupted_sync_recovers_partial_files(self):
        self.write(self.source, 'app.txt', 'preview')
        self.write(self.source, 'new.txt', 'new')
        spotlight = module.Spotlight(self.base)
        real_write = spotlight.write_entry
        count = 0

        def fail_after_write(*args):
            nonlocal count
            real_write(*args)
            count += 1
            if count == 2:
                raise OSError('simulated interruption')

        with spotlight.lock(), patch.object(spotlight, 'write_entry', side_effect=fail_after_write):
            with self.assertRaises(OSError):
                spotlight.on(str(self.source), True, 1)
        self.assertTrue(json.loads(self.cli('status', '--json').stdout)['recovery_required'])
        self.cli('recover')
        self.assert_clean()
        self.assertFalse((self.base / 'new.txt').exists())

    def test_live_watcher_switch_and_detach(self):
        self.cli('on', 'feature', '--interval', '0.1')
        self.write(self.source, 'app.txt', 'live edit')
        self.wait_for(lambda: (self.base / 'app.txt').read_text() == 'live edit')
        self.write(self.other, 'app.txt', 'other live')
        self.cli('on', 'other', '--interval', '0.1')
        self.write(self.source, 'app.txt', 'old source should not sync')
        self.write(self.other, 'app.txt', 'new source sync')
        self.wait_for(lambda: (self.base / 'app.txt').read_text() == 'new source sync')
        self.cli('off')
        time.sleep(0.2)
        self.assert_clean()

    def test_recovery_can_itself_be_interrupted(self):
        self.write(self.source, 'app.txt', 'preview')
        self.write(self.source, 'new-a', 'first addition')
        self.write(self.source, 'new-b', 'second addition')
        spotlight = module.Spotlight(self.base)
        real_write = spotlight.write_entry

        def crash_on_last_write(state, name, entry):
            real_write(state, name, entry)
            if name == 'new-b':
                raise OSError('first crash')

        with spotlight.lock(), patch.object(spotlight, 'write_entry', side_effect=crash_on_last_write):
            with self.assertRaises(OSError):
                spotlight.on(str(self.source), True, 1)
        real_unlink = Path.unlink

        def crash_during_recovery(path, *args, **kwargs):
            real_unlink(path, *args, **kwargs)
            if path == self.base / 'new-a':
                raise OSError('recovery crash')

        with spotlight.lock(), patch.object(Path, 'unlink', crash_during_recovery):
            with self.assertRaises(OSError):
                spotlight.off(False)
        self.assertTrue((self.base / 'new-b').exists())
        self.cli('recover')
        self.assertFalse((self.base / 'new-a').exists())
        self.assertFalse((self.base / 'new-b').exists())
        self.assert_clean()

    def test_directory_to_symlink_refused_before_mutation(self):
        self.write(self.base, 'folder/file', 'original')
        self.git(self.base, 'add', '.')
        self.git(self.base, 'commit', '-m', 'directory')
        self.git(self.source, 'merge', 'main')
        (self.source / 'folder/file').unlink()
        (self.source / 'folder').rmdir()
        os.symlink('app.txt', self.source / 'folder')
        self.cli('on', 'feature', '--once', success=False)
        self.assertEqual((self.base / 'folder/file').read_text(), 'original')
        self.assertEqual(self.git(self.base, 'status', '--porcelain'), b'')

    def test_live_conflict_pauses_without_overwrite(self):
        self.cli('on', 'feature', '--interval', '0.1')
        self.write(self.base, 'app.txt', 'base edit')
        self.wait_for(lambda: bool(json.loads(self.cli('status', '--json').stdout).get('error')))
        self.assertEqual((self.base / 'app.txt').read_text(), 'base edit')
        self.cli('off', '--save-conflicts')
        self.assert_clean()

    def test_live_watcher_waits_for_source_git_operation(self):
        self.cli('on', 'feature', '--interval', '0.1')
        source_lock = module.git_path(self.source, 'index.lock')
        source_lock.touch()
        self.write(self.source, 'app.txt', 'after git operation')
        self.wait_for(lambda: bool(json.loads(self.cli('status', '--json').stdout).get('waiting')))
        self.assertEqual((self.base / 'app.txt').read_text(), 'original\n')
        source_lock.unlink()
        self.git(self.source, 'commit', '-am', 'agent commit')
        self.wait_for(lambda: (self.base / 'app.txt').read_text() == 'after git operation')
        status = json.loads(self.cli('status', '--json').stdout)
        self.assertFalse(status['error'])
        self.assertFalse(status['waiting'])
        self.cli('off')
        self.assert_clean()

    def test_watcher_crash_and_recovery(self):
        self.write(self.source, 'app.txt', 'preview')
        self.cli('on', 'feature', '--interval', '0.1')
        state = json.loads((self.base / '.git/spotlight/active.json').read_text())
        os.kill(state['watcher_pid'], signal.SIGKILL)
        self.wait_for(lambda: not json.loads(self.cli('status', '--json').stdout)['watching'])
        self.cli('recover')
        self.assert_clean()

    def test_git_operation_in_progress_refused(self):
        (self.base / '.git/index.lock').touch()
        self.cli('on', 'feature', '--once', success=False)
        (self.base / '.git/index.lock').unlink()
        self.assert_clean()

    def test_non_worktree_and_base_itself_refused(self):
        self.cli('on', self.base, '--once', success=False)
        self.cli('on', self.root, '--once', success=False)
        self.assert_clean()

    def test_list_and_status_from_worktree(self):
        records = json.loads(self.cli('list', '--json', cwd=self.source).stdout)
        self.assertEqual(len(records), 3)
        self.assertEqual(json.loads(self.cli('status', '--json').stdout)['active'], False)

    def test_staged_deletion_and_new_file_supported(self):
        self.git(self.source, 'rm', 'delete.txt')
        self.write(self.source, 'staged', 'stage')
        self.git(self.source, 'add', 'staged')
        self.cli('on', 'feature', '--once')
        self.assertFalse((self.base / 'delete.txt').exists())
        self.assertEqual((self.base / 'staged').read_text(), 'stage')
        self.cli('off')
        self.assert_clean()

    def test_assume_unchanged_refused(self):
        self.git(self.base, 'update-index', '--assume-unchanged', 'app.txt')
        self.write(self.base, 'app.txt', 'hidden base edit')
        self.cli('on', 'feature', '--once', success=False)
        self.assertEqual((self.base / 'app.txt').read_text(), 'hidden base edit')

    def wait_for(self, predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        self.fail('Timed out waiting for watcher')


if __name__ == '__main__':
    unittest.main()
