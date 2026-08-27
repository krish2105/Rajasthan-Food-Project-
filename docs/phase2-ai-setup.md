# Phase 2 setup — AI pipeline

Everything in Phase 2 runs offline by default. `AI_PROVIDER=mock` is the
shipped setting, it is deterministic, and it spends no quota. You only need the
steps below when you want *real* recognition — and the eval harness will refuse
to report accuracy numbers until you do.

---

## 1. Google AI Studio (Gemini) — vision

<https://aistudio.google.com/apikey> → **Create API key**. Free tier, no card.

```bash
AI_PROVIDER=gemini
GEMINI_API_KEY=<your key>
AI_VISION_MODEL=gemini/gemini-2.0-flash
```

Free-tier limits are per-minute and per-day and they are real. A single-school
pilot photographing ~50 plates a day sits comfortably inside them; anything
beyond one school does not, which Section 15 already flags as a scaling
constraint to state honestly rather than discover.

## 2. Groq — the structured second pass

<https://console.groq.com/keys>. Also free.

```bash
GROQ_API_KEY=<your key>
AI_TEXT_MODEL=groq/llama-3.3-70b-versatile
```

Optional. The Section 6.1 anomaly pass is advisory: it can add plausibility
notes and nothing else. Without a Groq key the pipeline runs and every number is
identical — the pass cannot change a gram estimate or a calorie figure by
design.

## 3. Switching models

Model names go through LiteLLM (Section 4), so swapping provider is an
environment change and touches no business logic:

```bash
AI_VISION_MODEL=gemini/gemini-2.5-flash
```

## 4. Turning inference off entirely

```bash
AI_ENABLED=false
```

Captures are stored and left `sync_status='pending'`, exactly as in Phase 1.
Useful when a free-tier quota is exhausted mid-pilot: the field app keeps
working and the photographs keep accumulating, which is the whole point of
Section 7's ordering.

---

## What actually happens on upload

```
POST /captures
  photo -> Supabase Storage
  row written, sync_status='pending'
  201 RETURNED TO THE FIELD WORKER          <-- nothing below blocks this
  ------------------------------------------------------------------
  background: fetch photo -> Gemini vision -> validate against the closed
              PM POSHAN vocabulary -> recipe + yield -> IFCT lookup by code
              -> row updated to 'synced' (or 'failed', with the reason)
```

A rate limit, an outage or an unreadable reply marks the row `failed` and leaves
the photograph untouched. `POST /captures/{id}/reprocess` picks it back up.

## What the model is and is not asked

**Asked:** which dish, and its cooked weight in grams.

**Never asked:** calories, protein, carbohydrate, or anything about the child.
Section 6.3 draws that line and it is the system's whole accuracy argument —
portion estimation from a photo is genuinely hard and genuinely useful;
nutrition is a lookup table a language model would get plausibly wrong. If the
model volunteered a calorie figure it would be discarded.

**Sent to the provider:** the plate photograph, the dish vocabulary, and the
meal type. No name, no date of birth, no beneficiary ID, no AWC code — Section
11's guarantee holds by construction, because the prompt is built only from
those three things. There is a test for it.

---

## Running the eval harness

```bash
cd backend && uv run python -m app.eval
```

With an empty golden set it prints `unvalidated` for every metric and exits 0.
That is the honest state today, not a failure: Section 15 says no labelled
dataset exists for tribal-Rajasthan dishes and one must be built during the
pilot.

Under `AI_PROVIDER=mock` it additionally refuses to report anything at all,
because the offline provider validates plumbing rather than recognition.

### Building the golden set (pilot week 1)

1. Put plate photographs in `backend/app/eval/golden/images/`.
2. `uv run python -m app.eval.label app/eval/golden/images/plate_001.jpg`
3. `uv run python -m app.eval`

Section 6.5 wants ~200–300 labelled photographs. Two things matter more than
the count:

- **Weigh the plates.** The portion target (MAE ≤ 25 g) is only meaningful
  against a scale. The labeller asks, and the harness reports weighed and
  eyeballed subsets separately rather than mixing them.
- **No child in any photograph.** Section 12 is absolute. If a child is visible,
  delete the image — do not crop it.

---

## The calibration session is not optional

`app/nutrition/recipes.py` converts cooked dishes to raw ingredients before
looking anything up in IFCT, because IFCT is a **raw** food table and a camera
sees cooked food. Skipping that step overstates a plate of rice by about three
times, always in the direction of making an underfed child look adequately fed.

The conversion needs two numbers per dish: the standard cooked serving weight
and the yield factor. Raw grain, pulse, vegetable and oil quantities are
anchored to PM POSHAN's per-child norms and are as solid as the scheme itself.
The serving weights and yields are standard kitchen values — a documented,
adjustable prior, and **the least certain numbers in this system**.

Section 14 step 3 calls for a calibration session with dietitian-weighed
reference plates before any accuracy figure is quoted. Until it happens every
dish is marked `uncalibrated`, every nutrition result carries a warning, and the
eval harness caveats the calorie metric explicitly. A systematic yield error
moves ground truth and prediction together and would not show up in MAPE at all,
so saying so is the only defence.

Sanity check available today: a standard PM POSHAN plate (150 g rice, 120 g dal,
75 g sabzi, one banana) totals **475 kcal / 11.8 g protein** through this table,
against the scheme's own published primary-stage target of 450 kcal / 12 g. The
recipes reproduce the norm they were anchored to. That is reassuring, not
calibration.

---

## Attribution

Nutrition values come from the **Indian Food Composition Tables 2017,
ICMR-National Institute of Nutrition**. Any deck, report or screen that shows
these numbers must credit them. Section 4 chose IFCT over USDA precisely because
using India's own official dataset is a credibility signal to a reviewer who
knows the domain — which only works if the credit is visible.
