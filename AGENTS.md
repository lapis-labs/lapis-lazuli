# lapis-lazuli

Design skills for AI agents, shipped as three plugins from one source, plus the CLI they rely on.
The rules every session follows are at the end, because some harnesses read only this file.

| Plugin | Role | Skills |
|---|---|---|
| `lapis` | Direction, plans, named defaults for new UI and redesigns | `lapis`, `lps-brief`, `lps-ux`, `lps-copy`, `lps-system` |
| `ultramarine` | Render and behavior checks, slop and rights review, separate critic | `ultramarine`, `ulm-maintain`, `ulm-release` |
| `lazuli` | Local fonts and colors, catalogs, references, the `lazuli` CLI | `lazuli`, `lzl-fonts`, `lzl-color`, `lzl-research` |

`ll-` is reserved for work that belongs to no single plugin. No skill holds shared data.

## Sources of truth

- `src/` is the only place people edit. `plugins/`, `dist/`, `.claude-plugin/marketplace.json`,
  `.agents/plugins/marketplace.json`, and the root `package.json` are build outputs that are
  committed (marketplace installs read the repository as is). Regenerate them; never hand-edit.
  CI fails when they drift from `src/`.
- Contracts: `src/shared/` (`plan/`, `render/`, `behavior/`, `slop/`, `fonts/`, `assets/`, `vocab/`,
  `index.yaml`). The CLI packages all of it; each skill gets only the views `index.yaml` gives it.
- Harness facts and install commands: `install/harnesses.yaml`. Output shapes: `install/OUTPUTS.md`.
  `install.sh`, `install.ps1`, and `INSTALLATION.md` are generated from them.
- Knowledge migrated from the maintainers' previous skill, `design-and-frontend` (not part of this
  repository): `tools/migration-map.yaml` records each migrated file and where it went.
- Rule ID history: `tools/slop-id-trace.yaml`.
- The reasons behind decisions are recorded outside this repository. When code and such a record
  disagree, the repository wins.

## Commands

