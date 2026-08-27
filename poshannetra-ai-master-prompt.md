# PoshanNetra AI — Claude Code Master Build Prompt

**पोषण नेत्र — "The Eye of Nutrition"**

> Naming rationale: "Poshan" is the exact term Rajasthan/GoI already use across Poshan Tracker, Mission Poshan 2.0, and Raj-Poshan — a reviewer recognizes the domain instantly. "Netra" (Sanskrit, eye/vision) names what the AI actually does: it *sees* the plate. This is not an Arabic-brand-portfolio project; it's a government pitch artifact, and the name should read as native to that context.

---

## How to use this document

Paste this entire file into Claude Code as the system/project prompt. It is written as a CTO-level build spec — every section is a decision that's already been made, with the reasoning attached, so Claude Code should implement rather than re-litigate architecture. Where a decision genuinely depends on ground-truth data we don't have yet (real Raj-Poshan schema, real device conditions in Banswara), that is flagged explicitly rather than guessed at.

**Model routing for this build** (per your established convention):
- **Opus/Fable** → Section 6 (AI/ML pipeline correctness, WHO growth-standard math), Section 3 (architecture), Section 12 (privacy/child-data design)
- **Sonnet** → Sections 8–10 (API, PWA, dashboards — implementation-heavy CRUD/UI work)
- **Haiku** → READMEs, API docs, the pilot rollout deck copy

**Zero-paid-API constraint is absolute** — every AI call must run on a free tier (Gemini free tier, Groq free tier) or deterministic local code. No OpenAI, no paid Anthropic API calls in the product itself (Claude Code is your build tool, not a runtime dependency).

---

## 1. Project Overview & Problem Statement

**What it is**: An AI-assisted meal-monitoring add-on for Anganwadi centres and Ashram (tribal) schools in Rajasthan, starting with a single-school pilot in the Banswara–Dungarpur belt. A worker photographs a child's plate before/after a meal; the system estimates food quantity, calories, protein, and carbohydrates, checks the plate against the day's prescribed menu, and logs the result against the child's existing Poshan Tracker/Raj-Poshan beneficiary record. Growth data (height/weight, already collected under ICDS) is classified against WHO Child Growth Standards to flag wasting/stunting/underweight — same output categories Poshan Tracker already uses, so the numbers a district officer sees are numbers they already know how to read.

**What problem this actually solves** (from the Gadchiroli precedent): not "malnutrition" in the abstract, but two specific, auditable failures — (a) menu non-compliance (prescribed 5 items, 4 served) and (b) food-quality issues (watery dal, under-ripe/over-ripe fruit) that are invisible to manual registers but visible in a photo, cross-checked against a rule.

**Explicit non-goal**: this system does not diagnose malnutrition. It classifies growth data against an established clinical standard (WHO Growth Standards / IAP charts) using deterministic math — never an LLM guess. See Section 6.4 for why this boundary is non-negotiable.

---

## 2. Government Alignment & Compliance Mapping

Design posture: **add-on module**, not a competing system. Three integration surfaces:

| Existing system | What it owns | What PoshanNetra adds |
|---|---|---|
| **Raj-Poshan** (NIC-built, Rajasthan ICDS) | Beneficiary registry, AWC master data, growth entries | Plate-level photo evidence + automated macro estimate, tagged to the same beneficiary ID |
| **Poshan Tracker** (national, MoWCD) | Growth monitoring, service delivery tracking, 24-language support | Menu-compliance flagging that Poshan Tracker doesn't currently do |
| **PM POSHAN** (school meal scheme) | Prescribed menu, meal frequency | Automated menu-vs-served-plate comparison |

**Honest caveat — flag this to the reader, don't hide it**: the exact Raj-Poshan/Poshan Tracker field schema and any API access require going through NIC/WCD, which this document cannot access. Section 5 below is a best-effort schema built from Poshan Tracker's *publicly documented* field categories (beneficiary ID, AWC code, height/weight, age, gender, growth classification, supplementary nutrition Y/N). Treat it as a draft data contract to validate with an actual WCD/NIC contact before the pilot goes live — not as confirmed integration.

