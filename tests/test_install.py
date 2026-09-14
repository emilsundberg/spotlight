import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import shutil
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def test_install_and_reinstall_links_cli_and_skills(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for _ in range(2):
                installer.install(root / 'bin', [root / 'codex', root / 'claude'])
            self.assertEqual((root / 'bin/spotlight').resolve(), (ROOT / 'spotlight.py').resolve())
            self.assertTrue((root / 'codex/spotlight/SKILL.md').is_file())
            self.assertTrue((root / 'claude/spotlight/SKILL.md').is_file())

    def test_conflict_prevents_partial_install(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'skills').mkdir()
            (root / 'skills/spotlight').write_text('existing skill')
            with self.assertRaises(SystemExit):
                installer.install(root / 'bin', [root / 'skills'])
            self.assertFalse(os.path.lexists(root / 'bin/spotlight'))
            self.assertEqual((root / 'skills/spotlight').read_text(), 'existing skill')

    def test_standalone_skill_installs_and_runs_without_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            skill = home / '.agents/skills/spotlight'
            shutil.copytree(ROOT / 'skills/spotlight', skill)
            (skill / 'scripts/spotlight.py').chmod(0o644)
            env = dict(os.environ, HOME=str(home))
            result = subprocess.run([sys.executable, str(skill / 'scripts/install.py')],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((home / '.claude/skills/spotlight').resolve(), skill)
            self.assertEqual((home / '.local/bin/spotlight').resolve(), skill / 'scripts/spotlight.py')
            result = subprocess.run([str(home / '.local/bin/spotlight'), '--version'],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('0.2.0', result.stdout)

    def test_failed_install_rolls_back_created_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'blocked').write_text('not a directory')
            with self.assertRaises(OSError):
                installer.install(root / 'bin', [root / 'blocked/skills'])
            self.assertFalse(os.path.lexists(root / 'bin/spotlight'))

    def test_default_install_migrates_only_our_legacy_alias(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            legacy = home / '.codex/skills/spotlight'
            legacy.parent.mkdir(parents=True)
            legacy.symlink_to(ROOT / 'skills/spotlight')
            with patch.object(Path, 'home', return_value=home):
                installer.install(home / 'bin', installer.default_skill_dirs())
            self.assertFalse(os.path.lexists(legacy))
            self.assertEqual((home / '.agents/skills/spotlight').resolve(), ROOT / 'skills/spotlight')


if __name__ == '__main__':
    unittest.main()
