# Deploying

Three frontends on Vercel, one API on Render, database and photo storage on
Supabase. That split is Section 13's, and each piece is on a free tier.

Do them in this order — the frontends need the API's URL, and the API needs the
database.

---

## 1. Supabase (database + photo storage)

Follow [docs/phase1-supabase-setup.md](docs/phase1-supabase-setup.md). Ten
minutes. You need four values out of it:

| | Where |
|---|---|
| `DATABASE_URL` | Settings → Database → **Session pooler** (port 5432, *not* 6543), rewritten to `postgresql+asyncpg://` |
| `SUPABASE_URL` | Settings → API → Project URL |
| `SUPABASE_SERVICE_KEY` | Settings → API → `service_role` key |
| `SUPABASE_JWT_SECRET` | Settings → API → JWT Keys → legacy HS256 secret |

Region **Mumbai (ap-south-1)**. Already created one elsewhere? See
[docs/region-migration.md](docs/region-migration.md) — neither Supabase nor
Render can change region in place, so both have to be recreated. Supabase cannot move a project between regions
afterwards, so this is worth getting right on the first attempt: Section 12 puts
this system under India's DPDP Act, and "where does the data live" is the first
question at any government legal review. Latency from Rajasthan is the smaller
half of the argument.

Create a **private** bucket named `plate-photos`.

### Check it before touching Render

```bash
cd backend && uv run python scripts/check_supabase.py
```

It reads the same environment variables the application does, so it verifies
exactly what the deployment will use: the connection reaches Postgres, it is the
session pooler rather than the transaction pooler, the `authenticated` role can
be switched to (every RLS policy depends on that), pgcrypto is present, the JWT
secret is the symmetric one this build signs with, the bucket exists and is
private, and the region is Indian.

Every failure it reports is one that would otherwise appear as an opaque 500
from a service you cannot attach a debugger to.

---

## 2. Render (API)

Render dashboard → **New → Blueprint** → point it at this repository. It reads
[`render.yaml`](render.yaml) and creates the service.

**Expect the first deploy to fail.** A blueprint creates the service and
deploys it in the same motion, so that deploy runs before the secrets below
exist. This is a property of blueprints, not a fault in the build — the log
will say `configuration incomplete` and list exactly what is missing.

Then fill the values marked `sync: false` in the dashboard — they are
deliberately not in the repository:

```
DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_JWT_SECRET
ALLOWED_ORIGINS          ← leave until step 3; CORS blocks everything while empty
```

…and click **Manual Deploy**. That one succeeds.

`DATABASE_URL` accepts what Supabase gives you: the `postgresql://` scheme is
rewritten to `postgresql+asyncpg://` for you, and the `psql "…"` wrapper the
Connect dialog displays is unwrapped. An unfilled `[YOUR-PASSWORD]` placeholder
and the port-6543 transaction pooler are both refused by name rather than
accepted into a system that would start cleanly and enforce no access control.

Migrations run at startup, via [`backend/scripts/start.sh`](backend/scripts/start.sh),
so the schema is never behind the code. Health check is `/health`.

Two free-tier facts shape this: Render's free plan supports neither
`preDeployCommand` nor Shell access. Migrations therefore run in the start
command — a no-op once current, so the instance re-running them when it wakes
from sleep costs one quick query — and seeding happens from your own machine.

### Seed the demo data — from your laptop, not Render

There is no Shell on the free plan, and none is needed: the seed is an ordinary
command pointed at the Supabase database.

```bash
cd backend
```
```bash
APP_ENV=demo DATABASE_URL='<your Supabase session-pooler URI>' uv run python -m app.seed
```

Note `APP_ENV=demo` — the script refuses to run under `production`, which is
what stops synthetic children being written into a real database by accident.

It writes 3 centres, 120 children, 6 months of growth entries and ~5,000 plate
captures, all synthetic (Sections 12, 14), and prints the prevalence it actually
achieved rather than one it promises.

If you set `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` too, it also uploads the
placeholder plate images so signed URLs resolve; without them it skips that and
says so.

### Free tier, and what it costs you

Render's free instances sleep after 15 minutes idle and take **30–60 seconds**
to wake. Before a demo, open the API once and wait for it. Supabase pauses a
free project after about a week of inactivity — `GET /health/db` on a schedule
keeps both warm.

---

## 3. Vercel (three frontends)

Three separate projects from the same repository, each with a different **Root
Directory**:

| Project | Root directory | Framework |
|---|---|---|
| `poshannetra-field` | `apps/field-pwa` | Vite |
| `poshannetra-district` | `apps/district-dashboard` | Next.js |
| `poshannetra-state` | `apps/state-admin` | Next.js |

Each app has its own `vercel.json`; Vercel picks it up from the root directory.

**The two Next apps need one environment variable:**

```
API_ORIGIN = https://poshannetra-api.onrender.com
```

**The PWA needs none** — its `vercel.json` rewrites `/api/*` to the Render URL.
If your Render service has a different name, edit that rewrite.

### Then go back to Render

Set `ALLOWED_ORIGINS` to all three deployed origins, comma separated:

```
https://poshannetra-field.vercel.app,https://poshannetra-district.vercel.app,https://poshannetra-state.vercel.app
```

Until this is set, every browser request from every app is blocked by CORS.
It is the one step easy to forget and the one that makes everything look broken.

---

## 4. Signing in to the demo

`render.yaml` ships `OTP_PROVIDER=console` and `DEMO_REVEAL_OTP=true`, so the
sign-in screen shows the code for the seeded `99999xxxxx` numbers. No SMS
credits, no log-reading.

| Number | Role | Opens |
|---|---|---|
| `9999900001` | field worker, Ghatol | the capture PWA |
| `9999900010` | district official, Banswara | the district dashboard |
| `9999900020` | state admin | the state review |

**This is an open door, deliberately.** Anyone with the URL can sign in as any
seeded account. It is acceptable only because the database holds nothing but
synthetic data — which is also why `python -m app.seed` refuses to run when
`APP_ENV=production`.

**Before any real child's data touches this system**, set `APP_ENV=production`
on Render. That disables the code reveal regardless of `DEMO_REVEAL_OTP`,
refuses seeding, and requires a real SMS provider
([docs/phase6-auth-setup.md](docs/phase6-auth-setup.md)).

---

## What is not deployed

- **Real SMS.** MSG91 is implemented but needs an account, credits and a
  DLT-approved template. The demo uses the console provider.
- **Real food recognition.** `AI_PROVIDER=mock` spends nothing. A free Gemini
  key switches it on ([docs/phase2-ai-setup.md](docs/phase2-ai-setup.md)); the
  page says plainly when its AI output is a stand-in.
- **A custom domain.** Section 13 suggests one reads more credibly to a
  reviewer than a `vercel.app` subdomain, for about ₹1,000 a year.