---

## 3. System Architecture

Three applications, one backend, one database.

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  Field Capture PWA   │     │  District Dashboard  │     │  State Admin View    │
│  (Anganwadi/school    │     │  (Collector's office/ │     │  (DoIT&C/WCD/pitch    │
│  worker, offline-first)│     │  Block officer)       │     │  demo, polished)      │
└──────────┬───────────┘     └──────────┬───────────┘     └──────────┬───────────┘
           │  sync queue (background)    │  live queries              │  live + export
           └──────────────┬───────────────┴──────────────┬────────────┘
                           │                               │
                    ┌──────▼───────────────────────────────▼──────┐
                    │           FastAPI Backend (single service)   │
                    │  /capture  /beneficiaries  /compliance        │
                    │  /growth  /reports  /auth                     │
                    └──────┬─────────────────────┬───────────────┘
                           │                       │
              ┌────────────▼──────────┐  ┌────────▼─────────────┐
              │  AI Pipeline (LiteLLM) │  │  PostgreSQL (Supabase │
              │  Gemini free-tier vision│  │  free tier) + Storage │
              │  Groq free-tier text    │  │  for plate photos     │
              └────────────────────────┘  └────────────────────────┘
```

**Why one backend, three frontends** (not three separate services): at MVP/pilot scale (one school, a few hundred students) a split microservice architecture is over-engineering that will slow down the build without buying you anything — a senior call here is to *not* build for a scale you don't have yet. The API is designed with clean role-based access (Section 10) so splitting later, if the pilot expands statewide, is a refactor, not a rewrite.

---

## 4. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI (Python 3.12) | Matches your existing stack; async-native for image upload handling |
| Database | PostgreSQL via Supabase free tier | Free tier covers pilot scale; built-in object storage for plate photos in the same project |
| Vision AI | Gemini 2.0/2.5 Flash, free tier (Google AI Studio) | Best free-tier multimodal model for zero-shot food recognition + portion estimation as of this build; swappable via LiteLLM if a better free option appears |
| Fast text/reasoning | Groq (Llama models), free tier | Structured JSON extraction, compliance-flag reasoning, district-report summarization |
| Model routing | LiteLLM | Single abstraction so Gemini/Groq/a future model swap doesn't touch business logic |
| Nutrition database | **IFCT 2017** (Indian Food Composition Tables, National Institute of Nutrition) | This is the correct authoritative source — not USDA. Using India's own official nutrition dataset is itself a credibility signal to reviewers who know the domain |
| Growth standard | WHO Child Growth Standards (z-scores: weight-for-age, height-for-age, weight-for-height) — implemented as deterministic code, not model output | Clinical correctness; see 6.4 |
| Field PWA | Vite + React, installable PWA, Workbox service worker, IndexedDB queue | Needs to work with intermittent connectivity on basic Android phones |
| District/Admin frontends | Next.js 14 | Consistent with your existing stack; the Admin view can carry your usual Motion v12/GSAP polish since it's the pitch-facing surface — the Field PWA deliberately does **not**, see 9.1 |
| Auth | Phone-number OTP (via free-tier SMS provider, e.g. MSG91 free credits, or a stubbed OTP for demo) + JWT | Matches how field-worker apps in India are actually used; email/password is the wrong pattern for this user |
| Hosting (pilot/demo) | Vercel (frontends) + Render/Railway free tier (FastAPI) + Supabase free tier (DB + storage) | Zero-cost, matches the zero-paid-API ethos extended to infra |

---

## 5. Data Model (draft — validate against real Raj-Poshan schema before pilot)

```sql
-- Beneficiary: mirrors Poshan Tracker's known field categories
CREATE TABLE beneficiaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    poshan_tracker_id TEXT UNIQUE,        -- external ID, nullable until confirmed integration
    awc_code TEXT NOT NULL,               -- Anganwadi/school code
    district TEXT NOT NULL,               -- e.g. 'Banswara'
    block TEXT NOT NULL,                  -- e.g. 'Ghatol'
    name TEXT NOT NULL,
    dob DATE NOT NULL,
    gender TEXT NOT NULL CHECK (gender IN ('M','F','O')),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Growth entries: existing ICDS data type, WHO classification computed, never AI-guessed
