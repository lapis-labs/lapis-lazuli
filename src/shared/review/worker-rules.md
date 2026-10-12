# Rules every delegated task carries

A task you hand to another agent (a rough worker, a critic, a builder, a reviewer) starts blank: it has not read the root
skill, so it does not know these rules unless the task says them. Put the lines under **The rules** into every delegated
task verbatim. `lapis-design` prints them where it names a delegation (`diverge`, `critic packet`, `slice`), and checks what
it can afterwards (see **What is checked, and what is not**).

## The rules

- Do not open the source of a check (`lapis_design/lint`, `lapis_design/render`, `lapis_design/behavior_check`) to argue with a finding or to make a page pass it. Put a finding you believe is wrong in `.lapis/disputes/<task>.yaml` (`shared/review/disputes.schema.yaml`): a critic re-judges it on the captures, the owner sees both, and a dispute does not clear it.
- Stop a process only by a process id a command recorded (such as the one in `.lapis/logs/<task>.<step>.pid`). Never stop one by pattern: no `pkill`, no `killall`, no `pgrep`, `pidof`, `lsof`, or `ps` piped or substituted into `kill`, with or without `-f`. Other work shares the machine, and a pattern reaches it.
- Say in your last message which of these you could not keep, and why.

## What is checked, and what is not

- The pre-write hook (`pre-write`, which also receives `Bash` calls) refuses a shell command that stops a process by pattern, in a project that has a plan, in the main session and in every subagent of a harness whose hooks run for subagents (Claude Code does; the extension for Oh-My-Pi and pi sends `bash` calls to the same hook). A command that kills by pattern through a script or an interpreter (`python -c`, a shell script file) is not seen.
- A `SubagentStop` hook (Claude Code only) reads the subagent's own transcript, and `lapis-design worker check --task <task> --transcript <file>` reads any transcript file you give it. Each `pkill`, `killall`, or kill by pattern, and each path under `lapis_design/lint`, `lapis_design/render`, or `lapis_design/behavior_check` that a tool call touched, becomes a line of `.lapis/state/<task>.workers.json` and of the owner block's integrity section. Reading is only recorded, never refused: the hook cannot tell a worker arguing with a finding from a person working on the checker.
- Not checked: a harness that gives the CLI no subagent transcript (Codex, Antigravity, Hermes), reads in the main session, and a transcript format the scanner does not parse. There the rule rests on this text and on the critic's question: ask the maker which delegated work read check source or stopped a process, and put the answer in a finding when it did.
