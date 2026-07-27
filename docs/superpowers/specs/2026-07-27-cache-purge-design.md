# Design: `wp-post --purge`

Date: 2026-07-27

A single command that clears the page cache for one page, one site in a
multisite network, or every site in the network.

## Motivation

wp-post publishes and updates content but never invalidates the page cache
that sits in front of it. The SpinupWP plugin auto-purges on `save_post`,
which covers ordinary REST writes, but leaves two gaps:

1. Writes that bypass `save_post` entirely. wp-post links MSLS translations
   with `wp eval` + `update_option`, so sibling-language pages keep serving a
   stale language switcher from the FastCGI cache.
2. Any manual or out-of-band change where you want a deterministic "clear it
   now" without hunting through a hosting dashboard.

## Findings that shaped this design

These were measured on 2026-07-27, not assumed. They are recorded here because
they are the reason the scope is what it is.

### SpinupWP caches HTML, and purging it is real work

`payperfax.com` serves a `fastcgi-cache` header that transitions MISS -> HIT on
a second request, on both posts and pages:

| URL                                   | 1st hit | 2nd hit |
|---------------------------------------|---------|---------|
| `/de/wird-fax-noch-genutzt/` (post)   | MISS    | HIT     |
| `/de/impressum/` (page)               | MISS    | HIT     |

The `spinupwp` plugin (1.9.1) is active network-wide on payperfax, and active
on dashpadd.com, getboki.com and nanopo.st. It exposes exactly three WP-CLI
subcommands, all of which accept the `--url=` global parameter to select a blog
in a multisite network:

| Command                        | Scope          |
|--------------------------------|----------------|
| `wp spinupwp cache purge-post` | one post by ID |
| `wp spinupwp cache purge-url`  | one URL        |
| `wp spinupwp cache purge-site` | one blog       |

### Cloudflare caches no HTML, so purging it would be a no-op

Every zone returns `cf-cache-status: DYNAMIC` for HTML, on homepages and deep
content pages alike. The payperfax zone has zero cache rules and zero page
rules. Free and Pro plans cache by file extension only, and HTML is excluded.

| Site          | Plan | HTML `cf-cache-status` | Cache rules |
|---------------|------|------------------------|-------------|
| payperfax.com | Free | DYNAMIC                | none        |
| dashpadd.com  | Free | DYNAMIC                | none        |
| mintfax.com   | Free | DYNAMIC                | none        |
| faxbeep.com   | Pro  | DYNAMIC                | none        |

Static assets are cached (a `.css` request went MISS -> HIT), but wp-poster's
media dedup keeps attachment URLs stable, so an updated page does not leave a
stale asset behind.

Cloudflare is therefore out of scope. See "Deferred: Cloudflare" below for what
changes if HTML caching is ever enabled.

### Every server is reachable, but only one WP-CLI alias exists

`~/.wp-cli/config.yml` defines only `@payperfax`. The monolingual projects have
no alias and no `ssh` block in their configs. All three servers do have WP-CLI
installed and SSH host entries, and WordPress lives at `/sites/<domain>/files`.
`wp --ssh=dash/sites/dashpadd.com/files option get home` was verified to work
with no `~/.wp-cli/config.yml` involvement.

Transport configuration therefore belongs in `.wp-poster.json`, so a project is
self-contained.

## Command surface

One action flag plus exactly one scope selector:

```bash
wp-post --purge --file content/de/wird-fax-noch-genutzt/index.md   # one page
wp-post --purge --site de                                          # one language site
wp-post --purge --network                                          # every site
```

Behavior:

- `--purge` with no scope selector is an error listing the three selectors.
- More than one scope selector is an error.
- `--site` with no value on a single-site project targets the configured site.
  On a network project the value is required and must be a key in
  `network.sites`; an unknown key errors and lists the valid keys.
- `--network` on a config with no `network` block is an error naming the config
  file that was found.
- `--test` prints the commands that would run without running them.
- `--verbose` prints each command as it runs.

This follows the existing standalone-action convention in `main()`
(`--ping`, `--config-path`, `--init`).

## Configuration

Transport is read from `.wp-poster.json` under the key `wp_cli_alias`: at the
top level for single-site projects, and under `network` for network projects,
where it already exists and is already used for MSLS linking.

The value is interpreted by its first character:

- Starts with `@` -> run `wp <value> ...`, resolved through
  `~/.wp-cli/config.yml`.
- Anything else -> run `wp --ssh=<value> ...`, self-contained.

```jsonc
// payperfax-content/.wp-poster.json - already present, unchanged
"network": { "wp_cli_alias": "@payperfax", "sites": { ... } }

// dashpadd/.wp-poster.json - one line to add
"wp_cli_alias": "dash/sites/dashpadd.com/files"
```

The key name is imprecise once it can hold an SSH target rather than only an
alias, but it matches the existing `network.wp_cli_alias` key. Consistency with
the established name is worth more than the precision.

If `--purge` runs with no `wp_cli_alias` resolvable, it exits 1 with a message
naming the config file it read and the key to add.

## Scope resolution

| Scope       | Command per target                                    | Target resolution                       |
|-------------|-------------------------------------------------------|-----------------------------------------|
| `--file`    | `spinupwp cache purge-post <id> --url=<site_url>`     | `find_site_for_file()` on the file path |
| `--site`    | `spinupwp cache purge-site --url=<site_url>`          | key lookup in `network.sites`           |
| `--network` | `spinupwp cache purge-site --url=<site_url>` per site | iterate `network.sites`                 |

