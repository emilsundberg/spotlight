# Spotlight

Preview any Git worktree through your main checkout's existing development server. Attach, switch sources, and detach without changing branches or making checkpoint commits.

Requires **Git and Python 3.10+** on macOS or Linux. No Python packages or file-watcher dependencies.

## Install

```sh
gh repo clone emilsundberg/spotlight ~/Code/spotlight
cd ~/Code/spotlight
python3 install.py
```

This links `~/.local/bin/spotlight` and installs the agent skill in `${CODEX_HOME:-~/.codex}/skills/spotlight`. Keep the checkout in place and ensure `~/.local/bin` is on your `PATH`. New agent sessions can discover the skill.

To install for additional compatible agents, supply their skill discovery directories explicitly:

```sh
python3 install.py --skill-dir ~/.codex/skills --skill-dir ~/.claude/skills
```

The portable skill lives at [`skills/spotlight/SKILL.md`](skills/spotlight/SKILL.md). Agents without automatic skill discovery can read that file directly. Installation refuses to overwrite an existing unrelated command or skill. Pull this repository to update the linked installation.

## Use

From the main checkout or any linked worktree:

```sh
spotlight list
spotlight on /path/to/worktree
spotlight status
spotlight on another-branch
spotlight off
```

Use `spotlight --base /path/to/repo …` from elsewhere. `on` accepts a registered worktree path or exact branch name, including worktrees created by T3 Code, Herdr, Conductor, or Git itself. It discovers the repository's main checkout automatically.

`on` mirrors immediately and starts a background poller (one second by default). Switching to another source retires the old watcher. `on <source> --once` makes a snapshot without watching; `sync` refreshes an existing preview once. `list --json` and `status --json` support agent use. `--interval 0.5` changes the watcher interval.

The watcher waits while Git operations are in progress or source files change during a read, then retries automatically. `status` reports that waiting state. Persistent file conflicts pause the watcher and require attention.

**Edit and commit in the source worktree; test in the main checkout.** The main checkout stays on its original branch and its index stays unchanged. Its Git diff therefore shows the preview against that original branch. Do not stage, commit, stash, reset, clean, or switch branches there while Spotlight is active. Use one mirroring tool at a time.

The main checkout must initially be clean, including non-ignored untracked files. Commit or stash your own work before attaching. Spotlight never stashes it automatically.

## What gets mirrored

- Committed, staged, and unstaged source file contents, including deletions.
- New untracked files, respecting Git ignore rules.
- Binary files, executable permissions, and file symlinks.

Git metadata is never mirrored. Ignored files such as `.env`, `node_modules`, `vendor`, and runtime caches stay in the base checkout when covered by its ignore rules. An incoming new file that would collide with an ignored base path is rejected. Non-ignored tracked assets are still mirrored.

The existing development server can keep watching the base path. Spotlight does not run builds, commands, migrations, dependency installation, or server restarts. Detaching restores files, not database or process state. In-memory workers may still require your normal reload procedure.

## Detach and recover

```sh
spotlight off
# Same restoration after a crash or interrupted sync:
spotlight recover
```

A durable journal and content snapshots live inside the main checkout's Git metadata at `spotlight/`. File writes use atomic replacement and a write-ahead journal. Detach restores the original files and removes additions made by the preview. Unrelated files created in the base while previewing remain there.

Edits to mirrored base files pause syncing before overwriting them. `status` reports the error. To detach while preserving those edits:

```sh
spotlight off --save-conflicts
```

Conflicting bytes are saved under `spotlight/recovered/<timestamp>/files` in Git metadata with a `manifest.json` describing paths, permissions, symlinks, and deletions. Symlink targets are saved as ordinary bytes rather than active symlinks. The command prints the backup location. These backups can contain private code or secrets; they stay local and can be removed manually once no longer needed.

Move unmanaged directory collisions aside before detaching. If someone changed the main checkout's branch, HEAD, or index, Spotlight refuses to overwrite files until the original Git state is restored. Inspect the session's `active.json` and resolve that Git change deliberately; do not delete recovery data or blindly reset the checkout.

To resume a paused or crashed watcher after fixing the cause, run `on` with the same source again. Recover an interrupted file update with `off` first. Closing the terminal does not detach; neither does a watcher crash. After a machine restart, use `status`, then `on` to resume or `off` to restore.

## Boundaries

- A non-bare main checkout and separate, registered source worktree are required.
- Submodules, sparse checkouts, assume-unchanged/skip-worktree flags, and in-progress Git operations are rejected.
- Source/base nesting, directory-to-symlink transitions, and writes through symlinked parent directories are rejected.
- Mirroring is per-file, not a filesystem-wide atomic snapshot. Avoid editing the base concurrently; a watcher is not an operating-system write lock. Base changes are checked before syncing and again immediately before each write.
- Polling fingerprints files and reuses unchanged content. Large repositories or large generated files can make a scan take longer than the configured interval.
- A snapshot reflects working files, not Git clean/smudge transformations. The base's dependency installations remain its own.

## Develop

```sh
python3 -m unittest discover -s tests -v
```

Tests use disposable repositories, including background watcher and interrupted-sync recovery tests. CI runs on Linux and macOS with Python 3.10 and 3.13.
