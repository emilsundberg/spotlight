---
name: spotlight
description: Install or use Spotlight to preview a Git worktree through the main checkout's local app. Use for spotlight, worktree mirroring, testing an agent's worktree in the existing dev server, switching previews, or detaching them. Works with Git, T3 Code, Herdr, and Conductor worktrees.
---

# Spotlight

Run commands from the project directory. Spotlight uses Git to detect the current checkout and the real main checkout, including from subdirectories. Never infer either from a folder name or the branch name `main`.

```sh
spotlight status --json  # Reports checkout, role (main/worktree), base, and active source
spotlight on             # Preview this worktree; starts a background watcher
spotlight off            # Restore the main checkout
```

In the main checkout, `on` resumes the active source or selects the sole available worktree. If several exist, use `spotlight list` and `spotlight on <branch-or-path>` for the user's intended source. Do not pick an arbitrary worktree. An explicit worktree path also works from outside a repository. `spotlight` alone shows status.

If the command is missing, this skill already contains the entire app. Run `python3 <this-skill-directory>/scripts/install.py` by absolute path. It installs the command at `~/.local/bin/spotlight` and registers the skill for Codex and Claude Code. If PATH has not picked it up, invoke that absolute command path or `python3 <this-skill-directory>/scripts/spotlight.py` directly. Do not change to the skill's directory to preview a project. Requires Git and Python 3.10+; no package install is needed.

Edit and commit **in the source worktree**; run the existing app in the main checkout. While attached, the main checkout intentionally looks dirty. Do not edit, stage, commit, stash, reset, clean, or switch its branch. Attach/switch/detach when requested; do not change an existing preview just because an unrelated task ends.

The main checkout must initially be clean. Never discard or automatically stash the user's work. Ignored local files stay local. `status --json` reports `waiting` for temporary Git activity and `error` for a pause needing attention.

After an interruption, `off` restores files without needing the source worktree. If base edits block detaching, `off --save-conflicts` backs them up before restoration; use it when preserving those edits while detaching is requested, and report the printed backup path. Unmanaged directory collisions or changed base HEAD/index need inspection; never bypass them with reset/clean or by deleting recovery data. After resolving a pause, use `on` to resume watching.

Spotlight restores files, not databases, dependencies, or process state. Follow the project's server instructions; switching a preview does not authorize migrations, builds, dependency installation, or restarts.
