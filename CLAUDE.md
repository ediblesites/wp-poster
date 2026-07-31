## Skill installation

The `/wp-post` skill in `skills/wp-post/` is installed by `install.sh`,
which copies it into `.claude/skills/wp-post/` of whichever directory the
script is run from - project scope, not user scope. It is a copy, not a
symlink, so a change to `skills/` does not reach any installed copy until
`install.sh` is run again in that project. Mention that when a change to
the skill needs to take effect.

## Committing

Proactively commit and push completed work without waiting to be asked.
