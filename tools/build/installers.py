"""Install scripts and INSTALLATION.md, generated from install/harnesses.yaml.

generate(doc, version) returns install/install.sh (POSIX sh, macOS and Linux), install/install.ps1
(Windows PowerShell 5.1 or later, and PowerShell 7), and INSTALLATION.md. Every harness fact,
command, and note comes from the harness definitions; the templates here hold only the generic
engine (options, detection, questions, dry runs, logging) that runs them.

Placeholders (install/harnesses.schema.yaml): {repo}, {ref}, and {catalog} are filled here;
{plugin}, {skill}, {agent}, {sha}, and {checkout} are filled by the scripts at run time. Commands stay argv
lists in both scripts: each item becomes one quoted word, and nothing is passed to eval.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

PLACEHOLDER = re.compile(r"\{([a-z]+)\}")
RUNTIME = ("agent", "plugin", "skill", "sha", "checkout")
LOOPS = ("agent", "plugin", "skill")          # nesting order when a step uses more than one
SH_SAFE = re.compile(r"[A-Za-z0-9_./:@+,-]+")   # sh words that need no quotes
PS_SAFE = re.compile(r"[A-Za-z0-9_./:+-][A-Za-z0-9_./:@+-]*")
KINDS = ("run", "copy", "remove", "manual")

# How to put a tool's bin directory on PATH, by the tool that installed the CLI (cli.install needs).
PATH_HINTS = {"uv": ["uv", "tool", "update-shell"], "pipx": ["pipx", "ensurepath"]}

# Words for the closed enums of harnesses.schema.yaml (output formats and mechanism kinds).
FORMAT_LABELS = {
    "agent-skill": "Skills",
    "claude-plugin-manifest": "Plugin manifest (Claude format)",
    "codex-plugin-manifest": "Plugin manifest (Codex format)",
    "antigravity-plugin-manifest": "Plugin manifest (Antigravity format)",
    "claude-catalog": "Catalog",
    "codex-catalog": "Catalog (Codex)",
    "hooks-json": "Hooks",
    "antigravity-hooks-json": "Hooks (Antigravity format)",
    "mcp-json": "MCP server",
    "claude-agent": "Critic agent (Claude format)",
    "codex-agent": "Critic agent (Codex format)",
    "antigravity-agent": "Critic agent (Antigravity format)",
    "omp-package": "Extension package",
    "pi-package": "Package manifest",
    "ts-extension": "Session-start extension",
    "gate-extension": "Exit-gate extension",
    "hermes-plugin": "Hermes plugin",
    "agents-md-snippet": "Instructions snippet",
}
VIA_LABELS = {
    "plugin-hook": "plugin hook",
    "plugin-agent": "plugin agent",
    "plugin-mcp": "plugin MCP configuration",
    "extension": "extension",
    "hermes-plugin-hook": "Hermes plugin hook",
    "agent-file": "agent file that the install script copies",
    "cli-register": "registered with the harness's own command",
    "instructions": "instructions",
    "none": "not available",
}
VIA_BY_HAND = "instructions only: the skills say what to run by hand"
MECHANISMS = (("session_start", "Session summary"), ("critic", "Separate critic"), ("exit_gate", "Exit gate"),
              ("pre_write", "Write guard"), ("mcp", "MCP"))
SH_VARS = {"plugin": "LL_plugin", "skill": "LL_skill", "agent": "LL_agent", "sha": "LL_sha", "checkout": "LL_checkout"}
PS_VARS = {"plugin": "$Plugin", "skill": "$Skill", "agent": "$Agent", "sha": "$script:Sha", "checkout": "$script:Checkout"}
DOC_VARS = {"agent": "<agent>", "sha": "<commit>", "checkout": "<checkout>"}


def generate(doc: dict, version: str) -> dict[str, str]:
    """Map of repo-relative path -> file text for the installers and the install guide."""
    g = _Gen(doc, version)
    files = {"install/install.sh": g.install_sh(), "install/install.ps1": g.install_ps1(),
             "INSTALLATION.md": g.installation_md()}
    for path in ("install/install.sh", "install/install.ps1"):
        if not files[path].isascii():      # Windows PowerShell 5.1 reads a BOM-less script as ANSI
            raise ValueError(f"{path}: non-ASCII text from install/harnesses.yaml")
    return files


# --- quoting ---------------------------------------------------------------------------------------

def sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def sh_arg(text: str) -> str:
    return text if SH_SAFE.fullmatch(text) else sh_quote(text)


def ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _slug(title: str) -> str:
    """GitHub's heading anchor."""
    return re.sub(r"[^a-z0-9 _-]", "", title.lower()).replace(" ", "-")


def _prose(text: str) -> str:
    """Free text from the harness definitions, safe in Markdown (a bare <word> would read as HTML)."""
    return text.replace("<", "\\<")


def _code(text: str) -> str:
    return f"``{text}``" if "`" in text else f"`{text}`"


