# Evaluation and benchmark methods

This folder says how LapisLazuli's evaluations and benchmarks are run and where their output may
appear. It holds methods and no results: no score, rate, or comparison between conditions is
written here. Diagnostic reports and case studies join this folder as they are published, under the
rules below.

The tooling is in `tools/eval/` (see its [README](../../tools/eval/README.md) for the protocol):
paired agent runs with and without the skills, scored with the repository's own checkers, and a
blind review sheet. That README says how a run works; this file says what may be said about its
output.

## Three kinds of output

**(a) Method and reproduction.** The procedure, prompts, scoring rubric, scripts, data lists with
hashes, splits, seeds, environment versions, exclusion lists, pre-registrations, and known limits.
How many runs, tasks, and conditions were run is method; what the runs showed is not.

**(b) Diagnostic figures.** Figures about a tool (the font measurer, a checker, a renderer path) on
a fixed, open corpus that anyone can fetch again. A figure counts as diagnostic only when:

- the reference labels were not made by the tool and were not used to tune it;
- items the tool could not measure stay in the count, and are not dropped;
- one table gives n, a 95% confidence interval, the tool's version, and the corpus version (a hash
  of its list);
- thresholds were fixed before the corpus was looked at, or were tuned on development groups only
  and the figures come from held-out groups;
- nothing in it derives from Adobe Fonts, subscription or commercial fonts, or fonts installed on
  a maintainer's machine;
- the sentence that reports it says what it covers and what it does not.

Not diagnostic: a calibration run on someone's installed fonts (the corpus is not open, may mix in
commercial or Adobe faces, and stays private), and lint counts of what an agent built (the checker
is the skills' own rules, so a count says what the rules flagged, not whether the design is good).

**(c) Performance claims.** Any statement that one condition, tool, or model is ahead of another: a
difference between condition means, a rank sum per condition, a before-and-after count, a percentage,
"outperforms", "state of the art". LapisLazuli does not make them, in any place below.

## Where each kind may appear

| Place | (a) Method | (b) Diagnostic figures | (c) Performance claims |
|---|---|---|---|
| README, README.ko | One sentence that points here | None; a link only | Never |
| CHANGELOG | Changes to methods and tools | None; "report updated" with a link | Never |
| This folder | Procedure, rubric, pre-registration, case records | Diagnostics for the measurer and the checkers | Never |
| A benchmark repository and its data card, if one is published | Datasheet, scripts, splits | Baseline tables for that benchmark version | Never; no "state of the art" for our own benchmark |
| A model card, if a model is published | Data lists, how it was made | A benchmark table beside the baselines, without adjectives | Never; no claim about the quality of a design |

This file, the READMEs, and the CHANGELOG hold no sentence about an evaluation, a benchmark, or
the skills that carries a percent sign, a multiplication sign, a number beside runs, tasks,
findings, or tokens, an "N of M", or wording that compares conditions or reports a gain.
`tests/test_eval_wording.py` checks that.

## Case studies

A case study of skill-effectiveness runs is a record, not a score. It holds:

- the header below, and the prompt and the scoring rubric verbatim;
- per candidate, screenshots at a phone and a desktop width, with the condition revealed only
  after the review;
- a hand-written process summary: whether the agent wrote a plan, which skills it opened, which
  checks it ran, what the lint flagged and what changed, the agent's last stated assumptions;
- per candidate, a findings table: the notes that passed with each reviewer's evidence, the checker
  findings a reviewer accepted or rejected, and problems no checker flagged;
- the rubric and the agreement between reviewers.

It has no per-condition means, differences, totals, or ranks, and every task is published,
including the ones that went badly. A task whose subject matches an example in the skills is marked
in-domain beside its record.

Not published: run folders (event logs, raw commands, isolation and run records), exports made for
named reviewers, user names, skill names, local paths, the agent's login, the review key before the
review ends, a reviewer's identity without consent, anything drawn or measured with Adobe Fonts,
and any figure that reads as a gain, including checker counts set side by side by condition.

## Wording

Fill the angle-bracket parts; add no adjectives.

- README: "The repository includes the kit we use to study how agents work with the skills
  (`tools/eval/`). Its results are case studies, not measurements of quality; see `docs/eval/`."
- CHANGELOG, method change: "`score.py` lints every condition against one evaluator plan and
  reports waived and skipped findings per rule (method change; no results)."
- CHANGELOG, measurer change: "Measurer <version>: <what changed>. Diagnostic report for the pinned
  OFL corpus: <link>."
- Diagnostic: "On <benchmark> <version> (OFL only, google/fonts @<commit>, <G> design groups,
  <split>), measurer <version> matched Google's SERIF/SANS_SERIF category for <k> of <n> families
  (Wilson interval at the 95 percent level, <a> to <b>; <u> unmeasured, counted as misses). Its
  thresholds were fixed before this corpus existed. This describes the measurer on this corpus only,
  not other fonts or designs made with the skills."
- Case-study header: "Case study, not a benchmark. <n> runs per condition, model <M> at effort
  <E>, Codex <V>, no browser in the agent's sandbox, skills at commit <C>. With this few runs no
  difference between conditions can be told from run-to-run variation, and none is claimed."
