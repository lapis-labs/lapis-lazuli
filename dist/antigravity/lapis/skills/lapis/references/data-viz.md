# Data visualization

## Sections

Read the section a chart or data-view decision needs, by heading; the rest are other decisions.

- Start from the question: what the reader asks, which settles the form before any polish
- Choose the form: which chart or table answers each question, and what to settle first
- Honest scales: baselines, axes, and ranges that keep a comparison valid
- Labels, annotation, and uncertainty: titles that state the question, annotation, uncertainty
- Dashboards and analysis views: one job per region (monitor, diagnose, compare, act)
- Data color: scale and color rules a chart adds to `color.md`
- Access to a chart's values: the nonvisual task, table or text equivalent
- Keyboard, touch, and updates: interaction that earns its place, and live updates
- Building it: the access contract first, then the renderer
- What the checks cover: what the checks read about a data region and what they cannot

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

| Encoding | Strength | Cost to inspect |
|---|---|---|
| shared position or length | rank and small magnitude differences | space with many categories |
| separate positions or panels | related comparisons | scanning and scale coordination |
| area or angle | broad composition or spatial pattern | exact comparison |
| color intensity | dense spatial fields or matrices | steps, mark size, display conditions |
| shape or texture | a second category cue | noise as marks accumulate |
| animation | continuity between related states | comparison from memory |

Treat these as tradeoffs, not a universal ranking. Compare side-by-side states when a decision
depends on a difference that animation would ask the reader to remember.

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

For one real selection, write expected population, period, unit, values, and absent-value reasons
from authoritative data. Compare graphic, summary, table, and selected download against that
record. Change one filter and repeat, including reference lines and intervals. On failure,
compare the still-displayed old scope, not the pending selection. Claim only the inspected
selections; a synthetic example proves nothing about permissions, live updates, or other states.

| Check | Reads | Leaves out |
|---|---|---|
| `color.text-contrast` | text color against the weakest captured backdrop, including vector labels | graphic marks, color-vision differences, and labels whose fill differs from their text color |
| `component.small-target` | interactive boxes and their spacing from neighbors | marks with no interactive role; declared exceptions still need review |
| `imagery.missing-content-image` | raster image alternatives | inline vector or canvas names, and whether any alternative explains enough |
| `layout.compact-overflow` | page overflow, clipped text, and overlapping controls at compact widths | overflow contained within a chart's own region |
| `layout.shrunk-desktop`, `layout.bento-filler`, `layout.card-everything` | column persistence, empty grid cells, and content enclosed in cards | whether a module answers a useful question |
| `copy.placeholder-content` | placeholder entities in planned and rendered copy | domain fit of synthetic rows |
| `code.locale-time-rendering` | locale and number-format choices in source, and runtime hydration mismatches | the time zone a chart should use |
| `code.unvirtualized-list` | direct children in a scrolling or unusually tall list | table rows nested within a body |
| `ux.status-not-announced` | newly reported results after an action, announcements, and focus movement | a changing measurement alone, previous text, or whether the announcement describes every result |
| `ux.hover-content` | revealed content at an interactive box's center and its focus, persistence, and dismissal behavior | unrecognized marks within a graphic |
| `ux.gesture-only` | recognized drag targets and nearby alternatives | unexercised gesture directions or changes outside the target's group |
| `motion.reduced-motion-missing` | nonessential spatial or media movement under the reduced preference | stationary fades, animated child shapes, and content the probe classifies as essential |

Color-role extraction reads the painting box's presentation and structure; it does not understand the
data. `color.competing-accents` also reads declared data colors in `tokens.color.roles` and
`tokens.color.data_scales`. Record an earned exception in `defaults`, rather than changing names to
influence extraction. Sampling bounds and recognition lists belong to the check-bounds reference.

No check compares a chart with its table, tests series colors against the plot surface, simulates color
vision, or judges its summary, form, axes, or scale. Declaring `tokens.color.data_scales` informs palette
analysis but does not run the per-scale checks named in the vocabulary. Inspect those by hand across
themes and widths, use the keyboard, compare table and graphic, and report unexercised paths.
