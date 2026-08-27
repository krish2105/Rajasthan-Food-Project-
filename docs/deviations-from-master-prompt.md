# Deviations from the master prompt

`poshannetra-ai-master-prompt.md` says its sections are decisions already made,
to be implemented rather than re-litigated. These are the five places Phase 1
departs from it anyway, each with the reason. Nothing here is a preference — one
is a clinical-correctness fix, the rest are structural gaps that would have cost
a migration later.

---

## D1 — `growth_entries` gains `baz_score` and `standard_used`

**Section 5 as written.** Every child gets `whz_score` (weight-for-height).

**The problem.** The WHO Child Growth Standards cover **0–60 months only**.
Above five years the applicable reference is the **WHO 2007 Growth Reference**,
in which:

- weight-for-height **does not exist** — BMI-for-age replaces it;
- weight-for-age is defined **only to 120 months** (10 years), because after
  puberty begins weight-for-age cannot separate height from build.

Section 1 puts Ashram school children (6–14y) in the pilot alongside Anganwadi
children. Scoring a nine-year-old against the 0–60m tables produces a number
that is clinically meaningless but indistinguishable, in a database column, from
a valid one. Section 6.4 forbids putting a probabilistic model in this path
precisely because the classification must be defensible under audit; a silently
wrong deterministic number fails that same test.

**What we did.**

- Added `baz_score` (BMI-for-age z) and `standard_used`
  (`who_2006_0_60m` | `who_2007_5_19y`).
- `app/growth/assess.py` selects the reference from age at measurement.
- Indices WHO does not define come back `NULL` with an explanatory note on the
  API response, rather than a fabricated value.
- A `CHECK` constraint enforces the invariant in the schema itself: a
  `who_2006_0_60m` row can never carry `baz_score`, and a `who_2007_5_19y` row
  can never carry `whz_score`.

**A finding that widened the case.** Testing showed this is not only an Ashram
school concern. ICDS covers 0–6 years, but the WHO 2006 tables stop at 61
months — so roughly the oldest sixth of *any* Anganwadi cohort already needs the
2007 reference. A pilot that never touched a school would still have needed D1.
See `tests/test_seed.py::test_anganwadi_children_straddle_both_references_at_61_months`.

---

## D2 — `growth_entries` gains `classification_detail`

**Section 5 as written.** One `classification TEXT` column.

**The problem.** A child can be stunted *and* underweight *and* wasted at once —
in the Banswara belt that is the common case, not an edge case. One column
cannot say so, and the supervisor planning follow-up needs all three.

**What we did.** Kept `classification` as the single most-severe label in
Section 5's five-value vocabulary, so a district officer still reads a category
Poshan Tracker already displays. Added `classification_detail` (JSONB) carrying
the precise WHO label per index. Acute malnutrition outranks chronic in the
roll-up: SAM is a referral today, stunting is a months-long trend.

The detail field also preserves a distinction the coarse vocabulary loses. Under
five, acute malnutrition is *severe/moderate acute malnutrition* measured by
weight-for-height. From five, it is *severe thinness / thinness* measured by
BMI-for-age. Different WHO terms, different measurements — both roll up to
SAM/MAM for display, and both survive intact in the detail.

---

## D3 — new `awcs` master table

**Section 5 as written.** `awc_code` is a bare string in four tables with no
master record.

**The problem.** Nowhere to put the centre's name, its type (which decides the
menu cycle and the likely WHO reference), or its coordinates. Phases 4–5 need
all three, and duplicating them onto every beneficiary row is not a serious
option.

**What we did.** Added `awcs`, with bilingual name/district/block, `centre_type`,
and real lat/lon for the Phase 5 district map. `beneficiaries`, `growth_entries`
and `plate_captures` keep denormalised `awc_code`/`district` columns so RLS
scoping stays a column comparison rather than a subquery on every row.

---

## D4 — new `menu_items` table

**Section 5 as written.** `prescribed_items` / `detected_items` are JSONB.

**What we did.** Left them as JSONB, but they now reference stable codes from a
bilingual `menu_items` table instead of embedding raw English strings a
Hindi-first UI cannot render. `ifct_code` is present and nullable, ready for the
IFCT 2017 lookup in Phase 2.

---

## D5 — bilingual columns throughout

**Not in Section 5 at all**, but required by Section 9.1's Hindi-first mandate.

**What we did.** `name_en` / `name_hi` on every displayable reference entity, and
API responses that always carry both languages regardless of `?lang=`. The Field
PWA is offline-first (Section 7), so a language toggle must not require a
network round-trip. `?lang=` and `Accept-Language` set a *preference hint*; they
never remove a language from the payload.

Beneficiary `name` stays a single field — proper nouns, stored in Devanagari as
entered, not translated.

Error responses carry `title_en` and `title_hi` for the same reason: a
Hindi-first client should never fall back to English because it met an
unrecognised error code offline.

---

## D6 — nutrition goes through a recipe and yield layer, not Section 6.3's formula

**Section 6.3 as written.** `estimated_grams x (IFCT per-100g value / 100)`.

**The problem.** IFCT 2017 is a table of **raw** foods — 534 of its 542 entries,
the exceptions being six egg preparations and parboiled rice. A camera
photographs **cooked** food:

| | IFCT (raw) | actual cooked |
|---|---|---|
| Rice | 356 kcal/100 g | ~130 |
| Dal | 329 kcal/100 g | ~110 |
| Atta | 320 kcal/100 g | ~300 (roti) |