```bash
uv sync                                  # Python 3.12 venv with the CLI (editable) and dev tools
uv run playwright install chromium-headless-shell   # once per Playwright version; render tests need it
uv run pytest -q -m "not browser"        # contracts, checks, derived values: seconds
uv run pytest -q -m browser -n auto      # Chromium tests in parallel (pytest-xdist): minutes
uv sync --extra cjk && uv run pytest -q -m cjk   # optional Korean, Japanese, Chinese analyzers (~340 MB)
uv run lapis-design --version
uv run lapis-design plan check src/shared/plan/example.plan.yaml \
  --rules src/shared/slop/rules.yaml --lock src/shared/fonts/example.fonts.lock.json
uv run lapis-design rights check --ledger src/shared/assets/example.assets.ledger.json \
  --lock src/shared/fonts/example.fonts.lock.json --extract src/shared/render/example.extract.json
uv run lapis-design render check http://127.0.0.1:8000/ --task demo   # -> .lapis/renders/demo.json
uv run lapis-design behavior check http://127.0.0.1:8000/ --task demo --plan .lapis/plans/demo.yaml \
  --stub .lapis/stub.yaml                 # -> .lapis/behavior/demo.json
uv run lapis-design render check http://127.0.0.1:8000/ --task demo --width 390   # narrowed -> .lapis/renders/demo.narrow.json
uv run lapis-design behavior check http://127.0.0.1:8000/ --task demo --stub .lapis/stub.yaml \
  --probe controls --box b0123456789ab    # narrowed -> .lapis/behavior/demo.narrow.json (--limit N caps boxes)
uv run lapis-design stub serve .lapis/stub.yaml --port 8787   # same stub over HTTP, for server-rendered apps
uv run lapis-design slop lint --plan .lapis/plans/demo.yaml --extract .lapis/renders/demo.json \
  --session .lapis/behavior/demo.json -o .lapis/lint/demo.json   # every layer whose input is given
# a lint run narrowed by --layer or --rule goes to -o .lapis/lint/demo.narrow.json
uv run lapis-design critic packet --task demo   # the fixed inputs a critic report is judged against -> .lapis/critic/demo.packet.json; the report names it in target.packet
uv run lapis-design release check --task demo   # the release gate (src/shared/release/GATE.md) -> .lapis/release/demo.json
uv run lapis-design next --task demo           # the one step still to take (--json for tools); see GATE.md, Failure records
uv run lazuli local fonts --summary       # read-only font scan and measurement into the user cache
uv run lazuli doctor
uv run lazuli catalog sync                 # snapshot catalogs at human pace into the user cache (asks nothing)
uv run lazuli catalog status
uv run lazuli search --script hang --role body --license open   # ranked font candidates with evidence
uv run lazuli search --type color '#336699'   # nearest computed HLC/RAL-design codes and your own records
uv run lazuli lock "Family" --role body --task demo --dry-run    # pins facts in .lapis/fonts.lock.json
uv run lazuli license "Family"              # what a font says about its own license, and where to look (read-only, no request)
uv run lazuli fetch "Family" --into public/fonts/family   # an open-licensed Google Fonts family's files and license text into the project
uv run lazuli class set "Family" --genre min-bu-ri --subclass rounded   # your class for a font; user cache only, outranks catalogs
uv run lazuli sources --type color          # source registry (src/shared/sources/) with access policies
uv run lazuli color lookup pantone "186 C"  # codes and links only; values only from `lazuli color record`
uv run lazuli read https://example.com/page   # one requested page as Markdown, within registry and robots.txt
uv run lazuli ref capture https://example.com/ --rights reference-only   # -> .lapis/refs/<slug>.json
uv run lazuli ref capture https://example.com/ --rights reference-only --task demo   # + study copies in .lapis/references/demo/<slug>/
uv run lazuli setup                        # installs a model from a release manifest (src/shared/models/SETUP.md); exits 1 until one is published
uv run python tools/build/build.py       # regenerate plugins/, dist/, catalogs, package.json from src/
uv run python tools/build/build.py --check   # CI: fail when committed outputs drift from src/
sh install/install.sh --dry-run             # what the generated installer would do here (changes nothing)
uv build --out-dir build/wheels          # wheel carries src/shared as lapis_design/shared
```

