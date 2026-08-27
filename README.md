# PoshanNetra AI — पोषण नेत्र

AI-assisted meal monitoring for Anganwadi centres and Ashram schools in the
Banswara–Dungarpur tribal belt of Rajasthan. Full specification:
[`poshannetra-ai-master-prompt.md`](poshannetra-ai-master-prompt.md).

> **Phases 1–3 of 7 are complete.** Data model and FastAPI skeleton (Section 16
> step 1); AI pipeline and evaluation harness (step 2); the offline-first Field
> Capture PWA (step 3). Phases 4–7 have not been started.

---

## What exists today

| | Status |
|---|---|
| Data model — 7 tables, Section 5 + deviations D1–D5 | done |
| WHO implausible-value flagging on data entry | done |
| WHO growth classification — deterministic, 14 vendored reference tables | done, proven |
| Row-level security — Section 10 scoping enforced in Postgres | done, proven |
| FastAPI skeleton — 13 routes, bilingual contracts | done |
| Seeded sample data — 3 centres, 120 children, 6 months | done |
| IFCT 2017 nutrition — 542 foods, vendored with provenance | done |
| Cooked→raw recipe layer anchored to PM POSHAN norms | done |
| Vision pipeline (Gemini/Groq via LiteLLM) + offline mock | done |
| Menu compliance — the Gadchiroli-precedent feature | done |
| Evaluation harness — Section 6.5 metrics | done, reports `unvalidated` |
| Field Capture PWA — offline-first, Hindi-first, 4 themes | done |
| Test suite | 369 backend + 119 PWA passing |

### Not in these phases, by design

District Dashboard (Phase 4) · State Admin pitch view (Phase 5) · phone-OTP auth
(Phase 6) · deployment (Phase 7).

The AI pipeline defaults to `AI_PROVIDER=mock` — deterministic, offline, and it
spends no free-tier quota. Real recognition needs a Gemini key; see
[docs/phase2-ai-setup.md](docs/phase2-ai-setup.md).

---

## The four things worth reviewing first

**1. Growth classification is arithmetic, not a model.**
Section 6.4 is categorical that no LLM may sit in this path. `app/growth/lms.py`
implements the WHO LMS method over 14 reference tables vendored from who.int,
each CSV carrying its source URL, retrieval date and source SHA-256.

The claim that it is correct is checkable rather than asserted. The vendored
tables keep WHO's own published ±2SD/±3SD cut-off columns, which the runtime
never reads; `tests/test_who_lms.py` regenerates them from L/M/S and asserts an
exact match across **all 10,624 rows**. It also pins WHO's ±3SD flat-tail
correction — the detail naive implementations skip, which makes them disagree
with WHO Anthro precisely in the severe-malnutrition range this pilot exists to
find.

**2. Access scoping is enforced by Postgres, not by route handlers.**
Not one query in `app/api/routes/` contains a `WHERE awc_code = ...` clause. A
handler cannot leak another school's children by forgetting a filter, because
the filter is not in the handler — it is a policy the planner applies to every
statement (`alembic/versions/0002_rls_policies.py`). `tests/test_rls.py` proves
the isolation against the database directly, with FastAPI out of the picture.

**3. Nutrition is arithmetic, and the recipe layer is why it is right.**
IFCT 2017 is a table of *raw* foods; a camera sees *cooked* food. Section 6.3's
formula, applied literally, reports 150 g of rice at ~535 kcal instead of ~207 —
always in the direction that makes an underfed child look adequately fed.
`app/nutrition/recipes.py` converts each dish to raw ingredients using PM POSHAN's
own per-child norms before any IFCT lookup, so every calorie traces to either an
ICMR-NIN published value or a government standard. A standard plate totals
475 kcal / 11.8 g protein against PM POSHAN's published 450 / 12.

**4. The eval harness refuses to flatter the system.**
With no labelled photographs it reports `unvalidated`, never `0%` and never a
default. Under the mock provider it refuses to report accuracy at all. Section 15
asks any pitch to cite measured numbers rather than projections; this is the
thing that makes that possible to comply with.

See [`docs/deviations-from-master-prompt.md`](docs/deviations-from-master-prompt.md)
for the seven documented departures from the spec — the clinical fix (D1) that
stops school-age children being scored against an under-five standard, the
cooked-versus-raw fix (D6), and the closed vocabulary (D7) that replaced
free-text IFCT matching after it turned out to map "dal" to *Ragi* and "kela" to
*plantain* with perfect confidence.

---

## Running it