class _Gen:
    def __init__(self, doc: dict, version: str):
        self.doc = doc
        self.version = version
        repo = doc["repo"]
        self.repo = f"{repo['owner']}/{repo['name']}"
        self.ref = repo["ref"]
        self.catalog = repo["catalog"]
        self.static = {"repo": self.repo, "ref": self.ref, "catalog": self.catalog}
        self.web = f"https://github.com/{self.repo}"
        self.raw = f"https://raw.githubusercontent.com/{self.repo}/{self.ref}"
        self.docs = f"{self.web}/blob/{self.ref}/INSTALLATION.md"
        self.plugins = doc["plugins"]
        self.plugin_names = [p["name"] for p in self.plugins]
        self.skills = [s for p in self.plugins for s in p["skills"]]
        self.harnesses = doc["harnesses"]
        # Harnesses whose commands are unconfirmed (status: experimental) install only when --harness names them.
        self.experimental = [h["id"] for h in self.harnesses if h.get("status") == "experimental"]
        self.outputs = {o["id"]: o for o in doc["outputs"]}
        self.cli = doc["cli"]
        # Agent files (copy/remove steps) belong to the plugin that lists the agent: <prefix><agent>.
        self.agent_owner = {f"{p['prefix']}{a}": p["name"] for p in self.plugins for a in p.get("agents", [])}
        # Command names stay lower case at the start of a sentence (omp, pi, hermes, ...).
        self.command_names = {st["run"][0] for h in self.harnesses for ph in ("install", "update", "uninstall", "verify")
                              for st in h.get(ph, []) if "run" in st}
        self.command_names |= {c for h in self.harnesses for c in h.get("detect", {}).get("commands", [])}

    def sentence(self, text: str) -> str:
        text = text.strip()
        first = text.split(" ", 1)[0]
        if first.isalpha() and first.islower() and first not in self.command_names:
            text = text[:1].upper() + text[1:]
        return _prose(text if text.endswith((".", "!", "?")) else text + ".")

    # --- step model --------------------------------------------------------------------------------

    def segs(self, text: str) -> list[tuple[str, str]]:
        """Split a template into ("lit", text) and ("var", runtime placeholder) parts."""
        out: list[tuple[str, str]] = []

        def lit(s: str) -> None:
            if not s:
                return
            if out and out[-1][0] == "lit":
                out[-1] = ("lit", out[-1][1] + s)
            else:
                out.append(("lit", s))

        pos = 0
        for m in PLACEHOLDER.finditer(text):
            lit(text[pos:m.start()])
            pos = m.end()
            name = m.group(1)
            if name in self.static:
                lit(self.static[name])
            elif name in RUNTIME:
                out.append(("var", name))
            else:
                raise ValueError(f"unknown placeholder {{{name}}} in {text!r}")
        lit(text[pos:])
        return out

    def fill(self, text: str) -> str:
        """Static placeholders only; for free text such as notes."""
        parts = self.segs(text)
        if any(k == "var" for k, _ in parts):
            raise ValueError(f"run-time placeholder in free text: {text!r}")
        return "".join(v for _, v in parts)

    def step(self, raw: dict, h: dict) -> dict:
        kinds = [k for k in KINDS if k in raw]
        if len(kinds) != 1:
            raise ValueError(f"{h['id']}: a step needs exactly one of {KINDS}: {raw}")
        kind = kinds[0]
        if raw.get("when", "all-plugins") != "all-plugins":
            raise ValueError(f"{h['id']}: unknown when {raw['when']!r}")
        st = {"kind": kind, "confirm": bool(raw.get("confirm")), "all": raw.get("when") == "all-plugins",
              "note": self.fill(raw.get("note", "")), "among": [p for p in self.plugin_names if p in raw.get("plugins", [])],
              "owner": None, "expect": self.segs(raw["expect"]) if "expect" in raw else None}
        if kind == "run":
            templates = list(raw["run"])
            st["argv"] = [self.segs(t) for t in templates]
            if [k for k, _ in st["argv"][0]] != ["lit"]:
                raise ValueError(f"{h['id']}: the command name must be literal: {raw['run']}")
        elif kind == "copy":
            templates = [raw["copy"]["from"], raw["copy"]["to"]]
            st["src"] = self.segs(raw["copy"]["from"])
            st["dest"] = self.segs(self._home(raw["copy"]["to"]))
            st["owner"] = self.agent_owner.get(PurePosixPath(raw["copy"]["from"]).stem)
        elif kind == "remove":
            templates = [raw["remove"]]
            st["dest"] = self.segs(self._home(raw["remove"]))
            st["owner"] = self.agent_owner.get(PurePosixPath(raw["remove"]).stem)
        else:
            templates = [raw["manual"]]
            st["text"] = self.segs(raw["manual"])
        used = {n for t in templates for n in PLACEHOLDER.findall(t)}
        st["loops"] = [n for n in LOOPS if n in used]
        st["expect_loops"] = [n for n in LOOPS if n in PLACEHOLDER.findall(raw.get("expect", "")) and n not in used]
        for name in ("sha", "checkout"):
            if name in PLACEHOLDER.findall(raw.get("expect", "")):
                raise ValueError(f"{h['id']}: {{{name}}} in an expectation")
        if {"plugin", "skill"} <= used:
            raise ValueError(f"{h['id']}: a step cannot loop over both plugins and skills: {raw}")
        if "agent" in used and not h.get("agents"):
            raise ValueError(f"{h['id']}: {{agent}} without agents")
        st["sha"] = "sha" in used
        st["checkout"] = "checkout" in used
        return st

    @staticmethod
    def _home(path: str) -> str:
        if not path.startswith("~/"):
            raise ValueError(f"not a home path: {path!r}")
        return path[2:]

    def steps(self, h: dict, phase: str) -> list[dict]:
        return [self.step(raw, h) for raw in h.get(phase, [])]

    @staticmethod
    def narrows(st: dict) -> bool:
        """Whether the step depends on which plugins are selected."""
        return bool(st["all"] or st["owner"] or st["among"] or {"plugin", "skill"} & set(st["loops"]))

    def whole_package(self, steps: list[dict]) -> bool:
        """A phase with changes that ignore --plugin (one package carries every plugin)."""
        changes = [s for s in steps if s["kind"] != "manual"]
        return bool(changes) and not any(self.narrows(s) for s in changes)

    @staticmethod
    def commands(steps: list[dict]) -> list[str]:
        names: list[str] = []
        for st in steps:
            if st["kind"] == "run" and st["argv"][0][0][1] not in names:
                names.append(st["argv"][0][0][1])
        return names

    def display(self, st: dict) -> str:
        """Human text for a step, with run-time placeholders shown as <name>."""
        if st["kind"] == "run":
            return " ".join(self._doc_word(w, {}) for w in st["argv"])
        if st["kind"] == "copy":
            return f"copy {self.raw}/{self._doc_text(st['src'], {})} to ~/{self._doc_text(st['dest'], {})}"
        if st["kind"] == "remove":
            dest = self._doc_text(st["dest"], {})
            return f"remove folder if empty: ~/{dest}" if dest.endswith("/") else f"remove ~/{dest}"
        return self._doc_text(st["text"], {})

    def _doc_text(self, parts: list, values: dict) -> str:
        return "".join(v if k == "lit" else values.get(v, DOC_VARS.get(v, f"<{v}>")) for k, v in parts)

    def _doc_word(self, parts: list, values: dict) -> str:
        """One argv item for a document: quoted like sh, run-time placeholders left as <name>."""
        out = []
        for k, v in parts:
            if k == "var" and v not in values:
                out.append(DOC_VARS.get(v, f"<{v}>"))
            else:
                text = v if k == "lit" else values[v]
                out.append(text if SH_SAFE.fullmatch(text) else sh_quote(text))
        return "".join(out) or "''"

    def snippets(self, h: dict) -> list[str]:
        return [self.outputs[o]["path"] for o in h["consumes"]
                if self.outputs[o]["format"] == "agents-md-snippet"]

    def lookfor(self, h: dict) -> str:
        det = h.get("detect", {})
        parts = [f"command {c}" for c in det.get("commands", [])] + [f"folder {d}" for d in det.get("dirs", [])]
        parts += [f"folder {d}" for a in h.get("agents", []) for d in a["dirs"]]
        return " or ".join(parts) if parts else "nothing (no detection rule)"

    # --- install.sh --------------------------------------------------------------------------------

    def sh_word(self, parts: list) -> str:
        words = [sh_arg(v) if k == "lit" else f'"${SH_VARS[v]}"' for k, v in parts]
        return "".join(words) or "''"

    def sh_home(self, parts: list) -> str:
        return '"$HOME"/' + self.sh_word(parts) if parts else '"$HOME"'

    def sh_agents_var(self, h: dict) -> str:
        return "LL_AGENTS_" + h["id"].replace("-", "_")

    def sh_wrap(self, st: dict, h: dict, loops: list[str], guards: bool = True) -> list[tuple[str, str]]:
        pairs = []
        if guards:
            if st["all"]:
                pairs.append(("if all_plugins; then", "else\n  skip_all " + sh_quote(self.display(st)) + "\nfi"))
            if st["owner"]:
                pairs.append((f"if selected {st['owner']}; then", "fi"))
            if st["among"] and "plugin" not in loops:
                pairs.append((f'if [ -n "$(pick {sh_quote(" ".join(st["among"]))})" ]; then', "fi"))
        for n in loops:
            if n == "agent":
                source = "$" + self.sh_agents_var(h)
            elif n == "plugin":
                source = f'$(pick {sh_quote(" ".join(st["among"]))})' if st["among"] else "$LL_PLUGINS"
            else:
                source = "$LL_SKILLS"
            pairs.append((f"for {SH_VARS[n]} in {source}; do", "done"))
        if guards and st["sha"]:
            pairs.append(("if need_sha; then", "fi"))
        if guards and st["checkout"]:
            pairs.append(("if need_checkout; then", "fi"))
        return pairs

    @staticmethod
    def nest(pairs: list[tuple[str, str]], body: list[str], indent: str) -> list[str]:
        lines = []
        for i, (opener, _) in enumerate(pairs):
            lines.append(indent + "  " * i + opener)
        depth = indent + "  " * len(pairs)
        lines += [depth + b for b in body]
        for i, (_, closer) in reversed(list(enumerate(pairs))):
            for part in closer.split("\n"):
                lines.append(indent + "  " * i + part)
        return lines

    def sh_step(self, st: dict, h: dict, indent: str) -> list[str]:
        ask = "1" if st["confirm"] else "0"
        note = sh_quote(st["note"]) if st["note"] else "''"
        if st["kind"] == "run":
            call = f"step_run {ask} {note} " + " ".join(self.sh_word(w) for w in st["argv"])
        elif st["kind"] == "copy":
            call = f"step_copy {ask} {note} {self.sh_word(st['src'])} {self.sh_home(st['dest'])}"
        elif st["kind"] == "remove":
            call = f"step_remove {ask} {note} {self.sh_home(st['dest'])}"
        else:
            call = f"step_manual {self.sh_word(st['text'])}"
        return self.nest(self.sh_wrap(st, h, st["loops"]), [call], indent)

    def sh_check(self, st: dict, h: dict, indent: str) -> list[str]:
        if st["kind"] == "manual":
            return self.nest(self.sh_wrap(st, h, st["loops"], guards=False),
                             [f"check_manual {self.sh_word(st['text'])}"], indent)
        if st["kind"] != "run":
            raise ValueError(f"{h['id']}: verify steps are run or manual")
        body = ["check_cmd " + " ".join(self.sh_word(w) for w in st["argv"])]
        if st["expect"]:
            body += self.nest(self.sh_wrap(st, h, st["expect_loops"], guards=False),
                              [f"check_expect {self.sh_word(st['expect'])}"], "")
        return self.nest(self.sh_wrap(st, h, st["loops"], guards=False), body, indent)

    def sh_harness(self, h: dict) -> list[str]:
        fn = "h_" + h["id"].replace("-", "_")
        name = sh_quote(h["name"])
        det = h.get("detect", {})
        lines = [f"# {h['name']}", f"{fn}() {{", "  case $1 in", f"  name) LL_H={name} ;;", "  detect)", "    LL_WHY="]
        for c in det.get("commands", []):
            lines.append(f"    if has_cmd {sh_arg(c)}; then LL_WHY=\"${{LL_WHY:+$LL_WHY, }}command {c}\"; fi")
        for d in det.get("dirs", []):
            lines.append(f"    if has_dir {self.sh_home(self.segs(self._home(d)))}; then "
                         f"LL_WHY=\"${{LL_WHY:+$LL_WHY, }}folder {d}\"; fi")
        if h.get("agents"):
            var = self.sh_agents_var(h)
            lines.append(f"    {var}=")
            for a in h["agents"]:
                test = " || ".join(f"has_dir {self.sh_home(self.segs(self._home(d)))}" for d in a["dirs"])
                lines.append(f"    if {test}; then {var}=\"${{{var}:+${var} }}{a['id']}\"; "
                             f"LL_WHY=\"${{LL_WHY:+$LL_WHY, }}agent {a['id']}\"; fi")
        lines += ['    [ -n "$LL_WHY" ] ;;',
                  f"  lookfor) LL_LOOK={sh_quote(self.lookfor(h))} LL_ANCHOR={sh_quote('#' + _slug(h['name']))} ;;"]
        for phase in ("install", "update", "uninstall"):
            steps = self.steps(h, phase)
            lines.append(f"  {phase})")
            lines.append("    begin " + " ".join([name] + [sh_arg(c) for c in self.commands(steps)]))
            if h.get("min_version") and phase != "uninstall":
                lines.append(f"    note {sh_quote('needs version ' + h['min_version'] + ' or later')}")
            if self.whole_package(steps):
                lines.append("    note_whole")
            for st in steps:
                lines += self.sh_step(st, h, "    ")
            if phase != "uninstall":
                lines += [f"    snippet {sh_arg(p)}" for p in self.snippets(h)]
            lines.append("    ;;")
        lines.append("  verify)")
        for st in self.steps(h, "verify"):
            lines += self.sh_check(st, h, "    ")
        lines += ["    : ;;", "  esac", "}"]
        return lines

    def sh_cli(self) -> list[str]:
        lines = ["# The CLI: the first tool on PATH wins.", "cli_tool() {", "  case $1 in"]
        for phase in ("install", "uninstall"):
            tests = "; ".join(f"if has_cmd {sh_arg(a['needs'])}; then printf '%s' {sh_arg(a['needs'])}; return 0; fi"
                              for a in self.cli[phase])
            lines.append(f"  {phase}) {tests} ;;")
        lines += ["  esac", "  return 1", "}", "", "cli_steps() {", "  case $1:$2 in"]
        for phase in ("install", "uninstall"):
            for alt in self.cli[phase]:
                steps = [self.step(raw, {"id": "cli"}) for raw in alt["steps"]]
                lines.append(f"  {phase}:{alt['needs']})")
                for st in steps:
                    lines += self.sh_step(st, {"id": "cli"}, "    ")
                lines.append("    ;;")
        lines += ["  esac", "}", "", "cli_verify() {"]
        for raw in self.cli["verify"]:
            st = self.step(raw, {"id": "cli"})
            if st["kind"] != "run" or st["loops"] or st["expect_loops"]:
                raise ValueError("cli.verify steps are commands without run-time placeholders")
            expect = self.sh_word(st["expect"]) if st["expect"] else "''"
            lines.append(f"  verify_cmd {expect} " + " ".join(self.sh_word(w) for w in st["argv"]))
        lines += ["}", "", "path_hint() {", '  case $LL_TOOL in']
        for alt in self.cli["install"]:
            hint = PATH_HINTS.get(alt["needs"])
            if hint:
                lines.append(f"  {alt['needs']}) printf '%s' {sh_quote('; or run: ' + ' '.join(hint))} ;;")
        lines += ["  esac", "}"]
        return lines

    def usage(self, script: str) -> str:
        cli = ", ".join(self.cli["entry_points"])
        needs = " or ".join(a["needs"] for a in self.cli["install"])
        return "\n".join([
            f"Usage: {script} [options]",
            "",
            f"Installs the LapisLazuli CLI ({cli}) with {needs} and adds the plugins to every",
            "harness it finds. Guide: " + self.docs,
            "",
            "Options:",
            "  --dry-run        print every command it would run; change nothing",
            "  --harness ID     only this harness (repeatable): " + ", ".join(h["id"] for h in self.harnesses),
            *([f"                   experimental, so installed only when named here: {', '.join(self.experimental)}"]
              if self.experimental else []),
            "  --plugin NAME    only this plugin (repeatable; default: all): " + ", ".join(self.plugin_names),
            f"  --update         run the update steps and reinstall the CLI from {self.ref}",
            "  --uninstall      run the removal steps; a catalog goes only with every plugin, and",
            "                   the CLI only with every plugin from every harness",
            "  --yes, -y        answer yes to every question",
            "  --help, -h       show this help",
        ])

    def install_sh(self) -> str:
        skills = "\n".join(f"  {p['name']}) printf '%s' {sh_quote(' '.join(p['skills']))} ;;" for p in self.plugins)
        harnesses: list[str] = []
        for h in self.harnesses:
            harnesses += self.sh_harness(h) + [""]
        dispatch = "\n".join(f"  {h['id']}) h_{h['id'].replace('-', '_')} \"$2\" ;;" for h in self.harnesses)
        agent_vars = "\n".join(f"{self.sh_agents_var(h)}=" for h in self.harnesses if h.get("agents"))
        values = {
            "@VERSION@": sh_quote(self.version), "@REPO@": sh_quote(self.repo), "@REF@": sh_quote(self.ref),
            "@RAW@": sh_quote(self.raw), "@DOCS@": sh_quote(self.docs),
            "@PLUGINS@": sh_quote(" ".join(self.plugin_names)),
            "@HARNESSES@": sh_quote(" ".join(h["id"] for h in self.harnesses)),
            "@EXPERIMENTAL@": sh_quote(" ".join(self.experimental)),
            "@CLI_NAME@": sh_quote("CLI (" + ", ".join(self.cli["entry_points"]) + ")"),
            "@CLI_NEEDS@": sh_quote(" or ".join(a["needs"] for a in self.cli["install"])),
            "@AGENT_VARS@": agent_vars, "@USAGE@": self.usage("install.sh"), "@SKILLS@": skills,
            "@CLI@": "\n".join(self.sh_cli()), "@HARNESS_FUNCTIONS@": "\n".join(harnesses).rstrip("\n"),
            "@DISPATCH@": dispatch, "@PICK@": SH_PICK if self.uses_among() else "",
        }
        return _render(SH_TEMPLATE, values)

    def uses_among(self) -> bool:
        return any(st.get("plugins") for h in self.harnesses for ph in ("install", "update", "uninstall")
                   for st in h.get(ph, []))

    # --- install.ps1 -------------------------------------------------------------------------------

    def ps_word(self, parts: list) -> str:
        words = [ps_quote(v) if k == "lit" else PS_VARS[v] for k, v in parts]
        if not words:
            return "''"
        if len(words) == 1 and parts[0][0] == "lit":
            return words[0]
        if parts[0][0] == "var":
            words.insert(0, "''")
        return "(" + " + ".join(words) + ")"

    def ps_argv(self, argv: list) -> str:
        return "@(" + ", ".join(self.ps_word(w) for w in argv) + ")"

    def ps_home(self, parts: list) -> str:
        return f"(Get-HomePath {self.ps_word(parts)})"

    def ps_wrap(self, st: dict, h: dict, loops: list[str], guards: bool = True) -> list[tuple[str, str]]:
        pairs = []
        if guards:
            if st["all"]:
                pairs.append(("if (Test-AllPlugins) {", "} else {\n  Skip-All " + ps_quote(self.display(st)) + "\n}"))
            if st["owner"]:
                pairs.append((f"if (Test-Selected {ps_quote(st['owner'])}) {{", "}"))
            if st["among"] and "plugin" not in loops:
                among = "@(" + ", ".join(ps_quote(p) for p in st["among"]) + ")"
                pairs.append((f"if (@(Select-Among {among}).Count -gt 0) {{", "}"))
        for n in loops:
            if n == "agent":
                source = f"@($script:Agents[{ps_quote(h['id'])}])"
            elif n == "plugin":
                source = ("@(Select-Among @(" + ", ".join(ps_quote(p) for p in st["among"]) + "))"
                          if st["among"] else "@($script:Plugins)")
            else:
                source = "@($script:Skills)"
            pairs.append((f"foreach ({PS_VARS[n]} in {source}) {{", "}"))
        if guards and st["sha"]:
            pairs.append(("if (Get-Sha) {", "}"))
        if guards and st["checkout"]:
            pairs.append(("if (Get-Checkout) {", "}"))
        return pairs

    def ps_step(self, st: dict, h: dict, indent: str) -> list[str]:
        ask = "$true" if st["confirm"] else "$false"
        note = ps_quote(st["note"])
        if st["kind"] == "run":
            call = f"Invoke-Run {ask} {note} {self.ps_argv(st['argv'])}"
        elif st["kind"] == "copy":
            call = f"Invoke-Copy {ask} {note} {self.ps_word(st['src'])} {self.ps_home(st['dest'])}"
        elif st["kind"] == "remove":
            call = f"Invoke-Remove {ask} {note} {self.ps_home(st['dest'])}"
        else:
            call = f"Invoke-Manual {self.ps_word(st['text'])}"
        return self.nest(self.ps_wrap(st, h, st["loops"]), [call], indent)

    def ps_check(self, st: dict, h: dict, indent: str) -> list[str]:
        if st["kind"] == "manual":
            return self.nest(self.ps_wrap(st, h, st["loops"], guards=False),
                             [f"Add-CheckManual {self.ps_word(st['text'])}"], indent)
        body = [f"Add-CheckCmd {self.ps_argv(st['argv'])}"]
        if st["expect"]:
            body += self.nest(self.ps_wrap(st, h, st["expect_loops"], guards=False),
                              [f"Add-CheckExpect {self.ps_word(st['expect'])}"], "")
        return self.nest(self.ps_wrap(st, h, st["loops"], guards=False), body, indent)

    def ps_harness(self, h: dict) -> list[str]:
        fn = "h_" + h["id"].replace("-", "_")
        name = ps_quote(h["name"])
        det = h.get("detect", {})
        lines = [f"# {h['name']}", f"function {fn}([string]$Phase) {{", "  switch ($Phase) {",
                 f"    'name' {{ $script:H = {name} }}", "    'detect' {", "      $script:Why = @()"]
        for c in det.get("commands", []):
            lines.append(f"      if (Test-Cmd {ps_quote(c)}) {{ $script:Why += {ps_quote('command ' + c)} }}")
        for d in det.get("dirs", []):
            lines.append(f"      if (Test-Dir {self.ps_home(self.segs(self._home(d)))}) "
                         f"{{ $script:Why += {ps_quote('folder ' + d)} }}")
        if h.get("agents"):
            key = ps_quote(h["id"])
            lines.append(f"      $script:Agents[{key}] = @()")
            for a in h["agents"]:
                test = " -or ".join(f"(Test-Dir {self.ps_home(self.segs(self._home(d)))})" for d in a["dirs"])
                lines.append(f"      if ({test}) {{ $script:Agents[{key}] += {ps_quote(a['id'])}; "
                             f"$script:Why += {ps_quote('agent ' + a['id'])} }}")
        lines += ["    }",
                  f"    'lookfor' {{ $script:Look = {ps_quote(self.lookfor(h))}; "
                  f"$script:Anchor = {ps_quote('#' + _slug(h['name']))} }}"]
        for phase in ("install", "update", "uninstall"):
            steps = self.steps(h, phase)
            cmds = "@(" + ", ".join(ps_quote(c) for c in self.commands(steps)) + ")"
            lines += [f"    '{phase}' {{", f"      Start-Phase {name} {cmds}"]
            if h.get("min_version") and phase != "uninstall":
                lines.append(f"      Add-Note {ps_quote('needs version ' + h['min_version'] + ' or later')}")
            if self.whole_package(steps):
                lines.append("      Write-WholeNote")
            for st in steps:
                lines += self.ps_step(st, h, "      ")
            if phase != "uninstall":
                lines += [f"      Add-Snippet {ps_quote(p)}" for p in self.snippets(h)]
            lines.append("    }")
        lines.append("    'verify' {")
        for st in self.steps(h, "verify"):
            lines += self.ps_check(st, h, "      ")
        lines += ["    }", "  }", "}"]
        return lines

    def ps_cli(self) -> list[str]:
        lines = ["# The CLI: the first tool on PATH wins.", "function Get-CliTool([string]$Phase) {"]
        for phase in ("install", "uninstall"):
            lines.append(f"  if ($Phase -eq '{phase}') {{")
            for alt in self.cli[phase]:
                lines.append(f"    if (Test-Cmd {ps_quote(alt['needs'])}) {{ return {ps_quote(alt['needs'])} }}")
            lines.append("  }")
        lines += ["  return ''", "}", "", "function Invoke-CliSteps([string]$Phase, [string]$Tool) {"]
        for phase in ("install", "uninstall"):
            for alt in self.cli[phase]:
                lines.append(f"  if ($Phase -eq '{phase}' -and $Tool -eq {ps_quote(alt['needs'])}) {{")
                for raw in alt["steps"]:
                    lines += self.ps_step(self.step(raw, {"id": "cli"}), {"id": "cli"}, "    ")
                lines.append("  }")
        lines += ["}", "", "function Invoke-CliVerify {"]
        for raw in self.cli["verify"]:
            st = self.step(raw, {"id": "cli"})
            expect = self.ps_word(st["expect"]) if st["expect"] else "''"
            lines.append(f"  Invoke-Verify {expect} {self.ps_argv(st['argv'])}")
        lines += ["}", "", "function Get-PathHint {"]
        for alt in self.cli["install"]:
            hint = PATH_HINTS.get(alt["needs"])
            if hint:
                lines.append(f"  if ($script:Tool -eq {ps_quote(alt['needs'])}) {{ return {ps_quote('; or run: ' + ' '.join(hint))} }}")
        lines += ["  return ''", "}"]
        return lines

    def install_ps1(self) -> str:
        skills = "\n".join(f"  {ps_quote(p['name'])} = @(" + ", ".join(ps_quote(s) for s in p["skills"]) + ")"
                           for p in self.plugins)
        harnesses: list[str] = []
        for h in self.harnesses:
            harnesses += self.ps_harness(h) + [""]
        dispatch = "\n".join(f"    {ps_quote(h['id'])} {{ h_{h['id'].replace('-', '_')} $Phase }}" for h in self.harnesses)
        agents = "; ".join(f"{ps_quote(h['id'])} = @()" for h in self.harnesses if h.get("agents"))
        values = {
            "@VERSION@": ps_quote(self.version), "@REPO@": ps_quote(self.repo), "@REF@": ps_quote(self.ref),
            "@RAW@": ps_quote(self.raw), "@DOCS@": ps_quote(self.docs),
            "@PLUGINS@": "@(" + ", ".join(ps_quote(p) for p in self.plugin_names) + ")",
            "@HARNESSES@": "@(" + ", ".join(ps_quote(h["id"]) for h in self.harnesses) + ")",
            "@EXPERIMENTAL@": "@(" + ", ".join(ps_quote(i) for i in self.experimental) + ")",
            "@CLI_NAME@": ps_quote("CLI (" + ", ".join(self.cli["entry_points"]) + ")"),
            "@CLI_NEEDS@": ps_quote(" or ".join(a["needs"] for a in self.cli["install"])),
            "@AGENTS@": "@{ " + agents + " }" if agents else "@{}",
            "@USAGE@": self.usage("install.ps1"), "@SKILLS@": skills, "@CLI@": "\n".join(self.ps_cli()),
            "@HARNESS_FUNCTIONS@": "\n".join(harnesses).rstrip("\n"), "@DISPATCH@": dispatch,
        }
        return _render(PS_TEMPLATE, values)

    # --- INSTALLATION.md ---------------------------------------------------------------------------

    def doc_values(self, st: dict, loops: list[str]) -> list[dict]:
        combos: list[dict] = [{}]
        for n in loops:
            if n == "plugin":
                values = st["among"] or self.plugin_names
            elif n == "skill":
                values = self.skills
            else:
                continue                           # {agent}, {sha}, and {checkout} stay <agent>, <commit>, <checkout>
            combos = [{**c, n: v} for c in combos for v in values]
        return combos

    def doc_step_notes(self, st: dict, h: dict) -> list[str]:
        notes = []
        if st["owner"]:
            notes.append(f"Only with the `{st['owner']}` plugin.")
        if st["among"]:
            notes.append("Only for " + ", ".join(f"`{p}`" for p in st["among"]) + ".")
        if st["all"]:
            notes.append("Only when you remove every plugin.")
        if st["confirm"]:
            notes.append("The install script asks before this step.")
        if st["note"]:
            notes.append(self.sentence(st["note"]))
        if st["sha"]:
            notes.append(f"`<commit>` is the full commit `{self.ref}` points to: "
                         f"`git ls-remote {self.web} refs/heads/{self.ref}`.")
        if st["checkout"]:
            notes.append(f"`<checkout>` is a clone of the `{self.ref}` branch: "
                         f"`git clone --depth 1 --branch {self.ref} {self.web}.git <checkout>`; the install script makes it "
                         "in a temporary folder and deletes it afterwards.")
        if "agent" in st["loops"]:
            notes.append("`<agent>` is the skills CLI id of each agent you use: "
                         + ", ".join(f"`{a['id']}`" for a in h["agents"]) + ".")
        return notes

    def doc_steps(self, h: dict, phase: str) -> list[str]:
        lines: list[str] = []
        block: list[str] = []

        def flush() -> None:
            if block:
                lines.extend(["```sh", *block, "```", ""])
                block.clear()

        for st in self.steps(h, phase):
            notes = self.doc_step_notes(st, h)
            if st["kind"] == "run":
                if notes:
                    flush()
                for values in self.doc_values(st, st["loops"]):
                    block.append(" ".join(self._doc_word(w, values) for w in st["argv"]))
                if notes:
                    flush()
                    lines += [" ".join(notes), ""]
                continue
            flush()
            if st["kind"] == "copy":
                source = f"{self.raw}/{self._doc_text(st['src'], {})}"
                destination = self._doc_text(st["dest"], {})
                lines += ["```sh", f"mkdir -p ~/\"{PurePosixPath(destination).parent}\"",
                          f"curl -fsSL {source} -o ~/\"{destination}\"", "```", ""]
                text = f"Copy {source} to `~/{destination}`."
            elif st["kind"] == "remove":
                dest = self._doc_text(st["dest"], {})
                text = (f"The installer removes `~/{dest}` only when it is an empty directory; "
                        "otherwise it lists the path for manual review." if dest.endswith("/")
                        else f"Remove `~/{dest}`.")
            else:
                text = "By hand: " + self.sentence(self._doc_text(st["text"], {}))
            lines += [" ".join([text, *notes]), ""]
        flush()
        return lines

    def doc_checks(self, steps: list[dict]) -> list[str]:
        lines = []
        for st in steps:
            if st["kind"] == "manual":
                for values in self.doc_values(st, st["loops"]):
                    lines.append("- " + self.sentence(self._doc_text(st["text"], values)))
                continue
            cmd = " ".join(self._doc_word(w, {}) for w in st["argv"])
            if not st["expect"]:
                lines.append(f"- {_code(cmd)}")
                continue
            expects = [_prose(self._doc_text(st["expect"], values))
                       for values in self.doc_values(st, st["expect_loops"] + st["loops"])]
            if len(expects) == 1:
                lines.append(f"- {_code(cmd)}: {expects[0]}")
            else:
                lines += [f"- {_code(cmd)}, expect:", *[f"  - {e}" for e in expects]]
        return lines

    def output_path(self, out: dict) -> str:
        path = out["path"]
        only = out.get("only", [])
        if len(only) == 1:
            path = path.replace("{plugin}", only[0])
        return path.replace("{plugin}", "<plugin>").replace("{skill}", "<skill>")

    @staticmethod
    def no_cli_note(h: dict) -> str:
        """The Install-step sentence saying the commands skip the CLI this harness runs by name ("" if none)."""
        parts = []                                  # (phrase, plural)
        via = h["session_start"]["via"]
        if via == "plugin-hook":
            parts.append(("plugin hooks", True))
        elif via == "hermes-plugin-hook":
            parts.append(("Hermes plugin hook", False))
        elif via == "extension":
            both = h["exit_gate"]["via"] == "extension"
            parts.append(("session-start and exit-gate extensions" if both else "session-start extension", both))
        if h["mcp"]["via"] in ("plugin-mcp", "cli-register"):
            parts.append(("MCP server", False))
        if not parts:
            return ""
        verb = "run" if len(parts) > 1 or parts[0][1] else "runs"
        return (f"These commands do not install the CLI. The {' and '.join(p for p, _ in parts)} {verb} "
                "programs from the CLI package by name (`lapis-design-hook` for hooks, `lapis-design` for MCP), "
                "so the CLI must be on the PATH the harness sees "
                "(see [CLI and optional components](#cli-and-optional-components)).")

    def doc_harness(self, h: dict) -> list[str]:
        L = [f"### {h['name']}", ""]
        if h.get("status") == "experimental":
            L += [f"Experimental: these commands come from {h['name']}'s documentation and have not been confirmed on a "
                  f"real install. The install scripts install it only when you name it with `--harness {h['id']}`; "
                  "finding its command or folder is not enough.", ""]
        first = self.plugins[0]
        example = h["invoke"].replace("{plugin}", first["name"]).replace("{skill}", first["skills"][0])
        template = h["invoke"].replace("{plugin}", "<plugin>").replace("{skill}", "<skill>")
        intro = f"Installed as: {h['form']}. Skills are invoked as `{template}`"
        intro += f" (for example `{example}`)." if example != h["invoke"] and " " not in example else "."
        if h.get("min_version"):
            intro += f" Needs version {h['min_version']} or later."
        L += [intro, "", "What gets installed:", ""]
        for oid in h["consumes"]:
            out = self.outputs[oid]
            only = out.get("only", [])
            extra = f" ({', '.join(only)} only)" if len(only) > 1 else ""
            L.append(f"- {FORMAT_LABELS[out['format']]}: `{self.output_path(out)}`{extra}")
        for key, label in MECHANISMS:
            m = h[key]
            via = VIA_LABELS[m["via"]] if m.get("output") or m["via"] != "instructions" else VIA_BY_HAND
            text = f"- {label}: {via}"
            if m.get("output"):
                text += f", from `{self.output_path(self.outputs[m['output']])}`"
            if m.get("event"):
                text += f", event `{m['event']}`"
            text += "."
            if m.get("note"):
                text += " " + self.sentence(m["note"])
            L.append(text)
        if h.get("skill_paths"):
            L += ["", "The harness also reads skills from: " + ", ".join(_code(p) for p in h["skill_paths"]) + "."]
        L.append("")
        for phase, title in (("install", "Install"), ("update", "Update"), ("uninstall", "Uninstall")):
            L += [f"**{title}**", ""]
            steps = self.steps(h, phase)
            if self.whole_package(steps):
                L += ["These steps cover every plugin at once; `--plugin` does not narrow them.", ""]
            if phase == "install" and (note := self.no_cli_note(h)):
                L += [note, ""]
            L += self.doc_steps(h, phase)
        L += ["**Check**", "", *self.doc_checks(self.steps(h, "verify")), ""]
        for key, title in (("trust", "Needs your approval"), ("conflicts", "Conflicts"),
                           ("unverified", "Not yet confirmed")):
            if h.get(key):
                L += [f"**{title}**", "", *[f"- {_prose(t)}" for t in h[key]], ""]
        L += [f"Sources (checked {h.get('checked', self.doc['checked'])}): " + ", ".join(f"<{u}>" for u in h["sources"]) + ".", ""]
        return L

    def installation_md(self) -> str:
        sh_url = f"{self.raw}/install/install.sh"
        ps_url = f"{self.raw}/install/install.ps1"
        cli = ", ".join(f"`{e}`" for e in self.cli["entry_points"])
        needs = [a["needs"] for a in self.cli["install"]]
        exp = ", ".join(f"`{i}`" for i in self.experimental)
        L = ["<!-- Generated by tools/build/installers.py from install/harnesses.yaml; do not edit. -->", "",
             "# Installing LapisLazuli", "",
             f"LapisLazuli is design skills for AI agents in {len(self.plugins)} plugins, plus the CLI their hooks "
             f"and MCP server call (commands {cli}). This guide is generated for version {self.version}.", "",
             "| Plugin | What it does | Skills |", "|---|---|---|"]
        for p in self.plugins:
            L.append(f"| `{p['name']}` | {_prose(p['description'])} | " + ", ".join(f"`{s}`" for s in p["skills"]) + " |")
        L += ["",
              f"Every install follows the `{self.ref}` branch of <{self.web}>, which the maintainers move by hand "
              "to each release tag once that tag's CI passes. "
              "The install scripts, the CLI, the catalogs, and every harness read that repository from GitHub, "
              "so it must be reachable from your machine.", "",
              "## Quick install", "",
              f"The scripts are `install/install.sh` and `install/install.ps1` in the repository, fetched from "
              f"`{self.raw}/install/`. Run them with `--dry-run` first: it prints every command they would run "
              "and changes nothing. When the list looks right, run the same line without `--dry-run`.", "",
              "macOS and Linux:", "", "```sh",
              f'sh -c "$(curl -fsSL {sh_url})" install.sh --dry-run', "```", "",
              "Windows (Windows PowerShell 5.1 or later, or PowerShell 7):", "", "```powershell",
              f"& ([scriptblock]::Create((Invoke-RestMethod {ps_url}))) --dry-run", "```", "",
              "From a checkout, run `sh install/install.sh --dry-run`, or "
              "`powershell -NoProfile -ExecutionPolicy Bypass -File install\\install.ps1 --dry-run` "
              "(the policy applies to that one process).", "",
              "What the scripts do:", "",
              "1. Check the system, " + " and ".join(f"`{n}`" for n in needs)
              + ", and which harnesses are installed (see [Identify your harness](#identify-your-harness)).",
              f"2. Install the CLI with the first of {', '.join(f'`{n}`' for n in needs)} on PATH "
              "(see [CLI and optional components](#cli-and-optional-components)).",
              "3. For each harness found (an experimental one only when named), or each `--harness`, run the steps "
              "in its section below for the selected "
              "plugins. Steps marked as asking first wait for your answer (the default is no; `--yes` answers yes). "
              "Steps they cannot run because the harness command is missing, and steps only you can do, are listed "
              "at the end.",
              "4. Check the CLI with " + " and ".join(
                  _code(" ".join(s["run"])) for s in self.cli["verify"] if "run" in s)
              + ", and list each harness's checks.", "",
              "They never use sudo or administrator rights, never store secrets, never edit an instructions file, "
              "and print each change they made. Running them again is safe: a step that is already done is "
              "done again or reported unchanged.", "",
              "| Option | Effect |", "|---|---|",
              "| `--dry-run` | Print every command it would run and change nothing. |",
              "| `--harness ID` | Only this harness; repeat for more. IDs: "
              + ", ".join(f"`{h['id']}`" for h in self.harnesses) + ". A named harness that is not installed stops "
              "the script before any change."
              + (f" Experimental harnesses ({exp}) install only when named here." if exp else "") + " |",
              "| `--plugin NAME` | Only this plugin; repeat for more. Default: all ("
              + ", ".join(f"`{p}`" for p in self.plugin_names) + "). |",
              f"| `--update` | Run the update steps and reinstall the CLI from `{self.ref}`. |",
              "| `--uninstall` | Run the removal steps (see [Update and uninstall](#update-and-uninstall)). |",
              "| `--yes`, `-y` | Answer yes to every question. |",
              "| `--help`, `-h` | Show the options. |", "",
              "Exit codes: 0 when every step succeeded, 1 when a step or check failed or a named harness is "
              "missing, 2 for an unknown option, harness, or plugin.", "",
              "## Identify your harness", "",
              "The scripts treat a harness as installed when its command is on PATH or its folder exists."
              + (f" An experimental harness ({exp}) that is only found is skipped when installing, with a note; name it "
                 "with `--harness` to install it. Updating and removing treat it like any other harness." if exp else ""),
              "", "| Harness | Status | Command | Folder | Section |", "|---|---|---|---|---|"]
        for h in self.harnesses:
            link = f"[{h['name']}](#{_slug(h['name'])})"
            status = "Experimental" if h.get("status") == "experimental" else "-"
            det = h.get("detect", {})
            if det.get("commands") or det.get("dirs"):
                cmds = ", ".join(f"`{c}`" for c in det.get("commands", [])) or "-"
                dirs = ", ".join(f"`{d}`" for d in det.get("dirs", [])) or "-"
                L.append(f"| {h['name']} (`{h['id']}`) | {status} | {cmds} | {dirs} | {link} |")
            for a in h.get("agents", []):
                L.append(f"| {a['id']} | {status} | - | " + ", ".join(f"`{d}`" for d in a["dirs"]) + f" | {link} |")
        L += ["", "## Per-harness setup", "",
              "Each section lists the exact commands the scripts run, with the release filled in. Where a command "
              "names a plugin or a skill, the scripts run it once for each selected one.", "",
              "These commands install the plugins (or skills) only, not the CLI. Hooks and extensions run "
              "`lapis-design-hook`; MCP runs `lapis-design`. Both are plain programs on the PATH the harness "
              "sees: install the CLI as described under [CLI and optional components](#cli-and-optional-components). "
              "A missing hook runner is a non-blocking command-not-found diagnostic, not a denied write or "
              "Stop continuation; the skills still work and say what to run by hand.", ""]
        for h in self.harnesses:
            L += self.doc_harness(h)
        L += ["## CLI and optional components", "",
              f"Hooks and the MCP server call the CLI by name, so {cli} must be on the PATH the harness sees. "
              "The skills work without it and say what to run by hand. The scripts install it with the first tool "
              "on PATH:", ""]
        for alt in self.cli["install"]:
            L += [f"With {alt['needs']}:", "", "```sh",
                  *[" ".join(self._doc_word(w, {}) for w in self.step(s, {"id": "cli"})["argv"])
                    for s in alt["steps"] if "run" in s], "```", ""]
        L += ["If none of them is installed, install uv (<https://docs.astral.sh/uv/>) or pipx first. "
              "Check the CLI:", "", *self.doc_checks([self.step(s, {"id": "cli"}) for s in self.cli["verify"]]), ""]
        L += ["**Plugin/CLI version skew.** Every plugin hook runs "
              "`lapis-design-hook --plugin-version <plugin-version> <hook-name>`. This separate entry point is "
              "absent from old CLI installs: a failed executable lookup is non-blocking, unlike argparse's exit "
              "2 from an unknown `lapis-design hook` subcommand. The runner uses no shell wrapper and works as "
              "a plain program on macOS, Linux, and Windows.", "",
              "An installed runner skips unknown hooks/options and mismatched plugin/CLI versions with exit 0 "
              "and a one-line `systemMessage`, never a blocking decision. Version notices are claimed atomically "
              "under `.lapis/hooks/`, once per session and version pair (once per project without a session id). "
              "A read-only project may repeat the notice, but still never blocks. pi and Oh-My-Pi display it "
              "through notifications or stderr in headless mode; Hermes prints it on the first turn. "
              "Missing-runner diagnostics come from the harness and may repeat. Update the CLI and plugins "
              "together with the install script's `--update`, then restart the harness; a changed Codex hook "
              "must be trusted again in `/hooks`.", "",
              "Antigravity is stricter: it stops the tool call for a hook that exits non-zero or prints any JSON it "
              "does not read (a `systemMessage`, or `{}`). Its hooks call `lapis-design antigravity-hook "
              "--plugin-version <plugin-version> <hook-name>` followed by `|| exit 0`, so a missing or crashed "
              "runner prints nothing and the agent goes on, and a skipped hook's one line goes to stderr, which "
              "Antigravity writes to its CLI log (`~/.gemini/antigravity-cli/cli.log`). A CLI older than the plugin "
              "has no such subcommand: its argparse rejects it on stderr with status 2, which `|| exit 0` turns into "
              "no answer (checked 2026-10-06), so the hooks do nothing, without a notice, until the CLI is updated "
              "to the plugin's version.", "",
              "The exit-status contracts are documented in "
              "[Claude Code hooks](https://code.claude.com/docs/en/hooks#exit-code-output) and "
              "[Codex hooks](https://learn.chatgpt.com/docs/hooks#stop): exit 2 can block a write or continue a "
              "Stop; a failed command lookup cannot. Extensions instead require an explicit successful JSON "
              "denial/continuation and treat launch failures as no decision.", ""]
        hints = [f"`{' '.join(PATH_HINTS[n])}` ({n})" for n in needs if n in PATH_HINTS]
        if hints:
            L += ["When the commands are not found, the tool's bin folder is not on PATH: run "
                  + " or ".join(hints) + ", then open a new terminal and restart the harness.", ""]
        L += ["Optional: render and behavior checks drive Chromium. Run `playwright install chromium-headless-shell` "
              "with the Playwright in the CLI's environment, so the browser matches its version:", "", "```sh"]
        if "uv" in needs:
            L.append("uv tool run --offline --from lapis-design playwright install chromium-headless-shell   # uv")
        if "pipx" in needs:
            L += ["pipx inject --include-apps lapis-design playwright   # pipx: puts playwright on PATH",
                  "playwright install chromium-headless-shell"]
        L += ["```", ""]
        if "uv" in needs:
            L += ["`--offline` makes uv use only the installed `lapis-design` environment and never look the name up "
                  "on a package index. If uv says it cannot find `lapis-design`, the tool was installed with another "
                  "Python than uv's default; run that environment's own interpreter instead (`Scripts\\python.exe` "
                  "in place of `bin/python` on Windows):", "", "```sh",
                  '"$(uv tool dir)/lapis-design/bin/python" -m playwright install chromium-headless-shell', "```", ""]
        L += ["**Sandboxed and headless hosts.** Some agent hosts run commands in a sandbox where the bundled "
              "browser is installed but cannot start, the user cache cannot be written, or both. "
              "`lazuli doctor` reports whether the browser is installed, not whether it can start. "
              "When it cannot, `render check` and `behavior check` do not run; `plan check` and "
              "`slop lint --plan ... --source .` still do, and the agent lists the rest as not run.", "",
              "Render and behavior checks start Chromium, and lazuli-backed checks read the lazuli user cache; "
              "a sandboxed agent session must be allowed to do both. If a sandbox or permission blocks either, "
              "ask the user for permission once; if refused or impossible, report the check as not run with "
              "the exact error rather than treating it as a pass. Do not move `LAZULI_DB` into the project to "
              "bypass the restriction; if a project-local database is unavoidable, keep it outside version "
              "control and tell the user.", "",
              "When the cache is not writable, point the font database at a writable path outside version "
              "control and scan again:", "", "```sh", 'export LAZULI_DB="${TMPDIR:-/tmp}/lazuli.db"',
              "lazuli local fonts --summary", "```", "",
              "`lapis-design plan check`, `slop lint`, and `release check` read the same variable. "
              "The inventory then describes the sandbox, not your own computer. Both browser checks capture "
              "`http` or `https` on a host that is yours. You can serve the folder on loopback and check "
              "that address:", "", "```sh",
              "python3 -m http.server 8000 --bind 127.0.0.1 --directory .",
              "lapis-design render check http://127.0.0.1:8000/ --task <task>",
              "lapis-design behavior check http://127.0.0.1:8000/ --task <task> --plan .lapis/plans/<task>.yaml --stub .lapis/stub.yaml",
              "```", "",
              "An HTML file path or `file://` URL also works: the checks serve its folder read-only on "
              "127.0.0.1 for the run and record only the loopback HTTP URL. Other URL schemes are refused.", "",
              "### Portable role handoffs", "",
              "The CLI also provides offline `handoff export` and read-only `handoff check`. Reconcile the "
              "source intake and canonical plan first, then select a complete disclosure-approved scope:", "",
              "```sh",
              "lapis-design handoff export --plan .lapis/plans/task.yaml --scope reservation --role implementer --root . --out .lapis/handoffs/reservation.md",
              "lapis-design handoff check RETURN.md --against .lapis/handoffs/reservation.md --plan .lapis/plans/task.yaml --root .",
              "```", "",
              "Roles are design-head, implementer and reviewer. Receivers can read the Markdown without "
              "installed skills. The 32 KiB UTF-8 budget requires a smaller coherent scope, never truncation. "
              "Returns are proposals tied to exact input bytes: stale inputs are rejected, nothing is applied, "
              "and remote approval/test claims never become local records. The coordinator reviews and "
              "runs actual local checks. See [the protocol](src/shared/handoff/HANDOFF.md); manual web/Antigravity "
              "receipt does not claim native account or plugin integration.", "",
              "### Unattended runs", "",
              "`lapis-design next --task <task>` prints the one step of the procedure still to do, from the files "
              "under `.lapis/`, until it says done; done means every step ran on real inputs, not that the "
              "release gate passes. A harness's stop event can ask it: the exit gate continues an agent that is "
              "about to stop with that step only when `LAPIS_UNATTENDED=1` is set in the environment the harness "
              "runs in, and otherwise prints one line and never blocks. `LAPIS_UNATTENDED=1` is for an operator's "
              "design run: the gate is then active even when the agent wrote no plan, and its step is `brief` and "
              "then `plan`, named for the project folder unless `LAPIS_TASK` says otherwise; do not set it for other work. "
              "It continues at most three times in a row for one step and fifteen times in a session, then lets the "
              "agent stop and records the step that was left in `.lapis/gate/<task>.json`. Before the plan, a create "
              "run owes a brief record, `.lapis/answers/<task>.md`: what it read and looked up, and its answers to the "
              "questions the design needs. With nobody to ask it answers them itself and marks every answer `[assumed]` "
              "with its basis. A run that should ask its user instead, the brief's questions or the plan's approval, "
              "while you relay the answers, must be told so in its instructions; it then writes the questions to "
              "`.lapis/questions/<task>.md` and stops: `lapis-design next` says "
              "`waiting-for-user`, and the gate lets that stop pass without counting a continue, for two sets of "
              "questions before a plan exists and one after. A file of fewer than two words, or a set past those "
              "limits, is continued like any other stop; the agent records your answers in "
              "`.lapis/answers/<task>.md` and carries on. Claude Code, Codex, and Antigravity "
              "run it as the lapis plugin's `Stop` hook (Antigravity continues with `decision: continue`), Oh-My-Pi "
              "as `session_stop` and pi as `agent_before_settle` in the lapis exit-gate extension. Codex runs a plugin hook only after you trust it in `/hooks`, or "
              "for one run with `--dangerously-bypass-hook-trust` (use it only in an isolated `CODEX_HOME` whose "
              "hook sources you vetted); an untrusted hook is skipped without any message, so the gate is silently "
              "absent and the agent stops as it would without it. Without the gate the skills say to run "
              "`lapis-design next` by hand. The same switch turns on a write guard: the order is brief, references, "
              "plan, then code, and while a create run still owes one of them, an unattended agent's write of a page "
              "source file (HTML, CSS, script, or component) is refused with the next step named, as the lapis "
              "plugin's `PreToolUse` hook in Claude Code, Codex, and Antigravity, and as a `tool_call` handler of the same "
              "extension in Oh-My-Pi and pi. Files under `.lapis/`, other files, and anything outside the project "
              "pass, a refusal repeats at most three times for one step, and a page written through the shell is "
              "found afterwards (`release.procedure-order`). A person's session sees one line, once, and is never "
              "refused. Use reasoning or thinking at high or above for the agent that makes "
              "the work: in our runs, a low setting skipped the procedure.", "",
              "## Update and uninstall", "",
              f"`--update` runs each harness's update steps and reinstalls the CLI from `{self.ref}`. "
              "`--uninstall` runs the removal steps; with `--plugin`, only those plugins go. These steps run only "
              "when you remove every plugin, because they take every plugin with them:", ""]
        for h in self.harnesses:
            for st in self.steps(h, "uninstall"):
                if st["all"]:
                    L.append(f"- {h['name']}: {_code(self.display(st))}")
        L += ["", "The CLI is removed only when every plugin is removed from every harness (no `--plugin` and no "
              "`--harness`), with the first tool on PATH:", "", "```sh"]
        for alt in self.cli["uninstall"]:
            for s in alt["steps"]:
                if "run" in s:
                    L.append(" ".join(self._doc_word(w, {}) for w in self.step(s, {"id": "cli"})["argv"])
                             + f"   # {alt['needs']}")
        L += ["```", "", "Each harness section above has the exact update and removal commands.", "",
              "## Troubleshooting", "",
              "- Hook errors at session start, or the MCP server does not start: the harness cannot find the CLI "
              "on its PATH. Run `lazuli doctor` in a terminal; if it is not found, see "
              "[CLI and optional components](#cli-and-optional-components).",
              "- A harness was not found: the scripts look for its command on PATH or its folder (see "
              "[Identify your harness](#identify-your-harness)). Start the harness once, or install it, then run "
              "the script again.",
              *([f"- A harness was found but skipped because it is experimental ({exp}): run the script with "
                 "`--harness ID` to install it."] if exp else []),
              "- A step failed because it was already done: run the script with `--update` instead.", ""]
        for h in self.harnesses:
            items = [f"- Needs your approval: {_prose(t)}" for t in h.get("trust", [])]
            items += [f"- {_prose(t)}" for t in h.get("conflicts", [])]
            if items:
                L += [f"**{h['name']}**", "", *items, ""]
        L += ["## Instructions for agents", "",
              "If you are an agent installing LapisLazuli for a user:", "",
              "- Ask the user before you change any harness configuration, install a plugin, or run a script "
              "without `--dry-run`.",
              "- Run the script with `--dry-run` first and show the user what it would do.",
              "- Never store secrets: no tokens, keys, or passwords in any file, command, or setting.",
              "- Do not edit an instructions file (such as AGENTS.md) unless the user asks; the scripts print the "
              "snippet instead.",
              "- If you run commands by hand, use exactly the commands in the user's harness section.",
              "- Report what changed: the script's summary, and anything you did by hand.", ""]
        return "\n".join(L).rstrip("\n") + "\n"