CREATE TABLE growth_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    beneficiary_id UUID REFERENCES beneficiaries(id),
    recorded_at DATE NOT NULL,
    height_cm NUMERIC(5,2) NOT NULL,
    weight_kg NUMERIC(5,2) NOT NULL,
    waz_score NUMERIC(4,2),               -- weight-for-age z-score
    haz_score NUMERIC(4,2),               -- height-for-age z-score
    whz_score NUMERIC(4,2),               -- weight-for-height z-score
    classification TEXT,                  -- 'normal' | 'MAM' | 'SAM' | 'stunted' | 'underweight'
    recorded_by UUID REFERENCES field_workers(id)
);

-- Plate captures: the new thing this system adds
CREATE TABLE plate_captures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    beneficiary_id UUID REFERENCES beneficiaries(id),
    photo_url TEXT NOT NULL,              -- Supabase Storage path
    meal_type TEXT NOT NULL,              -- 'breakfast' | 'lunch' | 'thr' (take-home ration)
    captured_at TIMESTAMPTZ NOT NULL,
    sync_status TEXT DEFAULT 'pending',   -- 'pending' | 'synced' | 'failed' — offline queue state
    ai_food_items JSONB,                  -- [{item, confidence, est_grams}]
    ai_calories NUMERIC(6,1),
    ai_protein_g NUMERIC(5,1),
    ai_carbs_g NUMERIC(5,1),
    ai_model_version TEXT,                -- for eval/audit trail
    field_worker_id UUID REFERENCES field_workers(id)
);

-- Menu compliance: the Gadchiroli-precedent feature
CREATE TABLE menu_compliance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    awc_code TEXT NOT NULL,
    date DATE NOT NULL,
    prescribed_items JSONB NOT NULL,      -- from PM POSHAN menu cycle
    detected_items JSONB NOT NULL,        -- aggregated from plate_captures that day
    compliance_pct NUMERIC(5,2),
    flagged BOOLEAN DEFAULT false,
    flag_reason TEXT
);

CREATE TABLE field_workers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('field_worker','district_official','state_admin')),
    awc_code TEXT,                        -- null for district/state roles
    district TEXT
);
```

---

## 6. AI/ML Pipeline

### 6.1 Flow
```
Plate photo → Gemini vision call → food item list + est. quantity (grams)
           → IFCT 2017 lookup per item → calorie/protein/carb sum
           → Groq structured-output pass → confidence flags + anomaly notes
           → compare against day's prescribed menu → compliance_pct
