# Security policy

## Reporting a vulnerability

Report it privately through GitHub's private vulnerability reporting: open the repository's Security
tab and choose "Report a vulnerability", or go straight to
<https://github.com/lapis-labs/lapis-lazuli/security/advisories/new>. Please do not open a public
issue or pull request for a vulnerability, and do not post it in a discussion.

Include the command you ran, the version (`lapis-design --version`), your operating system, and the
smallest page, URL, or input that reproduces it. Use synthetic data; do not send credentials or
private files.

Only the latest release, which the `release` branch follows, receives fixes.

## What is in scope

The CLIs' network boundaries, which the code promises to keep (see "Boundaries the code must keep" in
[AGENTS.md](AGENTS.md)):

- `lapis-design render check` and `behavior check` reaching, capturing, or driving a host that is not
  ours, or storing typed values, query strings, headers, or request bodies.
- `lazuli ref capture` reaching a host the source registry marks `refused` or `browser-link`, using
  a proxy from the environment, ending on a document lazuli did not fetch, or keeping more than the
  source's rights allow.
- `lazuli read` and `lazuli read --render` reading an address that is not a global unicast address,
  handing a page a response a browser would have blocked, or following a redirect without checking
  it.
- Any request lazuli sends itself (catalogs, pages, `setup` downloads) that skips robots.txt, the
  source registry's policy, or its pace, or that a redirect carries to a refused host.
- Credentials, license keys, payment data, or private receipts ending up in a ledger, lock, profile,
  session, or log.

## What is out of scope

- A slop rule or detector that judges a design wrongly: open a regular issue.
- How a harness (Claude Code, Codex, Oh-My-Pi, pi, Hermes Agent, or another) loads plugins or runs
  hooks: report it to that harness.
- Findings that need control of your own machine, your shell, or your browser profile first.