Run them from this folder. CI runs `uv sync --locked`, then the two test commands above as separate
jobs (the contracts job excludes `cjk`; the browser job runs on four runners, each with
`--shard K/4`, a part of the tests weighed by `tests/shard_durations.json`, which `tests/shards.py`
refreshes from a full run's JUnit file after slow browser tests are added or split), plus a third job that installs the
`cjk` extra and runs every test but the browser ones, and a light docs workflow when only documents change, on Python 3.12
(`.python-version`), the lowest version `requires-python` allows. Tests
that drive Chromium carry the `browser` marker (`tests/conftest.py` sets it by file and
by the `browser` fixture); keep new browser tests parallel-safe (port 0, no shared files). Tests
that need the analyzers carry `cjk` and are skipped without the extra; `lint/morph.py` returns
nothing then, and the word matching runs as before.
`rights_check` on the example ledger reports three `rights.notice-missing` findings and exits 1,
because the example's notice files are not in this repository. The lazuli database needs SQLite
3.34 or later (FTS5 trigram). Only lazuli's own code creates or migrates it, each migration in one
transaction that runs its statements one at a time: every statement in a migration file ends with a
semicolon at the end of its own line, no migration needs to run outside a transaction
(`VACUUM`, a journal-mode change), and no migration holds a transaction or savepoint statement of
its own. The checks (`plan check`, lint, the gate, the exit-plan hook, MCP) read measured features
from it read-only; the one write a check makes is the gate's license
refresh, which opens it through the lazuli catalog layer as `lazuli catalog lookup` does, creating
or upgrading it when needed. Opening a WAL-mode database read-only can leave its `-wal` and `-shm`
files beside it; the database file itself does not change.

## Changing contracts

- A field change bumps that file's `version`, updates its example and tests, and the owning check
  converts or explains older versions. An optional field that older readers can ignore keeps the
  version; its example and tests still change.
- Rule IDs are `domain.name`, or `domain.lang.name` for one language. Requirement and contract
  rules always gate. Quality rules gate at P0–P1 and warn at P2–P3. Default rules that rely on
  statistical detection warn. Every `params` and `threshold` key is declared in
  `src/shared/slop/detectors.yaml`; threshold keys are `<metric>_max`, `<metric>_min`, or bare
  `min`/`max`, and a bound is the allowed edge (`_max` fires above it, `_min` below it).
- Each `keep_when` case is `{ id, when, evidence }` with a kebab-case id, unique within its rule. A plan's
  `defaults` keep names one as `keep_when`, and `plan check` and `slop lint` waive a finding only for an id
  of that rule, so renaming or removing an id breaks the plans that name it: treat it like a rule ID. A rule
  that lists no case takes no keep. A case on a rule that takes a keep lists `evidence`: the alternatives a
  plan can hold for its premise (`design`, `brief`, `material`, `source`, `exploration`, an `asset`, or a
  `plan` condition), any one of which backs the keep, or `none` when nothing a plan, a design contract, or
  the asset ledger holds can show it. The check waives only when the keep carries that evidence, so a new
  case states what a plan can hold, or `none`; the legend in `src/shared/slop/rules.yaml` defines each kind.
- Agent-facing rule text (`why`, `better`, `keep_when`) never names external skills, products,
  laws, or external IDs. Attribution goes only in `provenance`, which the build strips.
- Skill bodies name no connectors, external skills, or specific tools, and have no boilerplate
  sections (When to consult, Common pitfalls, Quick decision matrix, Cross-references). Every skill
  works without hooks, agents, or MCP; where a hook would help, the body says what to run by hand.
- Comments and free text in YAML and code are English. Exceptions: `tools/migration-map.yaml` and
  `README.ko.md` are Korean; data values stay as they are (UI copy in examples, `ko` fields, Korean
  seed values).
- Priority when judging a design: requirements > the project's contract (DESIGN.md) > conventions
  > editorial signals (slop rules).

## Boundaries the code must keep

- Behavior checks drive only our own render on hosts that are ours as render/DERIVED.md **Target
  hosts** defines it, and block every other host. They use a stub or an isolated local backend
  with synthetic data, never real accounts, credentials, or payment methods, and never store typed
  values, query strings, headers, or bodies. Path segments such as IDs become `:id`.
- Render checks capture hosts that are ours without a flag; a public host only with `--public`, and
  never a source-registry host or a host in the plan's `references`, even after a redirect
  (`cli/lapis_design/render/hosts.py`). Pages that are not ours go through `lazuli ref capture`.
- Reference captures load only URLs the user gave, or the ones a run chose itself in the `references` step (`--task`,
  which keeps study copies in `.lapis/references/<task>/`, git-ignored, never shipped), never sign in or submit forms,
  and keep what the
  render schema allows for the source's rights. The capture browser runs without a proxy, whatever
  proxy the environment sets, and cannot reach a host the source registry marks `refused` or
  `browser-link`: its launch rules leave those names unresolved, so no request the page makes gets
  there, redirect hops, frames, workers, and prefetches included, and a request the route handler
  sees for such a host is aborted first.
  Peer-to-peer connections are disabled. Apart from the named page's own document, which lazuli
  fetches after its checks, every request is left to the browser, whose own cross-origin and
  private-network rules stay in force; local-network access is granted only to a loopback page the
  user named. A capture whose main frame ends on a document other than the one lazuli fetched,
  through a prefetch or any other route, stops as blocked (a URL change through the history API
  keeps the document). A capture that stops as blocked, or fails before its profile is written,
  keeps no profile or screenshot from that run; a slug's profile and screenshots are replaced
  together or not at all. The profile's notes count the blocked requests the browser reports, a
  lower bound.
  Service workers are blocked. Page requests are checked against the registry only, not robots.txt
  or the pace. Reference-only captures keep no copy, alt text, accessible names, or screenshots:
  keyed MinHash signatures (`cli/lapis_design/text_sig.py`) and perceptual hashes only.
- `lazuli read --render` reads only pages on global unicast addresses. A page, a redirect hop, or a
  request the page makes that names or resolves to any other address (loopback, private, link-local,
  shared, multicast, unspecified, or one of these inside an IPv4-mapped, IPv4-compatible, or
  translated IPv6 address) is refused; a named page on such an address gets a one-line reason that
  points to `lapis-design render check`. The address a connection reaches is checked again once
  connected; behind a configured proxy it cannot be, so `--render` stops with a one-line reason. The
  render browser cannot reach the network by itself: it runs behind a proxy on a loopback port that
  lazuli holds for the render and that refuses or closes every connection, so prefetches,
  prerenders, and anything else it would send on its own fail, and only what lazuli fetches reaches
  the page. Peer-to-peer connections, which do not go through a proxy, are disabled. lazuli sends
  each request the page makes and follows its redirects one hop at a time. A request whose redirects
  move it to an origin other than the one it named, including a later navigation of the main frame,
  is not handed to the page; when the named page redirects, lazuli loads the final address as the
  page, so the page runs under its own origin. lazuli keeps the rules the browser would: a
  cross-origin response without exactly one matching `Access-Control-Allow-Origin` is not handed to
  the page for any request a browser applies CORS to, whatever its kind (every request that sends an
  `Origin` header, and every `fetch` and XHR); a classic script loads as it would in a browser. A
  result whose main frame ends on a document lazuli did not hand it is refused (a URL change through
  the history API keeps the document). lazuli reads the result's address and HTML where the page's
  own scripts cannot change what it reads.
- Rights checks compare records and never state a legal conclusion. Ledgers and locks never hold
  credentials, license keys, payment data, or private receipts.
- Font catalogs are looked up only when a task needs them and cached only in the user's local
  database. Keep a human pace and stated crawl delays (Sandoll Cloud: 10 seconds between
  requests), name lazuli in the request headers, and never get around a block. Read a source's
  robots.txt and terms before adding it; a source whose terms forbid automated collection, as lazuli
  reads them (not legal advice; the Adobe Fonts site, noonnu as of 2026-09-26), gets a `REFUSED` adapter
  that sends nothing and gives links. That has nothing to do with recommending, choosing, or locking
  Adobe Fonts.
- `lazuli fetch` downloads font files only from the google/fonts repository, for a family the catalog
  lists under a license the lock has a kind for, through the same request layer (registry, robots.txt, the
  3 s pace, a stop on a block), and writes nothing unless every file passes its checks (the repository's
  own hash, a font's first bytes, the license text naming the license). Adobe Fonts are never fetched,
  opened, or copied, and `lazuli license` reads no file of theirs and sends nothing.
- Every redirect of a request lazuli sends itself is followed by hand, one hop at a time: each hop
  is checked against the source registry and that host's robots.txt before it is requested, and a
  hop to a `refused` or `browser-link` host is never sent. A robots.txt that redirects is followed
  the same way, up to five hops, and counts as blocked beyond that. Hosts are compared in the form
  the request is sent to: percent-decoded as UTF-8, then in IDNA ASCII form. What remains must be a
  bracketed IPv6 address, a dotted-quad IPv4 address, or a name of labels made of ASCII letters,
  digits, hyphens, and underscores whose last label is not numeric; any other host is refused, and
  so is a host holding a character that host-name conversions disagree on or drop (`ß`, `ς`, the
  zero-width joiner and non-joiner). The URL a command is given is read the same way as a hop, dot
  segments resolved and credentials refused, before the registry and robots.txt decide. A hop's
  pace is kept under its own host. A reference capture's page subrequests follow the previous rule
  instead.
- A change to a network boundary (reference capture, `read --render`, the request path) comes with
  tests that attack it from a page: a refused host by name and through a redirect, a proxy the
  environment sets, a cross-origin read of each kind, and a name that resolves to a private address.
  Browser tests use the same browser build the capture uses.
- Tests never reach live sites; they use recorded fixtures. Font fixtures are OFL fonts added with
  their license file (`git add -f`, since `.gitignore` excludes font files).

## Packaging

- `pyproject.toml` at the repository root: distribution `lapis-design` (`lapis-lazuli` is taken on
  PyPI), entry points `lapis-design`, `lapis-design-hook`, and `lazuli`, version in `cli/lapis_design/__init__.py`.
  `cli.uninstall` in `install/harnesses.yaml` uses the same name. Ask before publishing.
- `uv run` syncs the environment to `pyproject.toml` and `uv.lock`, so add runtime dependencies
  with `uv add` and test tools with `uv add --dev`, never `uv pip install`. New dependencies need
  the user's approval first.
- `src/shared` ships as package data at `lapis_design/shared`; `lapis_design.shared_dir()` finds
  it, and falls back to `src/shared` in a checkout. CLI code finds contracts only through
  `shared_dir()`, never through paths relative to the repository.
- `dist/` holds committed skill outputs, so build Python wheels elsewhere
  (`uv build --out-dir build/wheels`).
- Hooks call the plain command `lapis-design-hook --plugin-version VERSION <name>` (`session-start`, `exit-plan`,
  `stop`, `pre-write`), with bodies in `cli/lapis_design/hooks.py`; unknown hook arguments and version skew fail open
  with one visible notice, never argparse exit 2 (install/OUTPUTS.md, Hooks). MCP is `lapis-design mcp`
  (`cli/lapis_design/mcp_server.py`, official MCP Python SDK). Hooks run at every session start (`stop`, at every
  turn's end; `pre-write`, before every file edit), so keep heavy imports out of them. pi and Oh-My-Pi have no
  hooks.json: extensions call the same versioned hook runner; the build stamps their version placeholders.
- `render check` lives in `cli/lapis_design/render/`: `capture.py` (capture matrix, boxes, base
  text runs), field passes in `render/fields/` (`text`, `visual`, `interaction`, run in that
  order on the live page, each restoring what it changed), `derived.py`, and `extract.py`
  (assembles and validates against `render/extract.schema.yaml`; an invalid extract is never
  written). DERIVED.md is the meaning of every field; a pass that cannot measure a field omits it.
  Text signatures use the per-user key from `cli/lapis_design/sig_key.py` (user cache, or
  `LAPIS_SIG_KEY_FILE`); tests always point that variable at a temporary file.
- `behavior check` lives in `cli/lapis_design/behavior_check/`: the driver core (`session.py`,
  `driver.py`, `network.py`, `settle.py`, `nodes.py`, `redact.py`, `scope.py`) and probe modules in
  `probes/` (`NAMES` and `run(session, open_driver)`), registered in order in `probes/__init__.py`. Derived
  values come only from `lapis_design/behavior.py` (`derive_session`). The stub backend is
  `cli/lapis_design/stub/`: one engine, answered in the browser through Playwright routing by
  default, or over HTTP with `stub serve` (admin endpoints under `/__lapis/`, driven by `--stub-url`).
  Its fixture format is `src/shared/behavior/stub.schema.yaml`. With `--backend local-dev`, the
  driver takes synthetic values only from `--values FIXTURE` and never injects failures or runs
  destructive probes.
  A narrowed run (`render check --width`; `behavior check` with `--probe`, `--context`, `--box`, or
  `--limit`) writes `.lapis/<renders|behavior>/<task>.narrow.json` (`lapis_design/narrow.py`) and is refused the
  full path, which the release gate reads. `--box` and `--limit` narrow the per-box probes (`PER_BOX` in
  `scope.py`: `controls`, `pointer`) through `session.scope.pick` and `admit`; `Session.cover` then marks a probe
  that left boxes out `partial` with their count, and `commits` with it, since it works from the controls that ran.
- `slop lint` lives in `cli/lapis_design/lint/`: `types.py` (the fixed detector interface),
  `engine.py` (rule severity, `defaults` waivers, `locales`, packages, leads, and behavior coverage
  turn detector results into findings), `cli.py` (loads and validates the inputs; also the MCP
  tool `slop_lint`), and one detector module per slice in `detectors/`, registered by
  `detectors.load()`. `plan check` runs the plan-layer names it does not implement from the same
  registry, and `asset-ledger` runs through `rights_check.py`. A detector that cannot judge returns
  a skip reason, never a pass. Every report records `scope` (the layers that ran, and `rules` or
  `rules_file` when the run was narrowed), and every skipped finding records `skip_cause`; the
  release gate reads both.
- `release check` lives in `cli/lapis_design/release_check.py`: it runs the plan checks itself, reads the lint, session, extract, and critic reports, rechecks catalog font licenses through `lazuli.catalog`, and writes the gate report; it never captures or drives a page.
- `next` lives in `cli/lapis_design/next_step.py`: `lapis-design next --task demo [--json]` runs `release_check.run(...,
  offline=True)` on the files and returns the one step still to take (`brief`, `references`, `plan`, `plan-fix`,
  `plan-flows`,
  `plan-explorations`, `fonts-lock`, `stub`, `ledger`, `render`, `behavior`, `lint`, `critic`, `release`) with its exact
  command or schema, or `done`; it judges nothing the gate already judges, and `done` is a complete procedure, not a
  passing gate. `render check`, `behavior check`, and `release check` write `.lapis/attempts/<task>/<step>.json`
  (`attempts.py`) when a full run cannot start because of the environment (a browser that is missing or will not start,
  a path the sandbox denies); `next` counts a record newer than the step's inputs as that step done, and nothing else
  is ever recorded. `lapis-design hook stop` (`gate.py`) is the exit gate every harness asks: with a plan in reach and
  `LAPIS_UNATTENDED=1` it continues the agent with that step, three times in a row for one step and fifteen in a
  session at most (state in `.lapis/gate/<task>.json`); an unattended run with no plan owes one, so its step is `brief`,
  then `references`, then `plan` (task from `$LAPIS_TASK`, else the project folder's name); otherwise it prints one line
  and never blocks.
  The `brief` step (`brief.py`) is asked for while a run with no plan, or a plan in `create` mode, has no brief record:
  `.lapis/answers/<task>.md` with a `## Found` and an `## Answers` section whose `[assumed]` items give a `Basis:`, at
  most six items under each answers heading (`## Answers` is round 1, `## Answers (round 2)` round 2) and no third
  round; a pending set in `.lapis/questions/<task>.md` of more than six numbered questions is cut the same way
  (`brief.owed`, `brief.questions_problem`), so the step is `brief` and the run does not wait.
  The `references` step (`references.py`) follows it on the same terms: `.lapis/references/<task>.md`, a fenced `yaml`
  block of at least six references, each with a `capture` file under `.lapis/references/<task>/` (three kinds and two
  outside `web-ui` among the images, `source_facts` for `web-ui`, at most two text-only); a run with no network records
  `next --unavailable references --reason`, and a run whose user's words forbid lookups during the work, with nobody
  to ask, declines with `next --declined references --brief-line "<line>"` (the line has to be in the brief record or
  the plan's `brief.constraints`; `references.declined`). Either counts as done and is reported as not looked at; a
  decline is `release.references-declined` in `release check`, and the plan's `explorations` use local material.
  A run that stopped to ask its user (`waiting.py`: `.lapis/questions/<task>.md` newer than `.lapis/answers/<task>.md`)
  makes `next` say `waiting-for-user` and the gate let the stop pass without a continue: two sets before a plan, one
  after (`waits` in the gate state).
  The order brief, references, plan, then code is `order.py`: `hook pre-write` refuses an unattended create run's write
  of a page source file while `next` names `brief`, `references`, `plan`, `plan-fix`, or `plan-explorations` (three
  refusals for one step, then the write passes and is recorded in `.lapis/order/<task>.json`), and `release check`
  reports page code that came first as `release.procedure-order`, which `next` turns into the step `plan-order`.
- `lazuli` lives in `cli/lazuli/`: `scan.py` (read-only inventory; `LAZULI_FONT_ROOTS` replaces the
  roots and turns the Core Text listing off), `coretext.py` (Adobe Fonts through Core Text on macOS,
  never through their files), `measure.py` (PANOSE Latin and the CJK extension per `vocab/type.yaml`; bump
  `MEASURER_VERSION` when a measurement changes so faces are re-measured), `db/` (migrations), `local.py`
  (`local fonts`, the session summary), `doctor.py`. The database lives in the user cache
  (`LAZULI_DB` overrides it). Tests build synthetic fonts in code (`tests/synthetic_fonts.py`); never
  copy an installed font into the repository or a fixture.
- `lazuli class set FAMILY --genre ID [--subclass ID] [--url URL]`, `lazuli class list [FAMILY]`,
  and `lazuli class remove FAMILY` keep your own class for a family: a genre, an optional subclass,
  and an optional link that lazuli never opens. It outranks catalogs for the class and nothing
  else; licenses and scripts still come from catalogs. It is kept only in your cache database
  (`user_class.py`; the table and view keep their internal names `user_label` and `v_font_label`).
- Catalogs live in `cli/lazuli/catalog/`: `net.py` (the only way to reach a site: robots.txt, pacing
  kept across runs, the lazuli User-Agent, Blocked on 401/403/429, CAPTCHA, or sign-in pages),
  `store.py`, `match.py`, `labels.py` (the `mapped` vocabulary), `cli.py` (`lazuli catalog sync|lookup|
  status`), and one module per source registered by priority in `catalog/__init__.py`.
  `lazuli setup` downloads release files through the same module, streamed to disk, with the same rules.

## Git and releases

- Check that `git config user.name` and `user.email` are set before committing; ask the user
  rather than setting them globally. Small commits with clear messages.
- Ask before pushing, creating remotes, or tagging. Installs follow the `release` branch, which is
  moved by hand to each release tag once the tag's CI passes. One version per release goes into
  every manifest and catalog, and it must change between releases.
- When a fact in `install/harnesses.yaml` `unverified` is confirmed on a real harness, move it out
  of `unverified`, fix the commands if needed, and say in the commit how and when it was checked.

## Rules for every session

- Never modify files outside this repository unless the user asks.
- Ask first before creating remotes, pushing, opening pull requests, publishing, spending money,
  installing software globally, changing global git config, or changing a harness's global
  settings or installed plugins.
- No credentials, tokens, license keys, payment data, or private receipts in any file or commit.
- Commercial, subscription, or synced font files and media never leave the machine they are on, nor does
  data extracted from them (outlines, tables, glyph data; a family name sent to a catalog lookup is not
  font data), and no lazuli database or other large local data goes into the repository. This limits where
  files and extracted data go, not which fonts a design may use: recommending and using licensed fonts,
  Adobe Fonts included (on the web through the user's Adobe web project), is fine.
- Data derived from Adobe Fonts (names, coverage, measurements) never goes into tests, fixtures,
  calibrations, evaluations, or training sets, and lazuli never opens Adobe Fonts files: on macOS it reads them
  through the operating system's font API (`cli/lazuli/coretext.py`); nowhere else are they listed.
  The test suite starts every test with `LAZULI_FONT_ROOTS` set to an empty folder, and eval scoring
  reads only the OFL evaluation font database given with `--font-db`.