```

### 6.2 Vision prompt design (Gemini)
Structured output, not free text — force JSON schema via response format, e.g.:
```json
{
  "items": [
    {"food_name": "dal (lentils)", "estimated_grams": 120, "confidence": 0.82},
    {"food_name": "roti", "count": 2, "estimated_grams": 80, "confidence": 0.91}
  ],
  "plate_quality_flags": ["watery_appearance", "portion_below_prescribed"]
}
```
`food_name` values should be constrained (via prompt + a validation step) to the IFCT 2017 item vocabulary, or the nutrition lookup in the next step fails silently. Build a fuzzy-match fallback (e.g. rapidfuzz against the IFCT item list) for near-miss names.

### 6.3 Nutrition calculation
Deterministic lookup, not model output: `estimated_grams × (IFCT per-100g value / 100)` for each of calories/protein/carbs, summed across items. This is the single most important accuracy-vs-hype decision in the whole system — the *AI's* job is portion estimation from a photo (genuinely hard, genuinely useful); the *nutrition math* is a lookup table, and should never be delegated to a language model, which will happily hallucinate plausible-sounding wrong numbers.

### 6.4 Growth classification — deterministic, not AI (non-negotiable)
Implement WHO Child Growth Standards z-score calculation (LMS method) as a pure function using the published WHO reference tables — the `pygrowup` or equivalent WHO Anthro reference tables/logic, vendored into the codebase, not called via any LLM. Output classification (`SAM`/`MAM`/`normal`/`stunted`/`underweight`) is a threshold lookup on the z-score, matching the same categories Poshan Tracker already uses. **No LLM in this path, ever** — a child's malnutrition classification is a clinical/statistical fact, and putting a probabilistic model in that loop is both a correctness risk and, frankly, indefensible if anyone audits the system.

### 6.5 Evaluation harness
This replaces your usual RAGAS harness (no RAG component here) with metrics that actually match this pipeline:

| Metric | Target | How measured |
|---|---|---|
| Food item recognition (top-3 accuracy) | ≥80% on pilot-labeled set | Manual labeling of ~200–300 plate photos collected during pilot week 1 (no existing labeled dataset for tribal-Rajasthan dishes exists — this has to be bootstrapped, flag this honestly in the pitch) |
| Portion/quantity estimate | MAE ≤ 25g per item | Compare against dietitian-weighed reference plates (a one-time calibration session, ideally with VAAGDHARA's field staff) |
| Calorie estimate | MAE ≤ 15% of true value | Derived from the above two |
| Menu compliance flag | Precision ≥ 0.85, Recall ≥ 0.85 | Manually cross-check flagged days against actual kitchen registers for 2 weeks |
| WHO z-score classification | 100% match against reference WHO Anthro output | Unit tests against WHO's own published reference tables — this must be exact, it's math, not ML |

Build this harness *before* the pilot, not after — the honest-limitations section of any pitch deck should cite these numbers, not vibes.

---

## 7. Offline-First & Low-Connectivity Design

This is the single most likely real-world failure point (Poshan Tracker's own documented weakness is exactly this: device/connectivity/data-entry burden on frontline workers). Design decisions:

- **Capture works fully offline.** Photo + metadata (meal type, timestamp, beneficiary selection from a locally cached list) is written to IndexedDB immediately. No network call blocks the capture flow.
- **AI inference happens server-side, not on-device**, but is *decoupled from capture* — a background sync (Service Worker Background Sync API, with a manual "sync now" fallback button since Background Sync isn't reliable on all Android WebViews) uploads queued captures whenever connectivity appears. The worker never waits for an AI result to move to the next plate.
- **Beneficiary list is cached locally** on first login/sync, so photo-to-child matching works offline (dropdown from cached list, not a live search).
- **Sync status is visible**, not silent — a simple badge showing "12 pending, 3 synced" so a worker isn't left wondering if their day's work was recorded.
- **Graceful AI failure**: if Gemini/Groq calls fail (rate limit on free tier, outage), the photo and raw metadata are still saved and queued for reprocessing — the pipeline is retry-safe, not capture-blocking.

---

## 8. Backend API Design (FastAPI)

Core routes — implement with Pydantic schemas, async handlers, role-checked via dependency injection:

```
POST   /auth/otp/request          {phone}
POST   /auth/otp/verify           {phone, otp} → JWT

GET    /beneficiaries?awc_code=   (field_worker, district_official)
POST   /captures                  (field_worker) — accepts photo + metadata, queues AI job
GET    /captures/{id}             (poll for AI result, since inference is async)

GET    /compliance/{awc_code}/{date}   (district_official, state_admin)
GET    /growth/{beneficiary_id}        (all roles, scoped)
POST   /growth                          (field_worker) — triggers Section 6.4 classification