Applied literally the formula charges cooked weight at dry-ingredient density.
For 150 g of rice on a plate it reports ~535 kcal against a true ~207 — an
overstatement of about 3x. The direction matters more than the magnitude: the
error always makes an underfed child look adequately fed, which is the worst way
for this system to be wrong.

**What we did.** `app/nutrition/recipes.py` maps each PM POSHAN dish to its raw
ingredients and a cooked serving weight; IFCT is then looked up on the raw
ingredients, which is what IFCT is for. Raw grain, pulse, vegetable and oil
quantities are anchored to PM POSHAN's per-child norms (100 g grains / 20 g
pulses / 50 g vegetables / 5 g oil at primary stage), so the numbers trace to a
government standard rather than to a guess.

**Independent check.** A standard plate totals 475 kcal / 11.8 g protein through
this table against PM POSHAN's own published target of 450 kcal / 12 g. The
recipes reproduce the norm they were anchored to.

**Honest caveat.** The serving weights and yield factors are standard kitchen
values, not measurements — the least certain numbers in the system. Every dish
is marked `uncalibrated`, every result warns, and the eval harness caveats the
calorie metric until the Section 14 step 3 calibration session happens.

---

## D7 — the vision model gets a closed dish vocabulary, not free-text IFCT matching

**Section 6.2 as written.** Constrain `food_name` to the IFCT vocabulary, with a
fuzzy-match fallback (rapidfuzz) for near misses.

**The problem.** Fuzzy-matching free text across IFCT's 542 entries returns
confident nonsense:

| query | top match | score |
|---|---|---|
| `dal` | Ragi | 90 |
| `kela` | Plantain, green | 100 |
| `aalu` | Yam, ordinary | 100 |
| `rice` | Rice flakes | 90 |

These are not scorer artefacts — verified across WRatio, QRatio,
token_sort_ratio and ratio, all four agree. IFCT genuinely lists "Kela" as a
local name for plantain and "Alu" for yam, so the ambiguity is in the data and
no threshold separates it. Section 6.2 anticipated silent lookup *failure*; the
real behaviour is worse, because a wrong match produces a confident calorie
figure for a food that was never on the plate.

**What we did.** The model is handed the ~10-dish PM POSHAN vocabulary as a JSON
schema enum, and fuzzy matching happens against ~76 curated aliases (English,
romanised Hindi and Devanagari) rather than 542 ambiguous food names. Each dish
names its IFCT codes **explicitly**; `ifct.get(code)` is the only path the
pipeline uses. A detected food outside the vocabulary is reported as
"detected but not costed" rather than approximated.

`ifct.find()` was removed and replaced by `ifct.search()`, which returns ranked
*candidates* and is documented as unusable for nutrition. A test pins the three
wrong matches above so nobody reintroduces the convenience.

---

## Not a deviation, but worth recording

**RLS is enforced in Postgres, not only in Python.** Section 11 asks for
cross-school access to be structurally impossible rather than merely blocked by
the UI. That required the backend to stop connecting as the table owner on
request paths — an owner bypasses policies silently, so policies on an
owner connection are decoration. `app/db/session.py` switches to Supabase's
non-owner `authenticated` role per transaction. `tests/test_rls.py` proves the
isolation at the database, with no FastAPI in the picture.

**`app.claim()` fails closed.** The obvious one-line SQL version casts the
claims setting straight to `jsonb`. With no claims stamped, `current_setting`
returns `''`, and `''::jsonb` raises — turning a request that should quietly
return nothing into a 500. A 500 that differs from an empty 200 is itself a
signal about which rows exist, so the cast is guarded and every failure mode
returns NULL. Found by testing, not by review.

**WHO implausible-value flagging was added to the growth path.** Not in the
master prompt, but Section 7 names data-entry burden on frontline workers as
this system's most likely real-world failure point, and Section 6.4 asks the
classification path to be defensible. Found during live verification: entering
88 cm for a six-month-old produced HAZ = +9.28 and stored it as a valid record.

We follow WHO Anthro's own handling rather than inventing one. Z-scores outside
WHO's plausible bounds (HAZ +/-6, WAZ -6/+5, WHZ and BAZ +/-5) are flagged in a
`data_quality_flags` column, the raw measurement and z-score are retained for
audit, and the flagged index is **excluded from the classification** so a
transposed digit cannot manufacture a SAM case or mask a real one. The
measurement is not rejected -- a genuinely extreme child exists, and refusing to
record them would be the worse failure. The bounds sit well outside the -3 SD
cut-offs, so no real classification boundary is ever swallowed; a test asserts
that a genuine SAM case at -3.4 SD passes through unflagged.

**The background inference task uses the owner connection.** Migration 0002
grants the `authenticated` role no UPDATE on any table, deliberately. The Phase 2
task that writes AI results back is a server-side process updating a row it was
handed, not a user acting on someone's data, so it uses `admin_session` and
touches only the single capture id it was given.

**`POST /captures/{id}/reprocess` is not in Section 8's route list.** It was
added because Section 7 requires the pipeline to be retry-safe, and free-tier
rate limits are a routine rather than exceptional condition. Without a retry
path, one busy afternoon would permanently strand a day's evidence.

**No UPDATE or DELETE policy exists on any table.** For a system of record about
children, corrections should be append-only amendments with an audit trail
(Phase 6+), not silent in-place edits. The absence is deliberate; the test suite
asserts it.
