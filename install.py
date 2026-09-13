#!/usr/bin/env python3
"""Install local symlinks to the CLI and agent skill; never overwrite another tool."""
import argparse
import os
from pathlib import Path


def install(bin_dir, skill_dirs):
    source = Path(__file__).resolve().parent
    links = [(bin_dir.expanduser() / 'spotlight', source / 'spotlight.py')]
    links += [(directory.expanduser() / 'spotlight', source / 'skills/spotlight')
              for directory in skill_dirs]
    for destination, target in links:
        if os.path.lexists(destination) and not (
                destination.is_symlink() and destination.resolve() == target):
            raise SystemExit(f'Refusing to overwrite {destination}; move it aside first.')
    for destination, target in links:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_symlink():
            destination.symlink_to(target, target_is_directory=target.is_dir())
        print(f'{destination} -> {target}')
    print('Keep this checkout in place. Ensure the bin directory is on PATH.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', type=Path, default=Path.home() / '.local/bin')
    parser.add_argument('--skill-dir', type=Path, action='append',
                        help='Skill discovery directory; repeat for multiple agents. Default: Codex skills.')
    args = parser.parse_args()
    default_skills = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'skills'
    install(args.bin_dir, args.skill_dir if args.skill_dir is not None else [default_skills])