def _render(template: str, values: dict[str, str]) -> str:
    out = template
    for key, value in values.items():
        out = out.replace(key, value)
    left = re.findall(r"@[A-Z_]+@", out)
    if left:
        raise ValueError(f"template markers left: {left}")
    return out


SH_PICK = r'''# pick LIST: the selected plugins that are in LIST, in catalog order.
pick() {
  LL_picked=
  for LL_p in $LL_PLUGINS; do
    if in_list "$LL_p" "$1"; then LL_picked="${LL_picked:+$LL_picked }$LL_p"; fi
  done
  printf '%s' "$LL_picked"
}
'''

SH_TEMPLATE = r'''#!/bin/sh
# shellcheck disable=SC2016  # harness text may hold a literal $ (Codex skill names)
# LapisLazuli installer for macOS and Linux (POSIX sh).
# Generated by tools/build/installers.py from install/harnesses.yaml; do not edit.
# Every harness command is an argv list from that file, run as quoted words; nothing is eval'd.
set -u

LL_VERSION=@VERSION@
LL_REPO=@REPO@
LL_REF=@REF@
LL_RAW=@RAW@
LL_DOCS=@DOCS@
LL_ALL_PLUGINS=@PLUGINS@
LL_ALL_HARNESSES=@HARNESSES@
LL_EXPERIMENTAL=@EXPERIMENTAL@
LL_CLI_NAME=@CLI_NAME@
LL_CLI_NEEDS=@CLI_NEEDS@
LL_NL='
'
LL_MODE=install
LL_DRY=0
LL_YES=0
LL_WANT_H=
LL_WANT_P=
LL_PLUGINS=
LL_SKILLS=
LL_TARGETS=
LL_H=
LL_MANUAL=0
LL_sha=
LL_SHA_STATE=
LL_checkout=
LL_CHECKOUT_STATE=
LL_CHECKOUT_DIR=
LL_TOOL=
LL_TODO=
LL_CHECKS=
LL_NOTES=
LL_CHANGES=
LL_FAILED=
LL_SNIPPETS=
LL_WHY=
LL_LOOK=
LL_ANCHOR=
@AGENT_VARS@

say() { printf '%s\n' "$*"; }
err() { printf '%s\n' "$*" >&2; }

usage() {
  cat <<'EOF'
@USAGE@
EOF
}

usage_error() {
  err "install.sh: $1"
  usage >&2
  exit 2
}

has_cmd() { command -v "$1" >/dev/null 2>&1; }
has_dir() { [ -d "$1" ]; }

# in_list WORD LIST: WORD (a slug) is one of the space-separated LIST.
in_list() {
  case $1 in '' | *[!a-z0-9-]*) return 1 ;; esac
  case " $2 " in *" $1 "*) return 0 ;; esac
  return 1
}

# skips_experimental ID: installing without --harness leaves out an experimental harness that was only found.
skips_experimental() {
  [ "$LL_MODE" = install ] && [ -z "$LL_WANT_H" ] && in_list "$1" "$LL_EXPERIMENTAL"
}

@PICK@selected() { in_list "$1" "$LL_PLUGINS"; }
all_plugins() { [ "$LL_PLUGINS" = "$LL_ALL_PLUGINS" ]; }

skills_of() {
  case $1 in
@SKILLS@
  esac
}

# sq WORD: WORD quoted for sh when it needs quotes.
sq() {
  case $1 in
    '') printf "''" ;;
    *[!A-Za-z0-9_./:@+,-]*)
      LL_s=$1
      LL_q=
      while :; do
        case $LL_s in
          *"'"*)
            LL_q=$LL_q${LL_s%%"'"*}"'\\''"
            LL_s=${LL_s#*"'"}
            ;;
          *)
            LL_q=$LL_q$LL_s
            break
            ;;
        esac
      done
      printf "'%s'" "$LL_q"
      ;;
    *) printf '%s' "$1" ;;
  esac
}

qargv() {
  LL_qa=
  for LL_a in "$@"; do LL_qa="$LL_qa${LL_qa:+ }$(sq "$LL_a")"; done
  printf '%s' "$LL_qa"
}

# Lists printed at the end.
todo() { LL_TODO="$LL_TODO- $1$LL_NL"; }
changed() { LL_CHANGES="$LL_CHANGES- $1$LL_NL"; }
failed() {
  LL_FAILED="$LL_FAILED- $1$LL_NL"
  say "  failed: $1"
}
note() {
  [ -n "$1" ] || return 0
  case "$LL_NL$LL_NOTES" in *"$LL_NL- $LL_H: $1$LL_NL"*) return 0 ;; esac
  LL_NOTES="$LL_NOTES- $LL_H: $1$LL_NL"
}
note_whole() {
  all_plugins || say "  note: $LL_H takes every plugin at once; --plugin does not narrow it"
}
check_cmd() { LL_CHECKS="$LL_CHECKS- $LL_H: $(qargv "$@")$LL_NL"; }
check_expect() { LL_CHECKS="$LL_CHECKS    expect: $1$LL_NL"; }
check_manual() { LL_CHECKS="$LL_CHECKS- $LL_H: $1$LL_NL"; }
snippet() {
  case "$LL_NL$LL_SNIPPETS$LL_NL" in *"$LL_NL$1$LL_NL"*) return 0 ;; esac
  LL_SNIPPETS="${LL_SNIPPETS:+$LL_SNIPPETS$LL_NL}$1"
}

print_block() {
  [ -n "$2" ] || return 0
  say ""
  say "$1"
  printf '%s' "$2" | while IFS= read -r LL_l; do say "$3$LL_l"; done
}

# ask QUESTION: yes only for y or yes (--yes answers for the user).
ask() {
  if [ "$LL_YES" = 1 ]; then
    say "  $1 [y/N] y (--yes)"
    return 0
  fi
  printf '  %s [y/N] ' "$1"
  LL_ans=
  IFS= read -r LL_ans || LL_ans=
  [ -t 0 ] || say "$LL_ans"
  case $LL_ans in [yY] | [yY][eE][sS]) return 0 ;; esac
  return 1
}

fetch() {
  if has_cmd curl; then
    command curl -fsSL -o "$2" "$1"
  elif has_cmd wget; then
    command wget -q -O "$2" "$1"
  else
    say "  neither curl nor wget is on PATH"
    return 1
  fi
}

# begin NAME [COMMAND...]: start a section; when a command is missing, its steps become a to-do list.
begin() {
  LL_H=$1
  shift
  LL_MANUAL=0
  LL_missing=
  for LL_c in "$@"; do
    has_cmd "$LL_c" || LL_missing="${LL_missing:+$LL_missing, }$LL_c"
  done
  say ""
  say "== $LL_H"
  if [ -n "$LL_missing" ]; then
    LL_MANUAL=1
    say "  not on PATH: $LL_missing; the steps are listed under 'To do by hand'"
  fi
}

skip_all() { say "  not now (only when every plugin is removed): $1"; }

# step_run ASK NOTE ARGV...: run one command; ASK 1 asks first.
step_run() {
  LL_ask=$1
  LL_note=$2
  shift 2
  LL_line=$(qargv "$@")
  note "$LL_note"
  if [ "$LL_MANUAL" = 1 ]; then
    todo "$LL_H: $LL_line"
    return 0
  fi
  if [ "$LL_DRY" = 1 ]; then
    if [ "$LL_ask" = 1 ] && [ "$LL_YES" = 0 ]; then
      say "  would ask, then run: $LL_line"
    else
      say "  would run: $LL_line"
    fi
    return 0
  fi
  if [ "$LL_ask" = 1 ]; then
    [ -z "$LL_note" ] || say "  note: $LL_note"
    if ! ask "Run $LL_line ?"; then
      say "  skipped: $LL_line"
      todo "$LL_H (you declined): $LL_line"
      return 0
    fi
  fi
  say "  run: $LL_line"
  command "$@"
  LL_st=$?
  if [ "$LL_st" -eq 0 ]; then
    changed "$LL_H: ran $LL_line"
  else
    failed "$LL_H: $LL_line (exit $LL_st)"
  fi
  return 0
}

# step_copy ASK NOTE SOURCE DEST: copy SOURCE (a repository path at the release ref) to DEST.
step_copy() {
  LL_ask=$1
  LL_note=$2
  LL_url="$LL_RAW/$3"
  LL_dest=$4
  note "$LL_note"
  if [ "$LL_MANUAL" = 1 ]; then
    todo "$LL_H: copy $LL_url to $LL_dest"
    return 0
  fi
  if [ "$LL_DRY" = 1 ]; then
    if [ "$LL_ask" = 1 ] && [ "$LL_YES" = 0 ]; then
      say "  would ask, then copy: $LL_url -> $LL_dest"
    else
      say "  would copy: $LL_url -> $LL_dest"
    fi
    return 0
  fi
  if ! LL_tmp=$(mktemp "${TMPDIR:-/tmp}/lapis-lazuli.XXXXXX"); then
    failed "$LL_H: could not create a temporary file"
    return 0
  fi
  say "  download: $LL_url"
  if ! fetch "$LL_url" "$LL_tmp"; then
    rm -f "$LL_tmp"
    failed "$LL_H: could not download $LL_url"
    return 0
  fi
  if [ -f "$LL_dest" ] && cmp -s "$LL_tmp" "$LL_dest"; then
    rm -f "$LL_tmp"
    say "  unchanged: $LL_dest"
    return 0
  fi
  if [ "$LL_ask" = 1 ] && ! ask "Copy ${3##*/} to $LL_dest ?"; then
    rm -f "$LL_tmp"
    say "  skipped: copy to $LL_dest"
    todo "$LL_H (you declined): copy $LL_url to $LL_dest"
    return 0
  fi
  if mkdir -p "${LL_dest%/*}" && cat "$LL_tmp" >"$LL_dest"; then
    say "  copied: $LL_dest"
    changed "$LL_H: copied $LL_url to $LL_dest"
  else
    failed "$LL_H: could not write $LL_dest"
  fi
  rm -f "$LL_tmp"
}

# step_remove ASK NOTE PATH: remove one file, or one empty folder when PATH ends in /.
step_remove() {
  LL_ask=$1
  LL_note=$2
  LL_dest=$3
  LL_action="remove $LL_dest"
  case $LL_dest in */) LL_action="remove folder if empty: $LL_dest" ;; esac
  note "$LL_note"
  if [ "$LL_MANUAL" = 1 ]; then
    todo "$LL_H: $LL_action"
    return 0
  fi
  case $LL_dest in
    */)
      LL_folder=${LL_dest%/}
      LL_reason=
      if [ -L "$LL_folder" ]; then
        LL_reason='symbolic link'
      elif [ -e "$LL_folder" ] && [ ! -d "$LL_folder" ]; then
        LL_reason='not a folder'
      elif [ -d "$LL_folder" ] && { [ ! -r "$LL_folder" ] || [ ! -x "$LL_folder" ]; }; then
        LL_reason=unreadable
      fi
      if [ -n "$LL_reason" ]; then
        say "  kept ($LL_reason): $LL_dest"
        todo "$LL_H: $LL_action"
        return 0
      fi
      ;;
  esac
  if [ ! -e "$LL_dest" ]; then
    say "  already absent: $LL_dest"
    return 0
  fi
  if [ "$LL_DRY" = 1 ]; then
    if [ "$LL_ask" = 1 ] && [ "$LL_YES" = 0 ]; then
      say "  would ask, then $LL_action"
    else
      say "  would $LL_action"
    fi
    return 0
  fi
  if [ "$LL_ask" = 1 ] && ! ask "Remove $LL_dest ?"; then
    say "  skipped: $LL_action"
    todo "$LL_H (you declined): $LL_action"
    return 0
  fi
  case $LL_dest in
    */)
      for LL_entry in "$LL_dest"* "$LL_dest".*; do
        case ${LL_entry##*/} in .|..) continue ;; esac
        if [ -e "$LL_entry" ] || [ -L "$LL_entry" ]; then
          say "  kept (not empty): $LL_dest"
          todo "$LL_H: $LL_action"
          return 0
        fi
      done
      if rmdir "$LL_dest" 2>/dev/null; then
        say "  removed empty folder: $LL_dest"
        changed "$LL_H: removed empty folder $LL_dest"
      else
        say "  kept (could not remove empty folder): $LL_dest"
        todo "$LL_H: $LL_action"
      fi
      ;;
    *)
      if rm -f "$LL_dest"; then
        say "  removed: $LL_dest"
        changed "$LL_H: removed $LL_dest"
      else
        failed "$LL_H: could not remove $LL_dest"
      fi
      ;;
  esac
}

step_manual() { todo "$LL_H: $1"; }

# need_sha: set LL_sha to the full commit the release ref points to.
need_sha() {
  if [ "$LL_DRY" = 1 ]; then
    [ -n "$LL_sha" ] || say "  would run: git ls-remote https://github.com/$LL_REPO refs/heads/$LL_REF"
    LL_sha='<commit>'
    return 0
  fi
  [ "$LL_SHA_STATE" != ok ] || return 0
  if [ -z "$LL_SHA_STATE" ]; then
    LL_SHA_STATE=failed
    if has_cmd git; then
      say "  run: git ls-remote https://github.com/$LL_REPO refs/heads/$LL_REF"
      LL_out=$(GIT_TERMINAL_PROMPT=0 command git ls-remote "https://github.com/$LL_REPO" "refs/heads/$LL_REF") || LL_out=
      LL_first=${LL_out%%[!0-9a-f]*}
      if [ ${#LL_first} -eq 40 ]; then
        LL_sha=$LL_first
        LL_SHA_STATE=ok
        say "  commit: $LL_sha"
        return 0
      fi
    fi
    say "  could not read the commit $LL_REF points to (git ls-remote https://github.com/$LL_REPO refs/heads/$LL_REF)"
  fi
  if [ "$LL_MANUAL" = 1 ]; then
    LL_sha='<commit>'
    return 0
  fi
  failed "$LL_H: skipped a step that needs the commit of $LL_REF"
  return 1
}

# cleanup: delete the temporary clone need_checkout made. It only runs from the EXIT trap, which shellcheck does not follow.
# shellcheck disable=SC2317
cleanup() {
  [ -z "$LL_CHECKOUT_DIR" ] || rm -rf "$LL_CHECKOUT_DIR"
}

# need_checkout: set LL_checkout to a shallow clone of the release ref in a temporary folder (deleted when the
# script ends), for a harness that installs from a local folder.
need_checkout() {
  if [ "$LL_DRY" = 1 ]; then
    [ -n "$LL_checkout" ] || say "  would run: git clone --depth 1 --branch $LL_REF https://github.com/$LL_REPO <checkout>"
    LL_checkout='<checkout>'
    return 0
  fi
  if [ "$LL_MANUAL" = 1 ]; then
    LL_checkout='<checkout>'
    return 0
  fi
  [ "$LL_CHECKOUT_STATE" != ok ] || return 0
  if [ -z "$LL_CHECKOUT_STATE" ]; then
    LL_CHECKOUT_STATE=failed
    if has_cmd git && LL_dir=$(mktemp -d "${TMPDIR:-/tmp}/lapis-lazuli-checkout.XXXXXX"); then
      LL_CHECKOUT_DIR=$LL_dir
      say "  run: git clone --depth 1 --branch $LL_REF https://github.com/$LL_REPO $LL_dir"
      if GIT_TERMINAL_PROMPT=0 command git clone --depth 1 --branch "$LL_REF" "https://github.com/$LL_REPO" "$LL_dir"; then
        LL_checkout=$LL_dir
        LL_CHECKOUT_STATE=ok
        return 0
      fi
    fi
    say "  could not clone $LL_REF (git clone --depth 1 --branch $LL_REF https://github.com/$LL_REPO)"
  fi
  failed "$LL_H: skipped a step that needs a clone of $LL_REF"
  return 1
}

# verify_cmd EXPECT ARGV...: one CLI check.
verify_cmd() {
  LL_exp=$1
  shift
  LL_line=$(qargv "$@")
  if [ "$LL_DRY" = 1 ]; then
    say "  would check: $LL_line"
    say "    expect: $LL_exp"
    return 0
  fi
  if ! has_cmd "$1"; then
    failed "CLI: $1 is not on PATH; open a new terminal$(path_hint)"
    return 0
  fi
  say "  check: $LL_line"
  say "    expect: $LL_exp"
  command "$@"
  LL_st=$?
  [ "$LL_st" -eq 0 ] || failed "CLI: $LL_line (exit $LL_st)"
}

show_snippets() {
  [ -n "$LL_SNIPPETS" ] || return 0
  printf '%s\n' "$LL_SNIPPETS" | while IFS= read -r LL_s; do
    LL_url="$LL_RAW/$LL_s"
    say ""
    say "== Instructions snippet: $LL_s"
    say "  Add it to your agent's instructions file yourself; this script never edits one."
    if [ "$LL_DRY" = 1 ]; then
      say "  would show: $LL_url"
      continue
    fi
    LL_tmp=$(mktemp "${TMPDIR:-/tmp}/lapis-lazuli.XXXXXX") || continue
    if fetch "$LL_url" "$LL_tmp"; then
      say "----- $LL_s -----"
      cat "$LL_tmp"
      say "----- end of $LL_s -----"
    else
      say "  could not download it; open $LL_url"
    fi
    rm -f "$LL_tmp"
  done
}

@CLI@

@HARNESS_FUNCTIONS@

harness() {
  case $1 in
@DISPATCH@
  esac
}

add_want() {
  case $1 in
    --harness)
      in_list "$2" "$LL_ALL_HARNESSES" || usage_error "unknown harness '$2' (known: $LL_ALL_HARNESSES)"
      in_list "$2" "$LL_WANT_H" || LL_WANT_H="${LL_WANT_H:+$LL_WANT_H }$2"
      ;;
    --plugin)
      in_list "$2" "$LL_ALL_PLUGINS" || usage_error "unknown plugin '$2' (known: $LL_ALL_PLUGINS)"
      in_list "$2" "$LL_WANT_P" || LL_WANT_P="${LL_WANT_P:+$LL_WANT_P }$2"
      ;;
  esac
}

set_mode() {
  if [ "$LL_MODE" != install ] && [ "$LL_MODE" != "$1" ]; then
    usage_error "--update and --uninstall cannot be combined"
  fi
  LL_MODE=$1
}

parse_args() {
  while [ $# -gt 0 ]; do
    case $1 in
      --dry-run) LL_DRY=1 ;;
      --yes | -y) LL_YES=1 ;;
      --update) set_mode update ;;
      --uninstall) set_mode uninstall ;;
      --harness | --plugin)
        [ $# -ge 2 ] || usage_error "$1 needs a value"
        add_want "$1" "$2"
        shift
        ;;
      --harness=*) add_want --harness "${1#*=}" ;;
      --plugin=*) add_want --plugin "${1#*=}" ;;
      --help | -h)
        usage
        exit 0
        ;;
      *) usage_error "unknown option: $1" ;;
    esac
    shift
  done
}

main() {
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM HUP
  parse_args "$@"
  if [ -z "${HOME:-}" ]; then
    err "install.sh: HOME is not set"
    exit 1
  fi
  LL_os=$(uname -s 2>/dev/null) || LL_os=unknown
  case $LL_os in
    Darwin) LL_os=macOS ;;
    Linux) ;;
    *)
      err "install.sh: this script is for macOS and Linux (found $LL_os); on Windows use install.ps1: $LL_DOCS"
      exit 1
      ;;
  esac
  for LL_p in $LL_ALL_PLUGINS; do
    if [ -z "$LL_WANT_P" ] || in_list "$LL_p" "$LL_WANT_P"; then
      LL_PLUGINS="${LL_PLUGINS:+$LL_PLUGINS }$LL_p"
      LL_SKILLS="${LL_SKILLS:+$LL_SKILLS }$(skills_of "$LL_p")"
    fi
  done
  if [ "$LL_DRY" = 1 ]; then LL_how="$LL_MODE, dry run: nothing is changed"; else LL_how=$LL_MODE; fi
  say "LapisLazuli installer $LL_VERSION ($LL_how)"
  say "  system: $LL_os"
  if [ "$(id -u 2>/dev/null)" = 0 ]; then
    say "  warning: running as root, so harness settings go to $HOME; run it as yourself instead"
  fi
  say "  source: https://github.com/$LL_REPO at $LL_REF"
  say "  plugins: $LL_PLUGINS"
  LL_found=
  for LL_h in $LL_ALL_HARNESSES; do
    harness "$LL_h" name
    if harness "$LL_h" detect; then
      LL_found="${LL_found:+$LL_found }$LL_h"
      if skips_experimental "$LL_h"; then
        say "  found: $LL_H ($LL_WHY); experimental, so not installed unless named: --harness $LL_h"
      else
        say "  found: $LL_H ($LL_WHY)"
      fi
    fi
  done
  if [ -n "$LL_WANT_H" ]; then
    LL_absent=0
    for LL_h in $LL_ALL_HARNESSES; do
      in_list "$LL_h" "$LL_WANT_H" || continue
      if in_list "$LL_h" "$LL_found"; then
        LL_TARGETS="${LL_TARGETS:+$LL_TARGETS }$LL_h"
        continue
      fi
      harness "$LL_h" name
      harness "$LL_h" lookfor
      err "install.sh: $LL_H is not installed here: found no $LL_LOOK."
      err "  Install $LL_H first, or leave out --harness $LL_h. Guide: $LL_DOCS$LL_ANCHOR"
      LL_absent=1
    done
    [ "$LL_absent" = 0 ] || exit 1
  else
    for LL_h in $LL_found; do
      skips_experimental "$LL_h" || LL_TARGETS="${LL_TARGETS:+$LL_TARGETS }$LL_h"
    done
  fi
  if [ -z "$LL_TARGETS" ]; then
    if [ -n "$LL_found" ]; then
      say "  no harness to install: the ones found are experimental; see $LL_DOCS#identify-your-harness"
    else
      say "  no supported harness found; see $LL_DOCS#identify-your-harness"
    fi
  fi

  if [ "$LL_MODE" != uninstall ]; then
    LL_TOOL=$(cli_tool install) || LL_TOOL=
    if [ -z "$LL_TOOL" ] && [ "$LL_DRY" = 0 ]; then
      err "install.sh: the CLI needs $LL_CLI_NEEDS on PATH; install one and run this again. Guide: $LL_DOCS#cli-and-optional-components"
      exit 1
    fi
    begin "$LL_CLI_NAME"
    if [ -n "$LL_TOOL" ]; then
      say "  with: $LL_TOOL"
      cli_steps install "$LL_TOOL"
    else
      failed "CLI: no $LL_CLI_NEEDS on PATH"
    fi
  fi

  for LL_h in $LL_TARGETS; do
    harness "$LL_h" "$LL_MODE"
  done

  if [ "$LL_MODE" = uninstall ]; then
    begin "$LL_CLI_NAME"
    if [ -n "$LL_WANT_H" ] || ! all_plugins; then
      say "  kept: the CLI goes only with every plugin from every harness"
    elif LL_TOOL=$(cli_tool uninstall); then
      cli_steps uninstall "$LL_TOOL"
    else
      say "  no $LL_CLI_NEEDS on PATH; remove the CLI with the tool that installed it"
    fi
  else
    begin "Check the CLI"
    cli_verify
    for LL_h in $LL_TARGETS; do
      harness "$LL_h" name
      harness "$LL_h" verify
    done
  fi

  print_block "== Checks to run" "$LL_CHECKS" "  "
  print_block "== To do by hand" "$LL_TODO" "  "
  [ "$LL_MODE" = uninstall ] || show_snippets
  print_block "== Notes" "$LL_NOTES" "  "
  say ""
  say "== Summary"
  if [ "$LL_DRY" = 1 ]; then
    say "  dry run: nothing was changed"
  elif [ -n "$LL_CHANGES" ]; then
    say "  changed:"
    printf '%s' "$LL_CHANGES" | while IFS= read -r LL_l; do say "    $LL_l"; done
  else
    say "  nothing was changed"
  fi
  if [ -n "$LL_FAILED" ]; then
    say "  failed:"
    printf '%s' "$LL_FAILED" | while IFS= read -r LL_l; do say "    $LL_l"; done
    exit 1
  fi
  exit 0
}

main "$@"
'''


