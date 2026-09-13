import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

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
            self.assertEqual((root / 'bin/spotlight').resolve(), ROOT / 'spotlight.py')
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


if __name__ == '__main__':
    unittest.main()
