# Data visualization

This file backs the `data-visualization` frame (`brief.product_frame`) and any chart, map, or data table inside another frame. Region order is in `archetypes.md`, a chart's place, span, and rank in `layout.md`, and the choice of a data scale in `color.md`; this file decides what is inside a data region. The examples continue the pottery page's firing log, with synthetic numbers.

| Decision | Where it lands in the plan |
|---|---|
| the question a region answers | `layout.sections[].answers`; the screen's job in `brief.one_job` |
| each measure's period, unit, comparison, source, freshness | `layout.procedure.content_inventory`, one entry per measure |
| what is not known: baseline, revision authority, suppression rule | `claims.unresolved`, or a reversible assumption in `claims.proposed` |
| title, summary, and empty-state text | `content.key_copy`, worded with `lps-copy` |
| what changes at each width | `layout.procedure.responsive` |
| scale kinds and data colors | `tokens.color.data_scales`; `tokens.color.roles` entries with `role: data` |

## Start from the question

Polishing a chart can make an invalid comparison more convincing, so settle what can change the form first:

- the decision or question, and who asks it;
- the unit behind each row, the measures, and the comparison or baseline that gives a value meaning;
- the time grain, and the zone times are read in;
- which values are absent, withheld, estimated, or sampled;
- how fresh and how uncertain the data is, and where it comes from.

Ask only what could change the chart; an open item that would is an `unresolved` claim. Never invent a threshold, baseline, cause, or value so that an empty view looks finished, and remove a chart that answers no question instead of styling it.

"How many pieces came out of each of the last four firings?" is a count by date: bars from zero, or a table of four rows. "How did the kiln behave during this firing?" is a value over hours against a hold target: a line with the target drawn and labeled. Two questions, two forms, two regions.

## Choose the form

| The reader asks | Start with | Settle first |
|---|---|---|
| which is larger, or how they rank | aligned bars, a dot plot, a table | exact values, or only order? |
| how it changed | a line, small multiples, an area with care | is the continuity real, are the intervals even? |
| how values are spread | a histogram, a box or strip plot | shape, outliers, or one summary? |
| whether two measures move together | a scatter, a connected scatter, a matrix | association, grouping, or sequence? |
| what makes up a whole | stacked bars, a treemap, a pie in narrow cases | part-to-whole, or exact comparison? |
| where it is high or low | shaded regions, sized symbols, a flow map | totals, rates, or locations? |
| where things go or drop off | a flow diagram, a funnel, a state diagram | paths and losses, or exact values? |
| what one value is | a table, one highlighted value with context | would a chart make lookup harder? |

These are hypotheses, not one chart per task; volume, sign, order, and the audience's familiarity change the answer. When lookup dominates, a plain table is a complete answer.

Readers judge positions along a shared scale more accurately than area, angle, or color intensity, so use bars for ranking, small differences, many or shifting categories, and negative values. A pie fits a small, stable part-to-whole with an evident total, direct labels, and coarse differences; a ban on pies is as arbitrary as allowing them anywhere. Decorative 3D distorts the comparison.

## Honest scales

- Bars start at zero, because a bar's length is its magnitude. A line may use a narrower range when the point is change and the scale makes that plain.
- Label a log scale as one. Two value axes can suggest a relation their scaling invented: prefer aligned small multiples or an indexed comparison, and share an axis pair only when it is justified and labeled.
- Show rates or shares for likelihood or proportion, totals for workload or size; a map of raw counts redraws the population.
- Keep time honest: a gap, an uneven sampling interval, or a zone shift stays visible instead of being smoothed away.
- Hold the scale fixed across selections readers compare; an axis that rescales on every filter invents differences.
- A broken axis, truncated domain, smoothing, or cumulative view can be legitimate. Disclose it, and never let it inflate the claim.

## Labels, annotation, and uncertainty

- Title the view with the question or the finding ("Pieces out of the kiln, last four firings"), not "Overview". A causal headline is never written over data that shows only association.
- Put units in axis titles, headers, or values, and round to the precision the collection supports. Label directly when that saves a legend lookup.
- Annotate a change with its evidence: an event, a threshold, a policy, a data caveat. A decorative arrow is not evidence.
- Tell actual, forecast, target, and scenario apart with more than color: line style, a label, a region.
- Distinguish absent observations, suppressed results, readings below detection, and values beyond the plotted domain with separate symbols explained in the legend. Never turn absence into zero or omit it without disclosure.
- Say how uncertain the data is in terms readers can use: an interval, the sample size, a suppression threshold, how late and how complete the data is, what changed when a value was revised. A "live" badge means a defined freshness window from a named source.

Chart copy names the population and the measure, and keeps "no events", "filtered out", "too small a sample", "no permission", and "query failed" as separate messages.

