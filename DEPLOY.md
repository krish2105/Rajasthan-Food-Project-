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

Region **Mumbai (ap-south-1)**: latency, and data residency under the DPDP Act
(Section 12). Create a **private** bucket named `plate-photos`.

---

## 2. Render (API)

Render dashboard → **New → Blueprint** → point it at this repository. It reads
[`render.yaml`](render.yaml) and creates the service.

Then fill the values marked `sync: false` in the dashboard — they are
deliberately not in the repository:

```
DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_JWT_SECRET
ALLOWED_ORIGINS          ← leave until step 3; CORS blocks everything while empty
```

Migrations run automatically before each release (`preDeployCommand`), so the
schema is never behind the code. Health check is `/health`.

**Seed the demo data** once the first deploy is green — Render dashboard →
Shell:

```bash
python -m app.seed
```

That writes 3 centres, 120 children, 6 months of growth entries and ~5,000
plate captures. All synthetic (Sections 12, 14).

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