GET    /reports/district/{district}    (district_official, state_admin) — aggregated
GET    /reports/state                  (state_admin only) — the pitch-view export
```

Background AI processing: use FastAPI `BackgroundTasks` for MVP scale (Section 3 reasoning applies — don't reach for Celery/Redis until pilot volume actually needs it).

---

## 9. Frontend Applications

### 9.1 Field Capture PWA — deliberately plain, not premium
This is the one app in your portfolio where the usual Motion v12/GSAP/React Three Fiber treatment is the *wrong* choice. The user is an Anganwadi worker or school staff member on a basic Android phone, possibly with low literacy comfort with apps, in a low-connectivity area. Design priorities, in order: large touch targets, Hindi-first bilingual UI (Hindi primary, English secondary — not the reverse), photo capture in ≤2 taps, minimal typed input (dropdowns/selectors over text fields), visible offline/sync status, works on a 3-year-old ₹8,000 Android phone without lag. This is the app that actually gets used every day — build it for that reality, not for a demo screenshot.

### 9.2 District Dashboard
Anganwadi supervisor/Block officer/District Collector's office. Table + chart views: per-AWC compliance trend, flagged days requiring follow-up, growth-classification distribution across the block. Functional, clean, still Next.js/Tailwind but restrained — this is a working tool for a busy official, not a showcase.

### 9.3 State Admin / Pitch View
This is the one surface that should carry your usual polish (Motion v12, clean data viz, the aesthetic register from your portfolio work) — because this is what DoIT&C staff, iStart reviewers, and a hackathon panel will actually see in a demo. Aggregate maps (district-level malnutrition trend), before/after case studies (mirroring the Gadchiroli "61→20" framing), exportable PDF report generation for a state-level review meeting.

---

## 10. Authentication & Role-Based Access

Three roles, enforced server-side on every route (never trust client-side role checks):
- **field_worker**: scoped to their own `awc_code` only — cannot see other schools' data
- **district_official**: scoped to their `district` — sees all AWCs within it
- **state_admin**: unrestricted read, plus export/report generation

Phone OTP login (Section 4). For the pilot/demo, a stubbed OTP flow (fixed test code) is acceptable — do not spend build time on a real SMS provider integration until there's a real district partner in hand.

---

## 11. Security & Data Handling

- All photo storage in Supabase Storage with row-level security tied to role/AWC scope — a field worker's bucket policy should make it structurally impossible to query another school's photos, not just impossible via the UI.
- JWT short-lived (1hr) + refresh token pattern.
- No raw beneficiary PII (name, DOB) exposed in any AI API call — only the plate photo goes to Gemini/Groq; beneficiary matching happens locally in your own database, never sent to a third-party model provider. This is both a privacy good-practice and reduces what's exposed if the pilot ever needs an actual security review.

---

## 12. Child Data Privacy — read this before building anything

This system handles data about children. Design constraints that are not optional:

- **No child face images, ever.** The system only needs plate photos. Do not add a "photograph the child for identification" feature even if it seems convenient — it turns a nutrition tool into a biometric-data system for minors, which is a different (and much higher-risk) category of compliance and ethical obligation, and isn't necessary for what this tool does.
- **Applicable law**: India's Digital Personal Data Protection Act (DPDP), 2023, applies here, and processing children's data under it requires verifiable parental/guardian consent and prohibits behavioral tracking/targeted advertising directed at children — neither of which this system does, but the consent mechanism needs a real answer before a live pilot, not just before scale. In practice for a school/Anganwadi pilot, consent is typically handled institutionally (school/AWC enrollment already involves guardian consent for data collection) — but this needs sign-off from whoever formally owns the pilot (District Collector's office, in coordination with the school), not an assumption baked into the code.
- **Minimize new PII collection.** Reuse existing Poshan Tracker/Raj-Poshan beneficiary IDs rather than creating a new PII store. The `beneficiaries` table (Section 5) is designed around this — it references an external ID rather than duplicating a full new identity record.
- **Data retention**: define and document a retention/deletion policy before pilot launch (e.g., raw plate photos retained 90 days for eval/audit, then deleted; aggregated compliance stats retained indefinitely). Don't leave this undecided — an undefined retention policy is itself the kind of gap that stalls a government pilot at legal review.

---

## 13. Deployment & Infra (pilot/demo scale)

- **Frontends**: Vercel (free tier) — separate projects for District Dashboard and State Admin View; Field PWA can also deploy to Vercel but needs PWA manifest + service worker configured correctly for installability.
- **Backend**: Render or Railway free tier for FastAPI.
- **Database + Storage**: Supabase free tier (Postgres + Storage + Row-Level Security in one place — this is doing real architectural work for you at zero cost, use it).
- **Domain**: a `.gov.in`-adjacent-sounding but honestly-owned domain for the pitch (e.g. `poshannetra.in` or similar) reads more credibly to a reviewer than a `vercel.app` subdomain, if budget allows a ~₹1,000/year domain purchase — small spend, real credibility gain.

---

## 14. Pilot Rollout Plan

1. **Week 1–2**: Deploy demo build, seed with synthetic/sample data for the pitch (do not use real children's data before consent/legal sign-off — see Section 12).
2. **VAAGDHARA conversation**: confirm one candidate school in Banswara/Dungarpur, understand real device/connectivity conditions on the ground — this may change assumptions in Section 7.
3. **Calibration session**: dietitian-weighed reference plates for the eval harness (Section 6.5) — do this before claiming any accuracy number in a pitch.
4. **2-week shadow pilot**: field worker uses the app alongside (not instead of) the existing paper/Raj-Poshan process, so nothing is lost if the tech fails, and you get a real precision/recall number on menu-compliance flagging.
5. **Handoff pitch**: District Collector's office or DoIT&C, with the shadow-pilot numbers as evidence — not projections.

---

## 15. Honest Limitations

State these explicitly in any pitch — being upfront about them is more credible than hiding them:

- Food recognition accuracy on tribal-region dishes is unvalidated until pilot data exists — no labeled dataset for this exact food vocabulary currently exists; this must be built during the pilot, not assumed beforehand.
- Portion estimation from a single top-down photo has an inherent error margin (occlusion, plate depth) — the MAE targets in Section 6.5 are goals, not guarantees, until measured.
- Raj-Poshan/Poshan Tracker integration (Section 2) is a proposed data contract, not a confirmed API — real integration requires NIC/WCD engagement this document cannot substitute for.
- Free-tier API rate limits (Gemini, Groq) will need monitoring at any scale beyond a single-school pilot — the zero-paid-API constraint is right for a demo/pilot budget, but is a real scaling constraint to flag honestly if this goes statewide.
- This system flags and documents; it does not itself fix menu non-compliance or food quality — the intervention still requires a human administrative response, same as in the Gadchiroli precedent.

---

## 16. Build Order for Claude Code

Execute in this sequence — each phase is independently demoable, which matters for a pitch that may need to happen before the full build is done:

1. **Data model + FastAPI skeleton** (Section 5, 8) — get `/beneficiaries`, `/captures`, `/growth` working with seeded sample data.
2. **AI pipeline + eval harness** (Section 6) — build and test in isolation against a small hand-picked image set before wiring into the API. Get the WHO z-score function unit-tested against reference tables first — this is the one place correctness must be proven, not assumed.
3. **Field Capture PWA** (Section 9.1) — offline-first capture flow, sync queue, bilingual UI.
4. **District Dashboard** (Section 9.2).
5. **State Admin/Pitch View** (Section 9.3) — this is likely the first thing shown in any hackathon/iStart demo, so it's worth polishing once the data underneath it is real.
6. **Auth + RBAC** wired across all three apps (Section 10) — do this after the core flows work with a stubbed auth bypass, not before, to avoid slowing early iteration.
7. **Deployment** (Section 13) + demo data seeding + honest-limitations doc (Section 15) finalized as a one-pager alongside the live demo.
