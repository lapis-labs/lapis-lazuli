# Structure and navigation

## Sections

Read the section the navigation decision needs, by heading; the rest are other decisions.

- Structure before chrome: content structure, destinations, and the levels the product has
- Labels: naming destinations and actions, including Korean labels
- Choose the navigation model: global, local, and contextual navigation and the pattern for each
- Navigation or not: link, button, or other control, from what activating it does
- Where am I, and the way back: current place, breadcrumbs, history, return paths
- Search: when to add it and how Korean input changes it
- Long collections: paging, loading more, and filtering large lists
- Across widths: what a width change keeps and what it may change
- The kiln shop: the worked navigation example
- Check: the behavior probes to run after changing navigation

This file backs the skill's start (where a person starts and how they know it is done), `flows`
(`start` and `done` are routes), the **Returning** bullet under the states, and **Interaction**. The
plan has no navigation field, so the decisions land in existing ones: destinations in
`layout.procedure.content_inventory`, the navigation model and its compact form in
`layout.procedure.relationships` and `layout.procedure.responsive`, top-level labels in
`content.key_copy` with `slot: nav`, the routes flows start and end on in `flows`, and the model
that lost in `claims.proposed`. The screen archetype, reading order, grids, and region
transformations are the `lapis` skill's layout step; final wording and register are the `lps-copy`
skill's. This file decides what the destinations are, how they are grouped and named, how people
move among them and back, and what search covers. Examples continue the example plan's pottery shop:
twenty-four pieces from one firing, reserved mostly on phones.

## Structure before chrome

Navigation exposes a structure; it never repairs one. Four things have to agree: how content is
grouped, what each group is called, how people move between groups, and what search covers. A tidy
menu over vague groups is still vague, and search does not replace grouping.

1. **List what can be reached.** Every page, object, and view, from `content_inventory` and
   `PRODUCT.md`, with its states: empty, archived, permission-limited, removed. Duplicate and
   overloaded labels show up here.
2. **Name the tasks and the nouns.** Write each top task with its circumstance and outcome, then the
   nouns that persist across tasks. They are the object model the interface shows: not the database
   schema, not the team's org chart.

   ```text
   Task: a visitor on a phone wants to reserve one piece before this firing sells out.
   Nouns: firing (소성), piece (작품), glaze (유약), reservation (예약), notice (알림).
   Relation: firing -> pieces -> at most one reservation per piece; notices follow firings.
   ```

3. **Choose a scheme per level.** Products mix them: the pottery shop groups pieces by firing, filters
   them by state, and treats reservations as objects.

   | Scheme | Groups by | Fits when |
   |---|---|---|
   | exact | alphabet, date, place, number | the reader knows the value |
   | topic | subject | a catalog or body of knowledge, with an owner for each boundary |
   | task | intended action | tasks are stable and distinct |
   | audience | role or situation | readers recognize themselves and the content truly differs |
   | object | domain nouns: orders, pieces, projects | an application, where actions attach to stable nouns the reader uses |
   | facets | independent attributes | a large catalog; facets are filters, not destinations |

4. **Give each item one home.** One canonical route and one place in the tree; other places link to
   it.
5. **Walk the tree in text.** For each top task, start at the top and write the label a reader would
   pick first, and why. When two siblings could both claim a task, rename or regroup. More steps are
   not worse; ambiguous steps are. No depth limit or click count replaces this walk.

```text
Weak:   설정 > 고급 > 관리 > 옵션
Strong: 작업실 설정 > 구성원 > 초대 > 대기 중인 초대
```

The strong path names objects and state, so each step predicts the next.

In a redesign the existing structure is learned behavior. Keep routes, labels, and saved links unless
the brief gives evidence or the user authorizes a change; write what must survive in
`brief.constraints`, and redirect every route that moves.

## Labels

- A label promises a destination. Name destinations with nouns and actions by their outcome; 자료실,
  더보기, and 서비스 promise nothing.
- Siblings sit at one level. 보안 / 팀 / 계정 삭제 mixes a domain, an object, and an action.
- One term per concept across navigation, page titles, headings, breadcrumbs, and results. Synonyms
  belong in search matching, not in the interface.
- Read each label with no icon and no neighbors; if it needs an icon or a tooltip, change the words.
  An icon-only control still needs a name (`component.unnamed-icon-button`), and emoji never stand in
  for icons (the `improvised-icons` card).