## Dashboards and analysis views

- Give each region one job: monitor (state against a threshold), diagnose (contributing segments, related events), compare (entities, periods, scenarios), or act (a route into a real workflow, carrying its context). A large number orients only with its unit, period, comparison, and freshness. A view joins a region only when it answers a follow-up no other view answers, and no module exists only to fill a grid.
- Controls sit beside what they change (`archetypes.md`); the mechanics of filters and selection belong to `lps-ux`.
- Do not shrink a desktop view. At each width decide, and write it in `layout.procedure.responsive`: which question stays primary; whether the chart scrolls sideways in its own named region at a readable text size, splits into small multiples, is summarized, or becomes a table; how hover detail becomes focus or tap detail; where the table stays reachable.

## Data color

`color.md` (Data scales) picks each scale by what the data means and lists it in `tokens.color.data_scales`. A chart adds the following.

- One focus against quiet context is not a fifth scale: write the context as a neutral and the focus as one `data` entry. A state belongs to `status`, with text and an icon, never to a chart hue alone.
- One color, one role. The action color is not every series, and an interface ramp step reused in a chart becomes its own `data` entry, tested as data in each theme. A category keeps its color when its state changes; "done" is text and an icon.
- Categorical: assign once and keep the assignment across related views and themes. Past the point where people can separate the hues in the real view, label directly, group, filter, or split into small multiples.
- Sequential and diverging: use classes when thresholds mean something, and record which side of each boundary is inclusive. A continuous ramp carries ticks. The midpoint of a diverging scale is a domain value that the legend names.
- Marks are smaller than swatches: a palette that separates large swatches can fail on a thin line, a small dot, or a low-opacity fill. Test the real marks against the plot surface and gridlines in each theme, and before raising chroma try a wider stroke, an added shape, direct labels, or fewer series.
- Give every consequential distinction a second encoding: direct labels, dash, or marker shape for series; hatching for areas; icon plus text for state; position or a boundary for selection. Under forced colors only labels, dashes, markers, and patterns survive. A palette called safe, or a simulation, is an input, not proof.

## Access to a chart's values

A name says what a chart is; it carries none of its evidence. Write the nonvisual task first: what a reader must be able to identify (the selection and its scope), understand (the comparison), and look up (every displayed value) without seeing color.

Give each layer its own job, and add one only for a task that needs it: a name with scope (question, measure, population, period); a visible summary (the relationship, baseline, uncertainty, a route to detail); a real, captioned table with header cells, units, and reasons for absence; and a download that names its selection and method. Do not pour a table into the graphic's description (`aria-describedby` flattens it into running text); link to it.

Chart, summary, table, and download agree on scope (filters, visible series, time grain, unit, data revision), values (including reference lines, interval bounds, and suppression reasons), transform, and order. Whatever clicking a mark does can also be done from the keyboard, for example through a named action on the matching row. No alternative exposes what the chart's permission model hides, and a download is never a way around suppression. A dense view gets a filterable, paginated table, and a sampled chart says it is sampled.

## Keyboard, touch, and updates

Interaction earns its place by answering what the static view cannot; not every mark becomes a tab stop. Pick a series or period with a native labeled select or radio group, and zoom or brush with labeled range or date controls and a reset beside the pointer gesture. To inspect single marks, use a library's tested navigation or a documented composite widget where arrow keys walk the data in order and the series and value are announced by name; decide what Home, End, and the ends do. Never capture page-level arrow keys outside the active control, and never add `role="application"` only to make a chart interactive.

Keep focus by the series or record identity, not by position. If a filter takes away the focused mark, send focus to the closest remaining item or back to the filter that caused it, and say so. A background update never reorders what someone is inspecting unless they can pause or review updates first.

A tooltip is never the only place for a value. Content shown on hover or focus can be hovered without vanishing, stays until dismissed, and closes without moving the pointer or focus when it covers other content; it opens from the keyboard, and on touch it is an explicit selection with a persistent detail.

Say that a filter or refresh finished in one concise message in a stable polite status region, without moving focus; keep the chart and table out of a live region. For a continuous feed, tell "view paused" from "source disconnected", and show freshness. A decorative draw-in needs a reduced-motion branch (`motion.md`); the live data view itself is content.

## Building it

The renderer draws marks; meaning, access, and state belong to the application. Write the access contract first, then choose the renderer on the chart wrapper, tokens, and export path the project already has: add the missing table or status message instead of replacing a working chart stack. A new dependency, hosted export service, or purchase needs the user's approval.

