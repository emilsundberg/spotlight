# Spotlight

Run your agent's worktree through your existing local app. Git tells Spotlight which checkout is the real main checkout and which is the worktree.

```sh
# Anywhere inside the worktree, including a subdirectory:
spotlight on

# From either checkout:
spotlight       # Where am I? What is being previewed?
spotlight off   # Restore the main checkout
```

In the main checkout, `on` resumes the active preview or selects the only available worktree. When several are available it requires an explicit choice:

```sh
spotlight list
spotlight on feature-branch
```

`spotlight on /path/to/worktree` also works from outside the repository. T3 Code, Herdr, Conductor, and manually created Git worktrees all work. No per-project configuration.

## Install once

Requires Git and Python 3.10+ on macOS or Linux. Access to this private repo is required to download it.

```sh
gh repo clone emilsundberg/spotlight ~/Code/spotlight
python3 ~/Code/spotlight/install.py
```

This installs `~/.local/bin/spotlight` and registers the skill in `~/.agents/skills` for Codex and `~/.claude/skills` for Claude Code. Keep the checkout in place. The installer reports if `~/.local/bin` needs adding to PATH and refuses to overwrite unrelated tools or skills. Run it again safely after pulling updates.

**An agent can install the skill alone** from `emilsundberg/spotlight`, path `skills/spotlight`. The skill includes the entire CLI and installer; its instructions explain how to make the command available automatically. Once discovered, ask “Spotlight this worktree.” Other agents must support local skills or explicitly read `skills/spotlight/SKILL.md`; a private app cannot be known before installation.

Skill locations follow the [Codex](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills) and [Claude Code](https://code.claude.com/docs/en/skills) conventions. Use `--skill-dir /custom/skills` (repeatable) or `--bin-dir /custom/bin` to override installation destinations.

## Keep your work safe

- Start with a clean main checkout. Edit and commit in the **source worktree** while previewing; the main checkout's Git diff shows the preview.
- File contents, additions, deletions, executable permissions, and symlinks are mirrored. Ignored local files and Git metadata stay local.
- Base edits pause syncing; they are not silently overwritten. `spotlight off --save-conflicts` backs up conflicting edits, prints the backup path, and restores the original files.
- `off` also recovers interrupted syncs and crashed watchers, even if the source disappeared. Recovery data lives in Git metadata. A changed base HEAD/index or unmanaged directory collision requires inspection, not a forced reset.
- Existing app processes stay running. Database changes, dependencies, and process state are outside file restoration.

Mirroring is per-file, not a filesystem-wide lock. Submodules, sparse checkouts, nested source/base directories, directory-to-symlink transitions, and writes through symlinked parents are refused. Temporary Git activity waits and retries. Do not run another mirroring tool or edit the base concurrently.

`status --json` reports the detected `checkout`, its `role`, the `base`, and preview state. `--base /path/to/repo` selects an explicit repository context. For advanced use, `on --once` takes a snapshot, `sync` refreshes it, `on --interval 0.5` changes polling, and `recover` is an alias for `off`.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests use disposable repositories. CI covers macOS and Linux with Python 3.10 and 3.13.
