#!/usr/bin/env python3
"""Install Spotlight and its skill for Codex and Claude Code. No dependencies."""
import argparse
import os
from pathlib import Path
import sys


def default_skill_dirs():
    return [Path.home() / '.agents/skills', Path.home() / '.claude/skills']


def install(bin_dir, skill_dirs):
    if sys.version_info < (3, 10):
        raise SystemExit('Spotlight requires Python 3.10 or newer.')
    skill = Path(__file__).resolve().parent.parent
    links = [(bin_dir.expanduser().absolute() / 'spotlight', skill / 'scripts/spotlight.py')]
    links += [(directory.expanduser().absolute() / 'spotlight', skill) for directory in skill_dirs]
    links = list(dict.fromkeys(links))
    for destination, target in links:
        if os.path.lexists(destination) and destination.resolve() != target:
            raise SystemExit(f'Refusing to overwrite {destination}; move it aside first.')
    executable = skill / 'scripts/spotlight.py'
    # Skill archives may not preserve executable permissions.
    if not os.access(executable, os.X_OK):
        executable.chmod(executable.stat().st_mode | 0o100)
    created = []
    try:
        for destination, target in links:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not os.path.lexists(destination):
                destination.symlink_to(target, target_is_directory=target.is_dir())
                created.append(destination)
    except OSError:
        for destination in reversed(created):
            destination.unlink()
        raise
    for destination, target in links:
        print(f'{destination} -> {target}')
    # Retire only our own old alias, after the standard Codex location is installed.
    legacy = Path.home() / '.codex/skills/spotlight'
    shared = Path.home() / '.agents/skills/spotlight'
    if (shared in [destination for destination, _ in links] and legacy.is_symlink()
            and legacy.resolve() == skill and legacy not in [d for d, _ in links]):
        legacy.unlink()
    print('Installed. Keep this skill folder in place; new agent sessions can discover it.')
    if str(bin_dir.expanduser().absolute()) not in os.environ.get('PATH', '').split(os.pathsep):
        print(f'Add {bin_dir.expanduser().absolute()} to PATH, or invoke its spotlight command by absolute path.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', type=Path, default=Path.home() / '.local/bin')
    parser.add_argument('--skill-dir', type=Path, action='append',
                        help='Override skill directories; repeat for multiple agents.')
    args = parser.parse_args()
    install(args.bin_dir, args.skill_dir if args.skill_dir is not None else default_skill_dirs())