PS_TEMPLATE = r'''# LapisLazuli installer for Windows (Windows PowerShell 5.1 or later, or PowerShell 7).
# Generated by tools/build/installers.py from install/harnesses.yaml; do not edit.
# Every harness command is an argv list from that file, run as separate arguments; nothing goes
# through Invoke-Expression.
Set-StrictMode -Version 2.0

$script:Version = @VERSION@
$script:Repo = @REPO@
$script:Ref = @REF@
$script:Raw = @RAW@
$script:Docs = @DOCS@
$script:AllPlugins = @PLUGINS@
$script:AllHarnesses = @HARNESSES@
$script:Experimental = @EXPERIMENTAL@
$script:CliName = @CLI_NAME@
$script:CliNeeds = @CLI_NEEDS@
$script:SkillsOf = @{
@SKILLS@
}
$script:Usage = @'
@USAGE@
'@
$script:Mode = 'install'
$script:Dry = $false
$script:Yes = $false
$script:WantH = @()
$script:WantP = @()
$script:Plugins = @()
$script:Skills = @()
$script:Agents = @AGENTS@
$script:H = ''
$script:Manual = $false
$script:Sha = ''
$script:ShaState = ''
$script:Checkout = ''
$script:CheckoutState = ''
$script:CheckoutDir = ''
$script:Tool = ''
$script:Why = @()
$script:Look = ''
$script:Anchor = ''
$script:Todo = New-Object 'System.Collections.Generic.List[string]'
$script:Checks = New-Object 'System.Collections.Generic.List[string]'
$script:Notes = New-Object 'System.Collections.Generic.List[string]'
$script:Changes = New-Object 'System.Collections.Generic.List[string]'
$script:Failed = New-Object 'System.Collections.Generic.List[string]'
$script:Snippets = New-Object 'System.Collections.Generic.List[string]'

function Say([string]$Text) { Write-Host $Text }
function Err([string]$Text) { [Console]::Error.WriteLine($Text) }

function Show-UsageError([string]$Text) {
  Err ('install.ps1: ' + $Text)
  Err $script:Usage
  return 2
}

function Test-Cmd([string]$Name) {
  return [bool](Get-Command -Name $Name -CommandType Application, ExternalScript -ErrorAction SilentlyContinue)
}
function Test-Dir([string]$Path) { return (Test-Path -LiteralPath $Path -PathType Container) }
function Get-HomePath([string]$Rel) {
  $sep = [string][IO.Path]::DirectorySeparatorChar
  return ($HOME.TrimEnd('/', '\') + $sep + $Rel.Replace('/', $sep))
}
function Test-Slug([string]$Word) { return ($Word -cmatch '^[a-z0-9-]+$') }
function Test-SkipExperimental([string]$Id) {
  return ($script:Mode -ceq 'install' -and $script:WantH.Count -eq 0 -and ($script:Experimental -ccontains $Id))
}
function Select-Among([string[]]$Names) { return @(@($script:Plugins) | Where-Object { $Names -ccontains $_ }) }
function Test-Selected([string]$Name) { return (@($script:Plugins) -ccontains $Name) }
function Test-AllPlugins { return ((@($script:Plugins) -join ' ') -ceq (@($script:AllPlugins) -join ' ')) }

# Format-Arg: one argument, quoted for PowerShell when it needs quotes.
function Format-Arg([string]$Arg) {
  if ($Arg -cmatch '^[A-Za-z0-9_./:+-][A-Za-z0-9_./:@+-]*$') { return $Arg }
  return ("'" + $Arg.Replace("'", "''") + "'")
}
function Format-Argv([string[]]$Argv) { return ((@($Argv) | ForEach-Object { Format-Arg $_ }) -join ' ') }

function Add-Todo([string]$Text) { $script:Todo.Add('- ' + $Text) }
function Add-Change([string]$Text) { $script:Changes.Add('- ' + $Text) }
function Add-Failure([string]$Text) {
  $script:Failed.Add('- ' + $Text)
  Say ('  failed: ' + $Text)
}
function Add-Note([string]$Text) {
  if (-not $Text) { return }
  $line = '- ' + $script:H + ': ' + $Text
  if (-not $script:Notes.Contains($line)) { $script:Notes.Add($line) }
}
function Write-WholeNote {
  if (-not (Test-AllPlugins)) { Say ('  note: ' + $script:H + ' takes every plugin at once; --plugin does not narrow it') }
}
function Add-CheckCmd([string[]]$Argv) { $script:Checks.Add('- ' + $script:H + ': ' + (Format-Argv $Argv)) }
function Add-CheckExpect([string]$Text) { $script:Checks.Add('    expect: ' + $Text) }
function Add-CheckManual([string]$Text) { $script:Checks.Add('- ' + $script:H + ': ' + $Text) }
function Add-Snippet([string]$Path) { if (-not $script:Snippets.Contains($Path)) { $script:Snippets.Add($Path) } }

function Write-Block([string]$Title, $Lines, [string]$Indent) {
  if ($Lines.Count -eq 0) { return }
  Say ''
  Say $Title
  foreach ($line in $Lines) { Say ($Indent + $line) }
}

# Ask: yes only for y or yes (--yes answers for the user).
function Ask([string]$Question) {
  if ($script:Yes) {
    Say ('  ' + $Question + ' [y/N] y (--yes)')
    return $true
  }
  $answer = Read-Host ('  ' + $Question + ' [y/N]')
  return ([string]$answer -match '^\s*(y|yes)\s*$')
}

function Get-Url([string]$Url, [string]$Dest) {
  $ProgressPreference = 'SilentlyContinue'
  try {
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Dest -ErrorAction Stop
    return $true
  } catch {
    Say ('  ' + $_.Exception.Message)
    return $false
  }
}

function Invoke-Argv([string[]]$Argv) {
  $rest = @()
  if ($Argv.Count -gt 1) { $rest = $Argv[1..($Argv.Count - 1)] }
  try {
    $cmd = Get-Command -Name $Argv[0] -CommandType Application, ExternalScript -ErrorAction Stop | Select-Object -First 1
    $global:LASTEXITCODE = 0
    & $cmd @rest | Out-Host
  } catch {
    Say ('  ' + $_.Exception.Message)
    return 127
  }
  return [int]$global:LASTEXITCODE
}

# Start-Phase: start a section; when a command is missing, its steps become a to-do list.
function Start-Phase([string]$Name, [string[]]$Commands) {
  $script:H = $Name
  $script:Manual = $false
  $missing = @(@($Commands) | Where-Object { -not (Test-Cmd $_) })
  Say ''
  Say ('== ' + $Name)
  if ($missing.Count -gt 0) {
    $script:Manual = $true
    Say ('  not on PATH: ' + ($missing -join ', ') + "; the steps are listed under 'To do by hand'")
  }
}

function Skip-All([string]$Text) { Say ('  not now (only when every plugin is removed): ' + $Text) }

function Invoke-Run([bool]$AskFirst, [string]$Note, [string[]]$Argv) {
  $line = Format-Argv $Argv
  Add-Note $Note
  if ($script:Manual) {
    Add-Todo ($script:H + ': ' + $line)
    return
  }
  if ($script:Dry) {
    if ($AskFirst -and -not $script:Yes) { Say ('  would ask, then run: ' + $line) } else { Say ('  would run: ' + $line) }
    return
  }
  if ($AskFirst) {
    if ($Note) { Say ('  note: ' + $Note) }
    if (-not (Ask ('Run ' + $line + ' ?'))) {
      Say ('  skipped: ' + $line)
      Add-Todo ($script:H + ' (you declined): ' + $line)
      return
    }
  }
  Say ('  run: ' + $line)
  $code = Invoke-Argv $Argv
  if ($code -eq 0) { Add-Change ($script:H + ': ran ' + $line) } else { Add-Failure ($script:H + ': ' + $line + ' (exit ' + $code + ')') }
}

function Invoke-Copy([bool]$AskFirst, [string]$Note, [string]$Source, [string]$Dest) {
  $url = $script:Raw + '/' + $Source
  Add-Note $Note
  if ($script:Manual) {
    Add-Todo ($script:H + ': copy ' + $url + ' to ' + $Dest)
    return
  }
  if ($script:Dry) {
    if ($AskFirst -and -not $script:Yes) { Say ('  would ask, then copy: ' + $url + ' -> ' + $Dest) } else { Say ('  would copy: ' + $url + ' -> ' + $Dest) }
    return
  }
  $tmp = [IO.Path]::GetTempFileName()
  try {
    Say ('  download: ' + $url)
    if (-not (Get-Url $url $tmp)) {
      Add-Failure ($script:H + ': could not download ' + $url)
      return
    }
    if ((Test-Path -LiteralPath $Dest -PathType Leaf) -and ((Get-FileHash -LiteralPath $tmp).Hash -eq (Get-FileHash -LiteralPath $Dest).Hash)) {
      Say ('  unchanged: ' + $Dest)
      return
    }
    $name = $Source.Substring($Source.LastIndexOf('/') + 1)
    if ($AskFirst -and -not (Ask ('Copy ' + $name + ' to ' + $Dest + ' ?'))) {
      Say ('  skipped: copy to ' + $Dest)
      Add-Todo ($script:H + ' (you declined): copy ' + $url + ' to ' + $Dest)
      return
    }
    try {
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dest) -ErrorAction Stop | Out-Null
      Copy-Item -LiteralPath $tmp -Destination $Dest -Force -ErrorAction Stop
      Say ('  copied: ' + $Dest)
      Add-Change ($script:H + ': copied ' + $url + ' to ' + $Dest)
    } catch {
      Add-Failure ($script:H + ': could not write ' + $Dest + ': ' + $_.Exception.Message)
    }
  } finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
  }
}

function Invoke-Remove([bool]$AskFirst, [string]$Note, [string]$Path) {
  $directory = $Path.EndsWith([string][IO.Path]::DirectorySeparatorChar)
  $action = if ($directory) { 'remove folder if empty: ' } else { 'remove ' }
  Add-Note $Note
  if ($script:Manual) {
    Add-Todo ($script:H + ': ' + $action + $Path)
    return
  }
  if ($directory) {
    $folder = $Path.Substring(0, $Path.Length - 1)
    $item = Get-Item -LiteralPath $folder -Force -ErrorAction SilentlyContinue
    if ($null -eq $item) {
      if (Test-Path -LiteralPath $folder) {
        Say ('  kept (unreadable): ' + $Path)
        Add-Todo ($script:H + ': ' + $action + $Path)
      } else {
        Say ('  already absent: ' + $Path)
      }
      return
    }
    $reason = if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { 'symbolic link' }
              elseif (-not $item.PSIsContainer) { 'not a folder' }
              else { '' }
    if ($reason) {
      Say ('  kept (' + $reason + '): ' + $Path)
      Add-Todo ($script:H + ': ' + $action + $Path)
      return
    }
  } elseif (-not (Test-Path -LiteralPath $Path)) {
    Say ('  already absent: ' + $Path)
    return
  }
  if ($script:Dry) {
    if ($AskFirst -and -not $script:Yes) { Say ('  would ask, then ' + $action + $Path) } else { Say ('  would ' + $action + $Path) }
    return
  }
  if ($AskFirst -and -not (Ask ('Remove ' + $Path + ' ?'))) {
    Say ('  skipped: ' + $action + $Path)
    Add-Todo ($script:H + ' (you declined): ' + $action + $Path)
    return
  }
  if ($directory) {
    try {
      if (@(Get-ChildItem -LiteralPath $folder -Force -ErrorAction Stop | Select-Object -First 1).Count -gt 0) {
        Say ('  kept (not empty): ' + $Path)
        Add-Todo ($script:H + ': ' + $action + $Path)
        return
      }
    } catch {
      Say ('  kept (unreadable): ' + $Path)
      Add-Todo ($script:H + ': ' + $action + $Path)
      return
    }
    try {
      [System.IO.Directory]::Delete($folder, $false)
      Say ('  removed empty folder: ' + $Path)
      Add-Change ($script:H + ': removed empty folder ' + $Path)
    } catch {
      Say ('  kept (could not remove empty folder): ' + $Path)
      Add-Todo ($script:H + ': ' + $action + $Path)
    }
    return
  }
  try {
    Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
    Say ('  removed: ' + $Path)
    Add-Change ($script:H + ': removed ' + $Path)
  } catch {
    Add-Failure ($script:H + ': could not remove ' + $Path + ': ' + $_.Exception.Message)
  }
}

function Invoke-Manual([string]$Text) { Add-Todo ($script:H + ': ' + $Text) }

# Get-Sha: set $script:Sha to the full commit the release ref points to.
function Get-Sha {
  $url = 'https://github.com/' + $script:Repo
  $refName = 'refs/heads/' + $script:Ref
  if ($script:Dry) {
    if (-not $script:Sha) { Say ('  would run: git ls-remote ' + $url + ' ' + $refName) }
    $script:Sha = '<commit>'
    return $true
  }
  if ($script:ShaState -eq 'ok') { return $true }
  if (-not $script:ShaState) {
    $script:ShaState = 'failed'
    if (Test-Cmd 'git') {
      Say ('  run: git ls-remote ' + $url + ' ' + $refName)
      $saved = $env:GIT_TERMINAL_PROMPT
      $env:GIT_TERMINAL_PROMPT = '0'
      try { $out = @(& git ls-remote $url $refName) } catch { $out = @() }
      $env:GIT_TERMINAL_PROMPT = $saved
      $first = ''
      if ($out.Count -gt 0) { $first = ([string]$out[0] -split '\s+')[0] }
      if ($first -cmatch '^[0-9a-f]{40}$') {
        $script:Sha = $first
        $script:ShaState = 'ok'
        Say ('  commit: ' + $first)
        return $true
      }
    }
    Say ('  could not read the commit ' + $script:Ref + ' points to (git ls-remote ' + $url + ' ' + $refName + ')')
  }
  if ($script:Manual) {
    $script:Sha = '<commit>'
    return $true
  }
  Add-Failure ($script:H + ': skipped a step that needs the commit of ' + $script:Ref)
  return $false
}

# Remove-Checkout: delete the temporary clone Get-Checkout made.
function Remove-Checkout {
  if ($script:CheckoutDir) {
    Remove-Item -LiteralPath $script:CheckoutDir -Recurse -Force -ErrorAction SilentlyContinue
    $script:CheckoutDir = ''
  }
}

# Get-Checkout: set $script:Checkout to a shallow clone of the release ref in a temporary folder (deleted when the
# script ends), for a harness that installs from a local folder.
function Get-Checkout {
  $url = 'https://github.com/' + $script:Repo
  if ($script:Dry) {
    if (-not $script:Checkout) { Say ('  would run: git clone --depth 1 --branch ' + $script:Ref + ' ' + $url + ' <checkout>') }
    $script:Checkout = '<checkout>'
    return $true
  }
  if ($script:Manual) {
    $script:Checkout = '<checkout>'
    return $true
  }
  if ($script:CheckoutState -eq 'ok') { return $true }
  if (-not $script:CheckoutState) {
    $script:CheckoutState = 'failed'
    if (Test-Cmd 'git') {
      $dir = Join-Path ([IO.Path]::GetTempPath()) ('lapis-lazuli-checkout-' + [guid]::NewGuid().ToString('N'))
      $script:CheckoutDir = $dir
      Say ('  run: git clone --depth 1 --branch ' + $script:Ref + ' ' + $url + ' ' + $dir)
      $saved = $env:GIT_TERMINAL_PROMPT
      $env:GIT_TERMINAL_PROMPT = '0'
      $code = Invoke-Argv @('git', 'clone', '--depth', '1', '--branch', $script:Ref, $url, $dir)
      $env:GIT_TERMINAL_PROMPT = $saved
      if ($code -eq 0) {
        $script:Checkout = $dir
        $script:CheckoutState = 'ok'
        return $true
      }
    }
    Say ('  could not clone ' + $script:Ref + ' (git clone --depth 1 --branch ' + $script:Ref + ' ' + $url + ')')
  }
  Add-Failure ($script:H + ': skipped a step that needs a clone of ' + $script:Ref)
  return $false
}

function Invoke-Verify([string]$Expect, [string[]]$Argv) {
  $line = Format-Argv $Argv
  if ($script:Dry) {
    Say ('  would check: ' + $line)
    Say ('    expect: ' + $Expect)
    return
  }
  if (-not (Test-Cmd $Argv[0])) {
    Add-Failure ('CLI: ' + $Argv[0] + ' is not on PATH; open a new terminal' + (Get-PathHint))
    return
  }
  Say ('  check: ' + $line)
  Say ('    expect: ' + $Expect)
  $code = Invoke-Argv $Argv
  if ($code -ne 0) { Add-Failure ('CLI: ' + $line + ' (exit ' + $code + ')') }
}

function Show-Snippets {
  foreach ($path in $script:Snippets) {
    $url = $script:Raw + '/' + $path
    Say ''
    Say ('== Instructions snippet: ' + $path)
    Say "  Add it to your agent's instructions file yourself; this script never edits one."
    if ($script:Dry) {
      Say ('  would show: ' + $url)
      continue
    }
    $tmp = [IO.Path]::GetTempFileName()
    if (Get-Url $url $tmp) {
      Say ('----- ' + $path + ' -----')
      foreach ($line in (Get-Content -LiteralPath $tmp)) { Say $line }
      Say ('----- end of ' + $path + ' -----')
    } else {
      Say ('  could not download it; open ' + $url)
    }
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
  }
}

@CLI@

@HARNESS_FUNCTIONS@

function Invoke-Harness([string]$Id, [string]$Phase) {
  switch -CaseSensitive ($Id) {
@DISPATCH@
  }
}

function Invoke-Main([object[]]$Arguments) {
  $i = 0
  $n = @($Arguments).Count
  while ($i -lt $n) {
    $a = [string]$Arguments[$i]
    $value = $null
    if ($a -clike '--harness=*' -or $a -clike '--plugin=*') {
      $value = $a.Substring($a.IndexOf('=') + 1)
      $a = $a.Substring(0, $a.IndexOf('='))
    } elseif ($a -ceq '--harness' -or $a -ceq '--plugin') {
      if ($i + 1 -ge $n) { return (Show-UsageError ($a + ' needs a value')) }
      $i++
      $value = [string]$Arguments[$i]
    }
    if ($a -ceq '--dry-run') { $script:Dry = $true }
    elseif ($a -ceq '--yes' -or $a -ceq '-y') { $script:Yes = $true }
    elseif ($a -ceq '--update' -or $a -ceq '--uninstall') {
      $mode = $a.Substring(2)
      if ($script:Mode -ne 'install' -and $script:Mode -ne $mode) { return (Show-UsageError '--update and --uninstall cannot be combined') }
      $script:Mode = $mode
    }
    elseif ($a -ceq '--harness') {
      if (-not (Test-Slug $value) -or -not ($script:AllHarnesses -ccontains $value)) {
        return (Show-UsageError ("unknown harness '" + $value + "' (known: " + ($script:AllHarnesses -join ' ') + ')'))
      }
      if (-not ($script:WantH -ccontains $value)) { $script:WantH += $value }
    }
    elseif ($a -ceq '--plugin') {
      if (-not (Test-Slug $value) -or -not ($script:AllPlugins -ccontains $value)) {
        return (Show-UsageError ("unknown plugin '" + $value + "' (known: " + ($script:AllPlugins -join ' ') + ')'))
      }
      if (-not ($script:WantP -ccontains $value)) { $script:WantP += $value }
    }
    elseif ($a -ceq '--help' -or $a -ceq '-h') {
      Say $script:Usage
      return 0
    }
    else { return (Show-UsageError ('unknown option: ' + $a)) }
    $i++
  }

  if ($PSVersionTable.PSVersion.Major -lt 5) {
    Err 'install.ps1: needs Windows PowerShell 5.1 or later'
    return 1
  }
  try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  } catch { }
  foreach ($p in $script:AllPlugins) {
    if ($script:WantP.Count -eq 0 -or $script:WantP -ccontains $p) {
      $script:Plugins += $p
      $script:Skills += $script:SkillsOf[$p]
    }
  }
  $how = $script:Mode
  if ($script:Dry) { $how = $script:Mode + ', dry run: nothing is changed' }
  Say ('LapisLazuli installer ' + $script:Version + ' (' + $how + ')')
  $os = 'Windows'
  if ($env:OS -ne 'Windows_NT') {
    try { $os = [Runtime.InteropServices.RuntimeInformation]::OSDescription } catch { $os = [string][Environment]::OSVersion }
  }
  Say ('  system: ' + $os + ', PowerShell ' + $PSVersionTable.PSVersion)
  if ($env:OS -eq 'Windows_NT') {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
      Say '  warning: running as administrator; this script needs no administrator rights'
    }
  } else {
    Say '  note: on macOS and Linux, install.sh is the supported script'
  }
  Say ('  source: https://github.com/' + $script:Repo + ' at ' + $script:Ref)
  Say ('  plugins: ' + ($script:Plugins -join ' '))
  $found = @()
  foreach ($h in $script:AllHarnesses) {
    Invoke-Harness $h 'name'
    Invoke-Harness $h 'detect'
    if (@($script:Why).Count -gt 0) {
      $found += $h
      if (Test-SkipExperimental $h) {
        Say ('  found: ' + $script:H + ' (' + ($script:Why -join ', ') + '); experimental, so not installed unless named: --harness ' + $h)
      } else {
        Say ('  found: ' + $script:H + ' (' + ($script:Why -join ', ') + ')')
      }
    }
  }
  $targets = @()
  if ($script:WantH.Count -gt 0) {
    $absent = $false
    foreach ($h in $script:AllHarnesses) {
      if (-not ($script:WantH -ccontains $h)) { continue }
      if ($found -ccontains $h) {
        $targets += $h
        continue
      }
      Invoke-Harness $h 'name'
      Invoke-Harness $h 'lookfor'
      Err ('install.ps1: ' + $script:H + ' is not installed here: found no ' + $script:Look + '.')
      Err ('  Install ' + $script:H + ' first, or leave out --harness ' + $h + '. Guide: ' + $script:Docs + $script:Anchor)
      $absent = $true
    }
    if ($absent) { return 1 }
  } else {
    $targets = @($found | Where-Object { -not (Test-SkipExperimental $_) })
  }
  if ($targets.Count -eq 0) {
    if ($found.Count -gt 0) { Say ('  no harness to install: the ones found are experimental; see ' + $script:Docs + '#identify-your-harness') }
    else { Say ('  no supported harness found; see ' + $script:Docs + '#identify-your-harness') }
  }

  if ($script:Mode -ne 'uninstall') {
    $script:Tool = Get-CliTool 'install'
    if (-not $script:Tool -and -not $script:Dry) {
      Err ('install.ps1: the CLI needs ' + $script:CliNeeds + ' on PATH; install one and run this again. Guide: ' + $script:Docs + '#cli-and-optional-components')
      return 1
    }
    Start-Phase $script:CliName @()
    if ($script:Tool) {
      Say ('  with: ' + $script:Tool)
      Invoke-CliSteps 'install' $script:Tool
    } else {
      Add-Failure ('CLI: no ' + $script:CliNeeds + ' on PATH')
    }
  }

  foreach ($h in $targets) { Invoke-Harness $h $script:Mode }

  if ($script:Mode -eq 'uninstall') {
    Start-Phase $script:CliName @()
    $tool = Get-CliTool 'uninstall'
    if ($script:WantH.Count -gt 0 -or -not (Test-AllPlugins)) {
      Say '  kept: the CLI goes only with every plugin from every harness'
    } elseif ($tool) {
      $script:Tool = $tool
      Invoke-CliSteps 'uninstall' $tool
    } else {
      Say ('  no ' + $script:CliNeeds + ' on PATH; remove the CLI with the tool that installed it')
    }
  } else {
    Start-Phase 'Check the CLI' @()
    Invoke-CliVerify
    foreach ($h in $targets) {
      Invoke-Harness $h 'name'
      Invoke-Harness $h 'verify'
    }
  }

  Write-Block '== Checks to run' $script:Checks '  '
  Write-Block '== To do by hand' $script:Todo '  '
  if ($script:Mode -ne 'uninstall') { Show-Snippets }
  Write-Block '== Notes' $script:Notes '  '
  Say ''
  Say '== Summary'
  if ($script:Dry) { Say '  dry run: nothing was changed' }
  elseif ($script:Changes.Count -gt 0) {
    Say '  changed:'
    foreach ($line in $script:Changes) { Say ('    ' + $line) }
  } else { Say '  nothing was changed' }
  if ($script:Failed.Count -gt 0) {
    Say '  failed:'
    foreach ($line in $script:Failed) { Say ('    ' + $line) }
    return 1
  }
  return 0
}

try { $code = @(Invoke-Main $args)[-1] } finally { Remove-Checkout }
if (Get-Variable -Name PSCommandPath -ValueOnly -ErrorAction SilentlyContinue) { exit $code }
if ($code -ne 0) { Say ('install.ps1 finished with exit code ' + $code) }
$global:LASTEXITCODE = $code
'''
