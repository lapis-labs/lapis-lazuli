# Exploring references for a design run

## Sections

Read the step you are on, by heading; the rest are later steps.

- 0. Receive hints: a recorded rotating starting set, and the independent search it does not replace
- 1. Find candidates: searches that name the subject's own world, and where to look
- 2. Capture: capturing each reference with `lazuli ref capture`, one at a time, at a human pace
- 3. Look: opening each capture and reading its order, scale, density, HTML, and CSS
- 4. Write the record: the shape of `.lapis/references/<task>.md`
- 5. No network, or no lookups: the two honest records for a step that cannot run
- 6. Carry it into the plan: citing the record and naming the source of each candidate

The `references` step of `lapis-design next` comes after the brief and before the plan of a create run. A
run that picks its own references from memory, or reads about them, brings back a list of encyclopedia
pages and a page that looks like every other page. A reference is evidence only when you have looked at
it: the picture, and for a web page its HTML and CSS too. The step's check counts the files that show you
did, not the quality of the looking.

## 0. Receive hints

Run `lazuli hints` to choose the nearest field, then `lazuli hints --field <field> --task <task>`. It offers
three starting points sorted by a task/date/field/URL hash and records their URLs, field, and date in
`.lapis/references/<task>.hints.json`. Repeating that field reprints the original draw, even on another day.
`--date YYYY-MM-DD` selects a rotation for a new task; use `--field none` only when no field fits.

Hints are starting points, not a canon, and their recognition does not establish usability or the current
design. Access policies still apply. Find at least as many references beyond the **whole hints list**, not
just this draw, as were offered (normally three). A URL on a hint's host and below its path is still from
the list; a source with no URL may be an independent find. The CLI checks this alongside the existing
six-reference and kind rules. Study whichever offered pages help, reject ones that do not, and search
the subject's world yourself. Do not read the entire data file to find a preferred draw.


## 1. Find candidates

- Search; do not only recall addresses. Use the harness's web search, and `lazuli search --type source
  <words>` for where to look. Run a few searches that name the subject's own world, not "design": a
  collection, a catalogue, a plate, a label, a sign, a timetable, a specimen, a tool.
- Spread the set. At least three kinds, and at least two outside web and UI design: `print` (a book,
  poster, packaging, label, map, ticket), `signage` (wayfinding, a sign, lettering, a transit graphic),
  `physical-object` (a product, tool, instrument, building), `archive` (a museum, library, or archive
  record), `media` (a painting, photograph, film, or other work), and `web-ui` (a site, app screen, or
  design system).
- Prefer pages that show over pages that describe: an object page of a museum collection, a digitized
  plate, a photograph of a sign on Wikimedia Commons, a product's own pages. An encyclopedia article
  describes; it counts as text-only.
- `lazuli sources` says how each registry source may be reached. `refused` and `browser-link` sources stay
  as they are: choose another source. A host the registry does not list may be read within robots.txt.

## 2. Capture

One at a time, at a human pace (a capture takes about half a minute; a few dozen requests in all); follow no
links. Use `--rights reference-only` and `--task <task>`:

| Source | Command | Study copies in `.lapis/references/<task>/<slug>/` |
|---|---|---|
| A web page | `lazuli ref capture <url> --rights reference-only --task <task>` | `390.png`, `768.png`, `1440.png`, `page.html`, `style-N.css`, and the digest `<slug>/facts.md` |
| A picture at an address | `lazuli ref profile <image-url> --rights reference-only --task <task>` | `image.<ext>` |
| A page as text (weak) | `lazuli read <url> > .lapis/references/<task>/<slug>.md` | the text |

A page names its pictures in the digest `<slug>/facts.md` (`og:image`) and in its own markup; pass the address
of the picture itself to `lazuli ref profile`. Exit 1 means a refusal or a block; the output names the link
for the user. Never get around it.

## 3. Look

- Open every capture image with the harness's way of looking at an image file (Claude Code: Read the
  path). Look at the order of regions, the scale jump between the largest and smallest thing, the density,
  the edges and spacing, the color, how the type is set. A reference you did not open is not looked at.
- For a web page, read `<slug>/page.html` and `<slug>/style-N.css` (search them for `font-family`,
  `font-size`, `grid-template-columns`, `max-width`, custom properties, and colors). `<slug>/facts.md`
  counts what they state; write `source_facts` from values you saw, not from the digest alone.
- If the harness cannot show you an image, say so in your final report; do not write references you did not
  see.

## 4. Write the record

`.lapis/references/<task>.md`: Markdown with one fenced `yaml` block.

````markdown
# References: <task>

The captures are under `.lapis/references/<task>/`, for study only.

```yaml
captures: study-only
references:
  - id: bradshaw-plate
    url: https://upload.wikimedia.org/wikipedia/commons/a/a9/Example.jpg
    maker: George Bradshaw; scan held by a library
    kind: print
    decision: layout of the run history
    capture: .lapis/references/<task>/upload-wikimedia-org-wikipedia-commons-a-a9-example-jpg/image.jpg
    relation: take the heavy time column against a light ruled body, so a row reads left to right; leave the faces and the ornament
  - id: docs-site
    url: https://docs.example.com/
    maker: Example, Inc.
    kind: web-ui
    decision: type scale for the data table
    capture: .lapis/references/<task>/docs-example-com/1440.png
    source_facts: body 16px/1.6 in a system stack; content column max-width 68ch; 12-column grid with 24px gap; ink #111 on #fafafa
    relation: take the one narrow reading column beside a wide table; leave the palette and the pairing