- Draft top-level labels as `content.key_copy` entries with `slot: nav`, one per locale. Unlike a
  headline, a label should not carry the subject's voice: use the plainest word the reader already
  uses. `plan check` applies the name-swap test to headline, subhead, and other key copy, not to `nav`.

### Korean labels

- Destinations are nouns: 작품, 소성 기록, 예약 내역. The -하기 form (예약하기) belongs to buttons that
  act. A sentence ending (보러 가요) is copy, not a label, so the register in `content.voice` does not
  show in navigation.
- Hangul syllables are wide, about 0.85 to 1 em depending on the face, so Korean labels are short in
  characters but not narrow: four syllables at 12 px take about 41 to 48 px, and five bottom-bar
  items on a 360 CSS px screen get about 72 px each. Keep tab labels to two to four syllables and
  design the 200% text state: the bar may grow and a label may wrap at its space, but nothing is
  clipped or cut with an ellipsis.
- With `word-break: keep-all`, 소성 기록 wraps at its space when room runs out. Space each compound noun
  one way (소성 기록 or 소성기록) in navigation, titles, and breadcrumbs alike.
- Name what is inside instead of a catch-all: 예약 내역 over 마이페이지 when reservations are all it
  holds. A menu button or last tab named 전체 that opens the full destination list is familiar; it is
  never the only way to a frequent destination.
- An English label on a Korean page (SHOP, ABOUT) reads as foreign to many readers and needs
  `lang="en"` so screen readers switch voice. Use one only when it is the brand's established term.

## Choose the navigation model

A product needs only the levels its structure has: **global** (top-level areas on every page),
**local** (views inside the current area), **contextual** (links in content and between related
objects), **utility** (sign-in, account, cart, help), and **wayfinding** (title, current item,
breadcrumbs where hierarchy matters). Each level gets its own pattern and place. No page needs a
navigation bar by default: a shop with one page and its details needs a way home and a way up, not a
소개 / 샵 / 문의 row copied from the category.

| Structure | Primary pattern | Companion | Avoid |
|---|---|---|---|
| a few broad destinations on a site | top bar | a labeled menu for secondary groups | a mega-menu without a real hierarchy |
| many stable areas in daily work | sidebar or rail | command palette as an accelerator | a dense top bar with hidden overflow |
| peer views of one object | tabs | an Up link or breadcrumb for ancestors | nested tab sets, tabs as sequential steps |
| a few frequent peer destinations on phones | bottom tab bar | a stack inside each tab | unlabeled icons, commands in the bar |
| less frequent destinations at compact width | menu sheet | the primary action outside it | hiding the one primary action inside it |
| a deep content hierarchy | sidebar plus breadcrumbs | search, on-this-page links | breadcrumbs that replay the path taken |
| a stable, revisitable result set | pagination | filters and sort in the URL | appending that loses position |
| an ongoing feed | load more, or infinite scroll | restored position, an end state | footer content that can never be reached |

For any pattern, decide the current-item mark, overflow, the compact form, and the keyboard model.

- **Tabs** switch peer views and keep the object's context. As a tab set (`role="tablist"`), arrow keys
  move between tabs and Tab leaves the set; as links to routes, each is a plain link and the current
  one carries `aria-current="page"`. Never wrap tabs into two rows: scroll the row inside its own
  region with a visible cue, or use a labeled select.
- **Bottom tab bar**: visible text with every icon; the platform or host sets the count. Each tab keeps
  its own stack and scroll position. No commands in the bar; it stays inside the safe area and gives
  way to the on-screen keyboard.
- **Menu sheet**: opened from a named button (전체 메뉴), never from a link and never on arriving at a
  route. A flat list of destinations, each opening a page. Overlaying the page, it behaves as a modal:
  focus moves in and stays while open, Escape and a visible 닫기 close it, and focus returns to the
  button (`ux.dialog-focus`).
- **Sidebar or rail**: collapse to icons only where each icon is already learned, with names on focus
  as well as hover (`ux.hover-content`). A parent with children either expands or opens its page on
  activation, never both; a current child keeps its parent expanded.
- **Breadcrumbs** show the hierarchy, not the path taken; the last item is the current page, not a
  link, and they never replace the title.
- **A command palette or search** speeds up known destinations; it never replaces navigation.

## Navigation or not

Start from what activating a control does, not from how it looks:

| Activating it | Build it as | State |
|---|---|---|
| moves to another destination | a link, in a bar or as a route-backed tab | `aria-current="page"` on the current one |
| swaps peer panels in one context | a tab set | `aria-selected` on the chosen tab |
| changes how nearby content is shown or filtered | a segmented control or radio group | checked; no new destination |
| chooses a value for later submission | radio, checkbox, select | a form value, not a location |
| runs a command | a button or menu item | busy, then a result; no lasting selection |
| reveals content in place | a disclosure | `aria-expanded` |

