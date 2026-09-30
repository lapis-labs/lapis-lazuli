# Security policy

## Reporting a vulnerability

Report it privately through GitHub's private vulnerability reporting: open the repository's Security
tab and choose "Report a vulnerability", or go straight to
<https://github.com/lapis-labs/lapis-lazuli/security/advisories/new>. Please do not open a public
issue or pull request for a vulnerability, and do not post it in a discussion.

Include the command you ran, the version (`lapis-design --version`), your operating system, and the
smallest page, URL, or input that reproduces it. Use synthetic data; do not send credentials or
private files.

If you cannot use the private report form, open an issue that asks for a private way to reach the
maintainers and says nothing about the vulnerability itself.

Only the latest release, which the `release` branch follows, receives fixes.

## What is in scope

The CLIs' network boundaries, which the code promises to keep (see "Boundaries the code must keep" in
[AGENTS.md](AGENTS.md)):

- `lapis-design render check` capturing a host that is not ours, as **Target hosts** in
  [`src/shared/render/DERIVED.md`](src/shared/render/DERIVED.md) defines it, without `--public`, or a
  registry or plan-reference host even with it.
- `lapis-design behavior check` reaching or driving a host that is not ours, or storing typed values,
  query strings, headers, or request bodies.
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

Code that runs on your machine and reads input you may not trust:

- The install scripts (`install/install.sh`, `install/install.ps1`), which INSTALLATION.md fetches from
  the `release` branch and runs straight in a shell.
- The hooks: `lapis-design hook session-start`, which a harness runs at every session start, and
  `lapis-design hook exit-plan`, which parses the event a harness sends on standard input.
- The MCP server (`lapis-design mcp`).
- `lapis-design slop lint` and `plan check` reading a project tree, plan, or report you did not
  write: running code from it, taking unbounded time or memory, or reading or writing outside the
  paths you gave.

## What is out of scope

- A slop rule or detector that judges a design wrongly: open a regular issue.
- How a harness (Claude Code, Codex, Oh-My-Pi, pi, Hermes Agent, or another) loads plugins or runs
  hooks: report it to that harness.
- Findings that need control of your own machine, your shell, or your browser profile first.