**Prerequisites.** Python 3.12+, [uv](https://docs.astral.sh/uv/), and a
Postgres — either a Supabase project
([setup guide](docs/phase1-supabase-setup.md), ~10 minutes) or a local Postgres
for development.

```bash
cd backend && cp .env.example .env    # then fill in your own values
```
```bash
cd backend && uv sync
```
```bash
cd backend && uv run alembic upgrade head
```
```bash
cd backend && uv run python -m app.seed
```
```bash
cd backend && uv run uvicorn app.main:app --reload
```

Interactive API docs: <http://localhost:8000/docs>

### Tests

The suite runs against a real Postgres, never SQLite — the security model *is*
row-level security, and a database without RLS could not exercise it. It creates
and migrates its own `poshannetra_pytest` database.

```bash
cd backend && uv run pytest -v
```

Point it elsewhere with `TEST_DATABASE_URL`. If no database is reachable the
suite skips loudly rather than passing with the security tests unrun.

---

## Verifying it works

```bash
curl -s localhost:8000/health/db
```
`rls_policies` must be greater than zero. If it is ever `0`, RLS has silently
stopped protecting anything.

```bash
curl -s -X POST localhost:8000/auth/dev/token -H 'content-type: application/json' -d '{"phone":"9999900001"}'
```

Then, with that token as `$TOKEN`:

```bash
curl -s localhost:8000/beneficiaries -H "Authorization: Bearer $TOKEN" | head -c 400
```

**The isolation proof.** Repeat with the Dungarpur worker (`9999900003`). The two
lists must be disjoint. Repeat with the state admin (`9999900020`) to see all
120. Requesting another centre explicitly (`?awc_code=RJ-DGP-SGW-003`) as a
Banswara worker returns an empty list, not that centre's children — the filter
narrows within scope and can never widen it.

**Deviation D1 in one command.** Record a measurement for a toddler and for a
school-age child via `POST /growth`:

- under 61 months → `standard_used: who_2006_0_60m`, `whz_score` populated,
  `baz_score` null
- over 61 months → `standard_used: who_2007_5_19y`, `whz_score` null,
  `baz_score` populated, and a `notes` entry explaining that weight-for-height
  is undefined in the WHO 2007 reference

An out-of-scope child returns **404, not 403** — a distinguishable 403 would
confirm that a given child exists at some other school.

**Data-quality flagging.** Enter a plainly wrong measurement — 88 cm for a
six-month-old — and the response comes back with `data_quality_flags: ["haz"]`,
the stunting label suppressed, and a note explaining that the z-score is outside
WHO's plausible range. The raw value is still stored for audit; it simply does
not get to drive a classification. This follows WHO Anthro's own handling, and
exists because Section 7 names data-entry burden as this system's most likely
real-world failure point.

---

## Seeded data

`python -m app.seed` writes 3 centres, 120 children, 720 growth entries across 6
months, ~5,200 plate captures over 60 days, and 156 menu-compliance rows with
~20% flagged.

All of it is synthetic. Section 14 step 1 is explicit that no real child's data
goes near this system before consent and legal sign-off, and Section 12 governs
what may be collected even then — there is no child photograph anywhere in the
schema, and no endpoint that could store one.

Measurements are generated by **inverting** the same WHO tables that later score
them: each child gets a target z-score, and height and weight are derived from
the L/M/S parameters. Two consequences, both deliberate — every stored z-score
is reproducible by running `assess()` on the stored height and weight, so a
reviewer can audit any row rather than trusting it; and prevalence is a
consequence of the targets rather than a fiction, so the seed *reports* its
achieved distribution instead of promising one. The run prints stunting,
wasting and underweight prevalence, tuned toward NFHS-5 figures for the tribal
belt.

The placeholder plate images are drawings, watermarked as such. Per Section 6.5
they must never be used to evaluate the Phase 2 vision pipeline — no labelled
dataset for tribal-Rajasthan dishes exists yet, and scoring a model against
drawings would manufacture exactly the false accuracy number that section warns
against.

---

## Layout

```
apps/field-pwa/   the worker's app  ← Section 9.1, see its own README
backend/app/
├── growth/        WHO LMS math + vendored reference tables  ← Section 6.4
├── db/            models, migrations, RLS-scoped sessions   ← Sections 5, 11
├── api/routes/    13 endpoints                              ← Section 8
├── core/          JWT + Principal (one identity, three consumers)
├── storage/       Supabase Storage, token-scoped
└── seed/          synthetic pilot data
```

`apps/` holds the frontends; the District Dashboard and State Admin view join
it in Phases 4–5.

**The Field Capture PWA is deliberately not premium** — Section 9.1 names it as
the one surface where animation libraries and 3D are the wrong choice, because
it runs on a basic Android every day in a low-connectivity area. No UI
framework, no animation library, no icon package: 63 KB gzipped. It is
Hindi-first, works fully offline, and ships four themes including a
high-contrast sunlight mode for outdoor use. See
[apps/field-pwa/README.md](apps/field-pwa/README.md).

---

## Honest limitations at this phase

Section 15 lists the product's limitations. These are Phase 1's own:

- **Raj-Poshan / Poshan Tracker integration is a proposed data contract, not a
  confirmed API.** `poshan_tracker_id` is a nullable external reference built
  from publicly documented field categories. Section 2's caveat stands: it needs
  validating with NIC/WCD before the pilot goes live.
- **Authentication is a development stub.** `POST /auth/dev/token` mints a token
  for any known phone number with no verification, and returns 404 when
  `APP_ENV=production`. The *scope* model is real and tested; only the identity
  source is stubbed, and Phase 6 replaces it without touching the policies.
- **Storage RLS depends on the legacy HS256 JWT secret** being available on the
  Supabase project. Where it is not, `STORAGE_MODE=service` falls back to
  application-level scope checks for Storage only. Postgres RLS is unaffected.
  Which mode you are on is a fact worth stating rather than glossing.
- **District officials are not scoped by district in Storage policies**, because
  an object path carries no district. The API never hands them a path it has not
  already read through an RLS-scoped query, so Postgres is the real constraint.
  Closing it properly is a Phase 6 decision.
- **The seed's prevalence figures are synthetic** and describe no real
  population. They exist to make Phases 4–5 renderable, and must never be quoted
  as pilot findings.
