# SpinupWP push-to-deploy: runbook notes

Working notes for publishing with wp-post from a SpinupWP deploy script
instead of by hand. Each entry records what was tested and the result. These
notes become the runbook once the setup works end to end.

## Design

- The content lives in the site's own git repo, which SpinupWP checks out
  into the site's `files/` directory (the WordPress root).
- A push to GitHub calls the SpinupWP push-to-deploy webhook. SpinupWP runs
  `git remote update` and `git checkout -f BRANCH`, then the site's Deploy
  Script.
- The Deploy Script runs wp-post on the changed files, on the server, as the
  site user. WP-CLI is local, so cache purge and MSLS linking need no SSH.

## Confirmed

### Server and site user (tested 2026-10-26)

- Site root is `/sites/<domain>/`, WordPress is in `/sites/<domain>/files/`.
  `files/` is the web root.
- The site user owns `files/` and can run `wp` (`/usr/local/bin/wp`) against
  it with `wp --path=$HOME/files`.
- `git` and `python3` (3.12) are installed.
- SpinupWP creates a deploy key for the site at `~/.ssh/git_rsa`.
- The site user has no sudo.

### Keeping content out of the web root (tested 2026-10-26)

With SpinupWP's default nginx config, served from `files/`:

| Path                 | HTTP | Meaning                     |
|----------------------|------|-----------------------------|
| `/content/probe.md`  | 200  | Served. Drafts are public.  |
| `/.content/probe.md` | 403  | Blocked by default.         |
| `/content/`          | 403  | No directory listing.       |
| `/.content/`         | 403  | Blocked.                    |

Use a dot directory (`.content/`) for content. A plain directory name is
served to anyone who guesses the path. The site user cannot read
`/etc/nginx`, so the rule that blocks dot paths was not inspected; the result
above is from requests only.

The repo must track only content files. `checkout -f` overwrites any tracked
file, so a tracked file with the same name as a WordPress file would replace
it on the live site.

## Known problems

- **No pip or venv.** Ubuntu's `python3` on the server has no `pip` and no
  `ensurepip`, so wp-post cannot install its packages with the system Python.
  The site user has no sudo. Planned fix: install `uv` in the site user's
  home directory (no root needed).
- **Temporary domain certificate.** A site on its temporary
  `*.spinupwp.site` address does not serve a certificate that curl trusts
  ("unable to get local issuer certificate"). wp-post posts over REST to the
  site URL, so it fails certificate checks there. Use a real domain with a
  Let's Encrypt certificate.
- **ID writeback.** `checkout -f` discards local changes, so an `id` that
  wp-post writes back into front matter is lost on the next deploy. wp-post
  needs to find posts by file path instead.

## Not yet tested

- Deploy Script: which user runs it, time limit, what happens on failure.
- Whether the Deploy Script can learn the previous commit, to find changed
  files (fallback: keep the last deployed SHA in a file).
- MSLS linking (needs a multisite network with MSLS).