`--file` uses `purge-post` rather than `purge-url` because frontmatter already
carries `id`, so no permalink lookup round-trip is needed. A file whose
frontmatter has no `id`, or `id: null`, errors as unpublished before any
subprocess is spawned. This mirrors the existing treatment of `id: null` as
absent.

`--file` purges only that page. It does not purge translation siblings; see
"Known limitation" below.

On a network project, a `--file` path that falls outside every site's
`content_path` is an error naming the file and the configured content paths,
rather than a silent no-op or a guess at blog 1.

For a single-site project, `--file` uses the top-level `site_url` with no path
matching, `--site` uses the same `site_url`, and `--network` is rejected.

## Structure

Four new module-level functions. No changes to the `WordPressPost` class, which
exists to hold an authenticated REST session that purging does not need.

- `resolve_wp_cli_transport(config)` -> argv prefix, e.g. `['wp', '@payperfax']`
  or `['wp', '--ssh=dash/sites/dashpadd.com/files']`. Raises with a
  configuration message when no alias is present.
- `resolve_purge_targets(args, config, project_root)` -> ordered list of
  `(label, site_url, post_id_or_None)`. Pure function over already-parsed
  config; no I/O beyond reading the target file's frontmatter.
- `spinupwp_purge(transport, target)` -> `(ok, output)`. Builds and runs one
  subprocess. The only function that touches `subprocess`.
- `handle_purge(args)` -> orchestration, output, exit code. Called from
  `main()` alongside the other standalone action flags.

Reuses `find_network_config`, `find_site_for_file`, `resolve_site_identity`,
`load_config` and `load_frontmatter` unchanged.

Splitting target resolution from execution is what makes the feature testable
without SSH: `resolve_purge_targets` is asserted directly, and
`spinupwp_purge` is the single mock point.

## Error handling

A non-zero exit from `wp` marks that target failed, prints its stderr, and the
loop continues to the remaining targets. The command exits 1 if any target
failed, 0 otherwise.

No retry or backoff, unlike the MSLS link-write path. Purging is idempotent and
cheap to re-run by hand, so a retry loop adds failure modes without adding
reliability.

Configuration errors (no alias, unknown site key, unpublished file, `--network`
on a single-site config) are detected before any subprocess runs and exit 1
immediately.

## Output

Plain text progress to stdout, matching the existing convention:

```
Purging SpinupWP cache (network: 6 sites)
  ✓ en   https://payperfax.com
  ✓ es   https://payperfax.com/es
  ✓ de   https://payperfax.com/de
  ✓ ja   https://payperfax.com/ja
  ✓ ko   https://payperfax.com/ko
  ✗ fr   https://payperfax.com/fr  (ssh: connection timed out)
✗ 5 purged, 1 failed
```

## Testing

Unit tests in `tests/test_wp_post.py`, with `subprocess` mocked, following the
existing patterns in that file:

- `--file` resolves to the correct `site_url` and `post_id` for a network
  project, based on which `content_path` contains the file.
- `--file` on a frontmatter with no `id`, and with `id: null`, errors and
  spawns no subprocess.
- `--site` with an unknown key errors and lists valid keys.
- `--file` outside every configured `content_path` errors and spawns no
  subprocess.
- `--network` on a single-site config errors.
- On a single-site config, `--file` and `--site` both resolve to the top-level
  `site_url`.
- Transport: `@payperfax` produces `['wp', '@payperfax', ...]`; an SSH target
  produces `['wp', '--ssh=...', ...]`.
- A failing target does not abort the loop: remaining targets are still
  attempted and the exit code is 1.
- `--test` resolves targets and prints commands but spawns no subprocess.

## Known limitation

`--purge --file` clears only the given page. wp-post writes MSLS translation
links with `wp eval` + `update_option`, which never fires `save_post`, so after
a translation link write the sibling-language pages keep serving a stale
language switcher. Use `--purge --site` or `--purge --network` after linking
translations.

Widening `--file` to follow `translation_set` via the existing
`find_translation_siblings()` is a deliberate future option, not part of this
change.

## Deferred: Cloudflare

Not implemented, because it would invalidate nothing today (see findings).

Revisit when a Cache Everything rule is added to a zone. At that point all
purge methods, including prefix, are available on every plan including Free
(Cloudflare opened these up in April 2025), so the mapping would be:

| Scope       | Cloudflare call                             |
|-------------|---------------------------------------------|
| `--file`    | `files: [<permalink>]`                      |
| `--site`    | `prefixes: ["payperfax.com/de/"]`           |
| `--network` | `purge_everything: true`                    |

One wrinkle to solve then: the `en` site sits at the domain root
(`https://payperfax.com`), so no prefix can isolate it from `/de/`, `/es/` and
the rest. That site would need URL enumeration or an accepted zone-wide purge.

Credentials would come from the existing `CLOUDFLARE_API_TOKEN` environment
variable, with the zone resolved by looking up the site's apex domain.

## Also out of scope

- **Redis object cache.** A dropin is installed on every site, but WordPress
  invalidates it on content change, so it is not stale after a publish.
- **Auto-purge after posting.** `--purge` is explicit only. The SpinupWP plugin
  already hooks `save_post`, which REST writes fire.

## Versioning

Per `CLAUDE.md`, bump the version in `.claude-plugin/plugin.json` if
`skills/wp-post/SKILL.md` is updated to document `--purge`.
