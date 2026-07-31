## Skill installation

The `/wp-post` skill in `skills/wp-post/` is installed by `./install.sh`,
which copies it to `~/.claude/skills/wp-post/` alongside the CLI. It is a
copy, not a symlink, so a change to `skills/` does not reach the installed
skill until `./install.sh` is run again. Mention that when a change to the
skill needs to take effect.

## Committing

Proactively commit and push completed work without waiting to be asked.