On a piece page, 작품 정보 and 소성 기록 swap peer panels: tabs. 크게 보기 / 목록 보기 changes how the
gallery shows pieces: a segmented control, not two destinations. 공유 is a command with a result.
예약 가능만 is a filter value that belongs in the URL. They may share a pill style, never semantics.
Current marks location, selected marks a choice in a widget, and focus can sit on an unselected tab.
`behavior check` activates every control and records whether its effect matches its look: a link that
goes nowhere, or a tab that changes nothing, is `ux.dead-control`.

## Where am I, and the way back

- The page `<title>` and `h1` name the current place; the current navigation item carries
  `aria-current="page"` and a visible mark that is not color alone.
- On a client-side route change, update the title, move focus to the new `h1` or `main`, and let the
  change be announced; no probe checks this.
- Put site navigation in `nav` elements outside `main`, name each when a page has several (주 메뉴,
  작품 분류), start `main` with the `h1`, and make the first stop a skip link that shows on focus and
  moves focus into `main` (`ux.no-bypass`, `ux.skip-link-missing`). `layout.wrapped-navigation` reads
  only text inside `nav` or `role="navigation"`.

Back, Up, and Close are three contracts; never give one icon all three meanings.

| Control | Does | Never |
|---|---|---|
| browser or system Back | returns to the previous history entry; may first close an overlay the user opened | holds the user with added entries or a reopened sheet (`ux.back-trap`) |
| Up, an in-page link to the parent | goes to the canonical parent, whatever the entry path | wears a back arrow while ignoring history |
| Close (닫기) | leaves a sheet, dialog, or bounded flow and returns focus to its opener | discards typed work without asking |

Decide per route what history keeps:

- Filters, sort, page, and the chosen tab of a shareable view go in the URL, so Back, reload, and a
  shared link restore them; Back also restores scroll position and typed input
  (`ux.lost-context-on-return`).
- A sheet the user opened may add one history entry so Back closes it; a page never adds entries by
  itself.
- A multi-step task gets a route per step, not a sheet that holds several. `ux.routine-modal` covers a
  blocking dialog that opens from a link, opens on a route change, or holds several flow steps.
- After sign-in, land on the route that asked for it.
- A destination the person may not open says why and who can grant it, when knowing it exists helps.
- Every route works as a first page. A piece link shared in a messenger opens in that app's built-in
  browser with no history behind it, so Back may leave the site; the page carries its own way up.

## Search

Add search when a collection is too large or varied to browse, or readers arrive knowing a name;
twenty-four pieces need a filter. Then decide the scope (this firing, all firings, help) and what a
signed-out person may see; matching, with synonyms in both scripts (청자, celadon) and common
misspellings; the query in the URL; and zero-result recovery. The results layout is the `search`
archetype in the `lapis` skill.

### Korean input

- Korean input methods compose each syllable from jamo. While composing, `InputEvent.isComposing` is
  true and the value holds an unfinished syllable. Update suggestions from `input` events, but do not
  submit, change the route, move focus, or rewrite the field's value before `compositionend`: a field
  re-rendered mid-syllable can drop or double jamo.
- Browsers have differed on the Enter that finishes a syllable: some deliver it while composing, others
  after composition ends, still marked as a composition key (`keyCode` 229). A keydown handler that
  acts on Enter, such as choosing a suggestion, ignores the event while `event.isComposing` is true
  or its `keyCode` is 229. Submit from the form's `submit` event, read the value then, and test with
  a Korean keyboard on every target browser, phones included.
- Compose queries and the index with `normalize("NFC")`, since pasted text can arrive decomposed.
  Match with and without spaces (소성기록, 소성 기록). For lists of names, consider initial-consonant
  matching (ㅊㅈ finds 청자), a habit many Korean readers bring. Keep Hangul and Latin forms of
  loanwords (머그, mug) as synonyms.
- The history probe pastes a whole `search` value from the stub's `values`, so no check exercises
  composition; test it by hand. Stub routes match the path alone and a `list` route returns the whole
  collection (`../shared/behavior/stub.schema.yaml`), so server-side search, filtering, and paging
  cannot be exercised through the stub yet; say so when you report the checks.

## Long collections