```
````

| Field | Content |
|---|---|
| `id` | unique within the record |
| `url` or `source` | where it is; `source` when it has no address (the user's own photograph) |
| `maker` | author, maker, or the institution that holds it |
| `kind` | `web-ui`, `print`, `signage`, `physical-object`, `archive`, or `media` |
| `decision` | the open decision it informs (type, palette, layout, motion, direction, copy) |
| `relation` | what you take, in what you saw; where it stops |
| `capture` | an existing file under `.lapis/references/<task>/`; its own file for each reference |
| `source_facts` | for `web-ui`: values read from its HTML and CSS (sizes, faces, colors, grid) |

The check wants at least six references, at least three kinds and two outside `web-ui` among those you saw as
images, every capture a real file, `source_facts` that state a value for each `web-ui` reference, and no more
than two text-only references. A reference is text-only when its capture is not an image or its page is an
encyclopedia; it counts toward the six and toward nothing else.
The recorded hints offer must also exist, and at least as many references must be agent-found beyond the
whole list as were offered. Put the actual independent sources in the same `references` array; do not
label a listed page independent merely because it was not offered in this rotation.

Take relations, not surfaces: order, ratio, rhythm, density, a label's job, how a table is ruled. Leave
assets, text, brand colors, marks, the exact type pairing, and any signature composition. A result close to
one reference in layout, palette, type, and copy at once is a clone.

## 5. No network, or no lookups

Two honest records stand for a references step that does not run. Neither is a pass: `next` goes on to the plan,
and the finished run and `release check` report that no references were looked at.

The user's words forbid network use, lookups, or downloads during the work, and nobody can be asked: follow them.
Do not look things up, and do not stop. Decline the step with the user's own line, exactly as the brief record
(`.lapis/answers/<task>.md`, under `Found`) or the plan's `brief.constraints` holds it:

```
lapis-design next --task <task> --declined references --brief-line "<the line>"
```

The command refuses a line that is in neither, so copy the request's line into `Found` as the user wrote it
first. The plan's `explorations` still compare candidates for every open decision, from local material: the
installed fonts (`lazuli local fonts`), the project, and the brief's facts.

The network cannot be reached from here at all (not a line of the brief): record the error.

```
lapis-design next --task <task> --unavailable references --reason "<the error you got>"
```

The command sends one plain GET first and refuses the record when it works. Never write a record for
references you did not look at.

## 6. Carry it into the plan

Cite the record from the plan's `context.other` (a declined step has none: cite the brief record). Put each
reference you took something from in the plan's
`references` (the profile at `.lapis/refs/<slug>.json`, `rights: reference-only`, `mode: analyze` or
`borrow`, what to `take` and `leave`), name it as the `source` of the candidate in the `explorations` entry of
the decision it informed, and list it in `sources`. The captures stay where they are: git-ignored, for study
only, never shipped or copied into the page, and deleted by nothing automatically.
