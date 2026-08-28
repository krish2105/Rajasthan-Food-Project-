# State Admin — review surface

The surface DoIT&C staff, iStart reviewers and a District Collector's office
actually see. Section 9.3 names this as the one place in the project that
should carry real polish, because it is what gets shown in a room.

```bash
cd backend && make serve          # the API this reads from
cd apps/state-admin && npm run dev
```

<http://localhost:3000>

---

## The design brief, and what it produced

**Audience:** government officials who read growth charts for a living and have
seen a great many dashboards.

**The hero is not a stat block.** It is the z-score distribution: every measured
child plotted against the WHO reference population, with the −2 and −3 SD
cut-offs marked. A prevalence percentage tells a reviewer how many children fall
past a threshold; this shows the whole cohort sitting to the left of the
population the standard was built from. That is the actual finding, and it is a
much harder thing to argue with than a number.

**The page is built on a growth-chart grid.** Fine graph-paper ruling, taken
directly from the artefact every ICDS supervisor already reads. The structure
encodes something true about what the system does rather than decorating it.

**Typography is IBM Plex** — Sans, Sans Devanagari and Mono. Drawn for
institutional use, and the one major superfamily with a real Devanagari cut, so
the bilingual headings sit on the same skeleton instead of looking like two
documents stapled together.

**Dark-first, for a specific reason:** this gets projected in a meeting room.
Projectors have poor black levels and worse ambient contrast; a bright page
washes out while dark ground with high-chroma data holds up. The print
stylesheet inverts to paper, because the report that leaves the room is on A4.

The palette comes from the subject — Rajasthani indigo, thali brass, and the
reds and ambers WHO growth charts already use for their cut-offs — rather than
from a dashboard template.

---

## Honesty, as a design constraint

Section 15 asks any pitch to cite measured numbers rather than projections. That
shaped more of this page than the visual direction did.

**The Gadchiroli figures are attributed, not borrowed.** Section 9.3 asks for a
before/after "mirroring the Gadchiroli 61→20 framing". This pilot has not run,
so a 61→20 under a Banswara heading would be a fabricated result put in front of
government reviewers. The figures appear as what they are — Gadchiroli's own,
named and sourced — and PoshanNetra's numbers appear separately as a baseline
with no intervention period to compare against.

**The page declares when its own AI output is not real.** Phase 2 defaults to an
offline stand-in provider. The report carries an `ai_is_mock` flag and the
limitations section says so on screen, because a pitch surface presenting mock
nutrition estimates as measurements is exactly what Section 15 forbids.

**Rates are null, not zero, when nothing has been measured.** A rate of zero
reads as "no malnutrition here", which is a very different claim from "nobody
has been measured yet".

**Implausible measurements are excluded and counted.** WHO-flagged readings stay
in the record for audit and out of every figure on this page, and the number
excluded is stated.

**The trend axis is fixed at 0–60%.** A chart scaled to its own data makes two
points of noise look like a trend. Over a six-month baseline with no
intervention, flat is the correct shape and the chart should show that.

---

## Three dependencies removed, and why

The first build used React Three Fiber, drei and Motion. All three are gone, and
each removal came from something breaking rather than from taste:

**React Three Fiber** — its `react-reconciler` read React internals that were
undefined in this combination and threw *during hydration*, which took the whole
page down: every section stuck at opacity zero, no error visible in the markup.
A dependency that can blank a government pitch surface has to earn its place,
and R3F's value is declarative composition of complex scenes. This scene is
three boxes, a grid and an orbit camera. Plain three.js does it in 200 lines with
no reconciler.

**Motion** — rendered its `initial` values as inline styles and then never ran
the animation, leaving the page at opacity zero in a second, different way. CSS
transitions cannot fail like that: the end state is what the stylesheet says, so
if the transition never runs the content is simply there.

**`whileInView` with `once: true`** — never fires when a section is *jumped past*
rather than scrolled through: a reload with a restored scroll position, a deep
link, find-in-page. `lib/useReveal.ts` replaces it and shows content three ways —
intersection, already-past-on-mount, and a hard timeout — so no combination of
circumstances can leave a section invisible.

The result is **93 kB first load**, down from 410 kB, with three.js on its own
lazily-loaded chunk.

---

## The 3D map

Three columns at three real coordinates. Height is stunting prevalence, width is
cohort size — the second variable is why it is 3D at all, since a flat map needs
a separate legend to say the same thing.

Deliberately **not** a shaded district choropleth: we have three centres, not a
district census, and colouring in the whole of Banswara from 90 children would
imply coverage this system does not have.

A flat toggle sits beside it for anyone who finds the 3D gimmicky, the flat map
renders first and upgrades after a WebGL check (locked-down government laptops
and remote-desktop sessions frequently refuse a context), and print drops the
canvas entirely.

## PDF export

The browser's own print-to-PDF over a stylesheet that reflows the page into a
paginated A4 report: letterhead, charts replaced by data tables, link URLs
printed inline, sources and caveats in full. No PDF library and no server
renderer — one layout, not three that can drift apart. Charts hold a room's
attention; tables are what gets annotated in the margin.

---

## Accessibility

- Every chart is `role="img"` with a description naming its key figures, and
  carries the same data as a real table.
- Colour never carries meaning alone: cut-off rules, labels and tables say the
  same thing as the bar colours.
- Body text meets 4.5:1 and secondary text 3:1 against their own surfaces,
  checked per theme rather than inferred.
- `prefers-reduced-motion` collapses every transition, and the 3D scene stops
  its idle rotation.
- Only `opacity` and `transform` animate, so nothing here can shift layout.

## Tests

```bash
npm test
```

24 tests. `tests/stats.test.ts` pins the statistics the page states out loud —
the "2.3% would be" figure is quoted to a government audience and had better be
right. `tests/reveal.test.tsx` exists because of the blank-page bug, and encodes
the rule it taught: content is visible unless something actively hides it.

## Known limitations

- **Auth is Phase 1's dev token**, minted server-side. Phase 6 replaces the
  identity source; `lib/api.ts` is the only file that changes.
- **Read-only.** No drill-down into a centre or a child yet; that is the
  District Dashboard's job (Phase 4, not built).
- **The seeded cohort is synthetic.** Prevalence is tuned toward NFHS-5 figures
  for the tribal belt so the surface is realistic, and must not be quoted.