Choose the renderer by the marks. Vector markup fits a modest number of marks and inspectable labels. A 2D canvas fits dense repeated marks, but its pixels carry no per-mark meaning, so detail, hit testing, and keyboard routes become HTML you build. GPU rendering is for measured dense scatter or spatial work and adds context loss and picking. A server-made graphic has no interaction: ship text and a table. No mark count settles it, so measure with the real marks, device, theme, and update rate; a table of thousands of cells is often the bottleneck. When a canvas or GPU context is lost, keep the last committed text and table, say the graphic is unavailable, and never show a cached image as current.

Derive the selected data once and feed chart, summary, table, and export from it. At that seam record a stable identity per datum (team and month, not sorted position), the scope, the revision or freshness, the transform, and the pending scope, kept apart from the displayed one; a count is not a percent, and zero differs from missing. A new filter leaves the old chart in place, marked as updating, and everything commits together on success; on failure the old scope stays labeled as old, and a slow reply cannot overwrite a newer selection. Render a deterministic first scope, so dates, locale, zone, and number format agree between server and browser. Aggregate or bin only with domain approval, show the transform and coverage, and never average away a consequential spike.

## What the checks cover

Checks read boxes, text, source, and behavior; none reads a chart's meaning.

| Check | Reads | Leaves out |
|---|---|---|
| `color.text-contrast` | text against its surface in each theme and state, including `svg` labels measured from CSS `color`, not SVG `fill`; use `fill: currentColor` or check the labels by hand | marks, gridlines, the 3:1 for graphics, color-vision differences |
| `component.small-target` | buttons, links, and inputs under 24 px with neighbors in reach; a mark given a button role counts | a mark with no role |
| `imagery.missing-content-image` | an `img` or `picture` with neither `alt` nor an accessible name | an inline `svg` or a `canvas`, named or not; whether an alternative says enough |
| `layout.compact-overflow` | sideways page scroll, clipped text, overlapping controls at 320 and 390 px | a chart that scrolls in a region of its own passes; a fixed-width graphic wider than the page fails |
| `layout.shrunk-desktop`, `layout.bento-filler`, `layout.card-everything` | the page's boxes: the same columns at 390 and 1440 px, a cell that only fills the grid, cards holding most of the content | whether a module answers a question |
| `copy.placeholder-content` | stock placeholder names and companies in key copy and rendered text | whether sample rows fit the domain |
| `code.locale-time-rendering` | source: `toLocale*String` and `Intl` calls with no locale or one outside the plan's locales, hard-coded dates, hand-formatted numbers; runtime: hydration mismatches | the zone an axis reads times in |
| `code.unvirtualized-list` | more than 500 direct children of a scrolling box, or of a list taller than three viewport heights | a `table`: its rows sit in a `tbody`, so they are not counted |
| `ux.status-not-announced` | after a control is pressed, changed text that reports a result (in a status, alert, live region, output, toast, or snackbar, or text the box gained that names a result, such as saved, added, sent, 저장했어요, or a count of results or a cart, such as 12 results, 검색 결과 12개) with no announcement and no move of focus | a summary that names neither, such as "72 pieces in 4 firings", since a number that changes alone is not a result; text the box showed before the press; any announcement in the same action clears every result in it; the controls probe presses controls and never picks another option in a `select` |
| `ux.hover-content` | what an interactive box reveals when hovered at its center: shown on focus too, kept when the pointer moves onto it, held while hovered, closed by Escape when it covers content | a tooltip on marks inside an `svg`, which are boxes only with a role |
| `ux.gesture-only` | a drag on a recognized target (draggable, range input, slider, grab or resize cursor, or a `touch-action: none` target that is named, focusable, or a canvas): is a step button, menu, or other input beside it? Native range inputs are dragged sideways; other targets are dragged straight down | horizontal brushes are not exercised; a brush whose result appears outside the dragged target's own group |
| `motion.reduced-motion-missing` | under reduced motion, boxes that still move by transform (a fade that slides counts), scroll-linked animation, video, and canvas that is not essential | a fade in place; shapes that animate inside an `svg` (bars growing, a stroke drawing in), since only the `svg` box is watched; a canvas presented as content passes (in a `figure`, with a role and a name, or named as a chart, graph, plot, or map) |

The render guesses a color's role from the box that paints it. A chart that is named for what it shows (role `img` and an accessible name), or drawn as repeated marks with text labels, paints `data`, and table cells do too. The guess exempts nothing by itself: data hues stay out of `color.competing-accents` only when the plan lists them (`role: data`, `data_scales`). When a real chart is still reported, record a `defaults` keep with the reason; do not rename elements to change the guess.

No check compares a chart with its table, reads series colors against the plot surface, simulates color vision, judges a summary, or reads a chart's form, axis, or scale, and nothing reads `tokens.color.data_scales` (the vocabulary names a check for each scale; no detector runs it). Do those by hand: render the chart in each theme and width, operate it with the keyboard alone, read the table against the graphic, and report what you did not test.