| Pattern | Choose when | Keep |
|---|---|---|
| pagination | people return to a known place, compare, or share a page | the page in the URL; the current page marked `aria-current="page"`; full-size previous and next; a filter change returns to page 1 |
| load more | continuous browsing where position still matters | focus on the control or the first new item, never the top; the count so far and the total |
| infinite scroll | a feed where exact position and the footer do not matter | an end state, retry after an error, position restored on Back, footer content reachable elsewhere |

A very large list that renders every item is `code.unvirtualized-list`; a virtualized list still
restores position on Back.

## Across widths

A width change keeps the destinations, the current location, history, names, and reachable targets;
only the chrome changes. Write in `layout.procedure.responsive` what the navigation becomes at each
width: a top bar keeps its priority items and moves the rest into a labeled menu; a sidebar becomes a
rail only with learned icons, then a menu sheet or bottom bar on phones; tabs scroll in their own
region or become a select. Never add destinations because the window grew.

- No two-row navigation at desktop width (`layout.wrapped-navigation`), nothing clipped or
  overlapping at compact widths (`layout.compact-overflow`).
- A bottom bar, a sticky commit button, a banner, the on-screen keyboard, and the safe area can all
  claim the bottom edge. Say in the plan which navigation must stay; the `lapis` layout step decides
  the stacking, and the focused control is never covered (`ux.focus-obscured`).

## The kiln shop

The job is to see this firing's pieces and reserve one, mostly on phones. There is one page, `/`
(log row, gallery, full firing log, notice signup), plus a piece at `/pieces/:id` and a reservation at
`/reservations/:id`. The header holds the studio name, leading home, and 예약 확인; no tab bar, no
menu sheet. The open-only filter lives in the URL, so Back from a piece returns to the same filtered
gallery at the same scroll position. A shared piece link opens cold, so the piece page links up to the
gallery beside its title. Add these lines to what the layout step wrote in `layout.procedure` and
`content`:

```yaml
layout:
  procedure:
    content_inventory:
      - "routes: / (log row, gallery, full firing log, notice), piece /pieces/:id, reservation /reservations/:id"
    relationships:
      - "site header: structural region - studio name linking to /, then 예약 확인; no destination row"
      - "piece page: an Up link named for the gallery (9월 소성 작품) beside the title; a shared link opens it with no history"
      - "open-only filter: a form value on the gallery, kept in the URL, not a destination"
    responsive: >
      header: one line at every width; at 320 with 200% text 예약 확인 wraps below the studio name,
      never behind a menu button. piece page: the Up link stays beside the title at every width.
content:
  key_copy:
    - { slot: nav, text: 예약 확인, locale: ko-KR }
    - { slot: nav, text: 9월 소성 작품, locale: ko-KR }
claims:
  proposed:
    - "A bottom tab bar lost: one page and its details need no persistent tabs, and the bar would take height from the gallery on every phone"
  unresolved:
    - "How 예약 확인 finds a reservation without an account: reservation number and phone, or only the link in the confirmation message"
```

Reserving opens from 예약하기 on the piece page. While it takes one screen, a sheet serves; if the
unresolved delivery regions add a step, reserving moves to its own route (`/pieces/:id/reserve`).

## Check

After changing navigation, run `lapis-design behavior check <url> --task <task> --plan
.lapis/plans/<task>.yaml --stub .lapis/stub.yaml --probe history --probe keyboard --probe dialogs
--probe controls --probe flows --probe pointer` (`flows` for a sheet that holds several steps,
`pointer` for content shown only on hover). A run with `--probe` writes
`.lapis/behavior/<task>.narrow.json`; the full session at `<task>.json` is the release gate's.

| Probe | Records | Rules | By hand |
|---|---|---|---|
| `history` | sets a filter, page, search, and scroll on the entry route where it finds them, follows a link, presses Back; presses Back from the entry page until it leaves; with a stub account, signs in from a protected route | `ux.lost-context-on-return`, `ux.back-trap` | system Back in native apps, per-tab stacks, deep links opened cold |
| `keyboard` | Tab walks over several routes: order, traps, covered focus, repeated stops before `main`, the skip link | `ux.focus-order`, `ux.keyboard-trap`, `ux.focus-obscured`, `ux.no-bypass`, `ux.skip-link-missing` | arrow keys in tab sets and menus, focus after a route change |
| `dialogs` | menu sheets and other layers: focus in, contained, Escape, a close control, focus returned | `ux.dialog-focus`, `ux.routine-modal` | a sheet that holds anything but destinations |
| `controls` | whether each control does what its look promises | `ux.dead-control` | the current item marked with `aria-current` |
