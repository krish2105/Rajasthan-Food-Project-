# District Dashboard

The working tool for an Anganwadi supervisor, block officer, or a District
Collector's office. Section 9.2 asks for something "functional, clean ...
restrained — this is a working tool for a busy official, not a showcase."

```bash
cd backend && make serve
cd apps/district-dashboard && npm run dev
```

<http://localhost:3002> — port 3002 rather than 3001, which was already in use
on the development machine.

---

## What it is

Two tabs, and the order is the argument.

**Worklist** opens first, because a block officer arrives with "what needs me
today":

- **Children needing referral** — every child whose latest plausible measurement
  puts them at SAM or MAM, most severe first, then longest-since-measured. An
  SAM child last seen six weeks ago is the top of anyone's list.
- **Flagged days** — menu days the plates did not match, and food-quality
  problems seen across most plates. Each row names the *missing items*, not just
  a percentage, because that is what the officer acts on.
- **Centres not uploading** — not in Section 9.2's list, but it belongs here. A
  centre sending nothing is invisible to every other view on this page, and
  silence is indistinguishable from compliance unless something looks for it.
  Usually a broken phone rather than a broken kitchen; either way it is the
  officer's problem.

**Report** is the district-scoped version of the state review: growth
classification across the block, per-centre comparison, month by month, and menu
compliance. Presented as tables rather than charts, because this reader is
comparing centres and will annotate the result, not being persuaded by it.

## Recording follow-up

Section 15 draws the line this feature sits on: *"this system flags and
documents; it does not itself fix menu non-compliance — the intervention still
requires a human administrative response."* Recording that response is
documenting it. Performing it is not, and nothing here tries to.

Expanding a flagged day shows the centre's compliance strip, the full
prescribed-versus-detected lists, the follow-up history, and a form. Outcomes
are a closed list — visited, contacted, escalated, no action needed — because a
Collector asking "how many flags were acted on" needs a number, not a pile of
prose.

**Append-only.** A follow-up is never edited or deleted; a correction is another
row. Migration 0003 grants `INSERT` and `SELECT` and no `UPDATE` or `DELETE`, so
that is enforced by the database rather than by convention. For a record of what
an official did about a flagged kitchen, a history that can be rewritten is
worth less than none.

**`no_action_needed` requires a reason,** enforced in the form, in the API and
by a database CHECK. Overruling a flag is the one outcome where the next person
to read the record needs to know why, and three layers is not excessive for the
field an officer is most likely to skip.

**Only district officials write.** A state admin reads every district's
follow-ups and records none — they did not visit the centre, and claiming
otherwise in a permanent record is the failure mode worth designing against. The
RLS policy refuses it independently of the role gate.

---

## Design

Same palette as the state review, different density. An officer moves between
the two surfaces, and two palettes for one product is a tell.

Where they differ is everything except colour: 15px base type instead of fluid
display sizes, tighter spacing, zebra-striped tables, tabular figures
throughout — and **no entrance animations at all**. The review surface earns its
motion by holding a room's attention. This one is read at a desk for hours, and
a busy official should not wait for content to fade in.

`tests/tokens-in-sync.test.ts` asserts the token file matches the state admin's
byte for byte from `:root` onwards. A shared workspace package was considered
and declined for two consumers, so the test is what stops "kept in sync by hand"
from being a hope.

---

## Backend it added

Skipping Phase 4 in the original order meant these did not exist yet. They are
general endpoints under the existing RLS, not dashboard-shaped ones:

| | |
|---|---|
| `GET /compliance/flagged` | the queue, district-scoped, 30-day default window |
| `GET /compliance/quiet-centres` | centres with no recent uploads |
| `GET /compliance/{awc}/trend` | one centre's compliance day by day |
| `GET /reports/district/{d}/children` | the referral list, by classification |
| `POST /compliance/{id}/follow-up` | record a response (district officials) |
| `GET /compliance/{id}/follow-ups` | the append-only trail |

No route filters by district for security — RLS does, so a district official
calling any of them sees only their own district and the routes carry no
authorisation logic to forget.

One thing worth knowing: `/compliance/{awc_code}/{day}` had to be moved *below*
the literal two-segment routes. FastAPI resolves in registration order, so the
`{day}` parameter was matching `"trend"` and rejecting it as an invalid date.

## Accessibility

- Tables are real tables with scoped headers; the summary tiles are text, not
  images.
- Status is a labelled pill, never colour alone — `SAM`, `MAM`, `open`,
  `visited` all read as words.
- The compliance strip is `role="img"` with a description naming the flagged-day
  count, and every bar carries a `<title>` with its date and percentage.
- Form errors use `role="alert"` and name the field that needs attention.
- `prefers-reduced-motion` collapses the few transitions there are.

## Tests

```bash
npm test
```

18 tests here, plus 22 backend tests in `backend/tests/test_worklist.py`. The
backend ones carry the weight: they check that an officer sees exactly their own
district's work, and that what they record cannot later be rewritten.

## Known limitations

- **Auth is Phase 1's dev token**, exchanged server-side by `app/session/route.ts`
  so the phone number never reaches the bundle. Phase 6 replaces the body of
  that handler and nothing else.
- **No per-child drill-down.** The referral list names children and their
  measurements but does not open a growth history.
- **The 30-day queue window is fixed** in the UI. The API takes `since`, so
  widening it is a control this screen does not yet expose.
- **Follow-ups have no notification.** An escalation sits in the record until
  someone opens the dashboard.
