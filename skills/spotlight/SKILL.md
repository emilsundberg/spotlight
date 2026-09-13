---
name: spotlight
description: Mirror a Git worktree into the main checkout for local testing with the Spotlight CLI. Use when asked to spotlight, preview, attach, switch, detach, or recover a worktree preview, including worktrees created by T3 Code, Herdr, or Conductor.
---

# Spotlight worktree previews

Use the `spotlight` CLI for an explicitly requested worktree preview. It mirrors source files one way into the main checkout while preserving the main checkout's Git HEAD and index. It does not create commits or copy changes back to the source.

## Workflow

- Run `spotlight status --json` and `spotlight list --json` in the repository first. Commands also work from a linked worktree; the main checkout is discovered automatically. Outside the repository, use `spotlight --base /path/to/repo <command>`.
- Attach or switch with `spotlight on /absolute/path/to/worktree`. Exact branch names also work. It starts a background watcher; the command returns immediately.
- Make code changes and commits **in the source worktree**. Run the existing local app from the main checkout. While attached, the main checkout intentionally looks dirty against its original branch: do not stage, commit, stash, reset, clean, switch branches, or run an agent that edits it.
- Check `spotlight status --json` after attaching or when preview changes stop appearing. `active` means files are mirrored; `watching` indicates watcher availability. A paused session is still attached.
- Detach when requested with `spotlight off`. `spotlight recover` performs the same restoration after an interrupted sync or crashed watcher. Do not detach a user's existing preview merely because an unrelated task ended.

## Constraints and recovery

The initial main checkout must be clean, including non-ignored untracked files. Do not automatically stash or discard the user's work to satisfy that requirement. Ignored files, dependencies, and runtime files stay local. Incoming files that collide with ignored paths are rejected.

If base-file edits pause syncing, inspect the reported paths. When the user asks to detach and preserve those edits, use `spotlight off --save-conflicts`: it saves conflicting bytes plus a manifest under the Git metadata directory's `spotlight/recovered/`, then restores the original files. Report that backup location. Deleted files are represented by null in the manifest; symlink targets are stored as ordinary text bytes. Unmanaged directory collisions must be moved aside manually without losing their contents.

If Git HEAD or the index changed in the base, stop and inspect the situation; do not force-reset it. Recovery data remains in Git metadata. Never delete the active session's metadata to bypass a refusal.

Switching files does not undo migrations, database writes, installed dependencies, or process state. Follow the target project's existing development-server instructions. Do not automatically migrate, install dependencies, restart servers, or run production builds just because Spotlight switched worktrees.

Use `spotlight on <worktree> --once` for a snapshot without watching, and `spotlight sync` to refresh it. To resume watching after resolving a pause, run `spotlight on <same-worktree>` again. Only one source is active per repository. Submodules, sparse checkouts, nested source/base directories, and in-progress Git operations are unsupported and rejected.

If `spotlight` is missing, locate the user's existing Spotlight checkout and run `python3 install.py` there, or invoke its `spotlight.py` directly. The skill is CLI-independent of the worktree creator; no T3 Code, Herdr, or Conductor integration is needed.
