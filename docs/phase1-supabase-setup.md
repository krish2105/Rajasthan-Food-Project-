# Supabase setup for Phase 1

You do these steps; they need credentials that should never reach a tracked file
or a chat log. Everything the backend needs, it reads from `backend/.env`, which
is gitignored.

Budget: about ten minutes. Cost: nothing — this is all free tier (Section 13).

---

## 1. Create the project

supabase.com → **New project**.

- **Region: Mumbai (`ap-south-1`).** Two reasons, both worth having an answer
  for if a reviewer asks: latency from Rajasthan, and data residency. Section 12
  puts this system under India's DPDP Act 2023, and "the database is in India"
  is a much shorter conversation at legal review than the alternative.
- Set a strong database password and store it in your password manager. You will
  paste it into `.env` once.
- Free tier is enough for the whole pilot: 120 children and ~5,000 capture rows
  is a rounding error against the 500 MB limit.

## 2. Connection string

Project Settings → **Database** → Connection string → **Session pooler**.

Take the **session pooler (port 5432)**, *not* the transaction pooler (6543).
This matters:

- The RLS design in `alembic/versions/0002_rls_policies.py` depends on
  `SET LOCAL ROLE` and `set_config(..., is_local => true)` holding for the whole
  transaction.
- asyncpg's prepared-statement cache misbehaves behind transaction pooling. The
  code sets `statement_cache_size=0` defensively anyway, but the session pooler
  removes the problem rather than working around it.

Rewrite the scheme to `postgresql+asyncpg://` when you paste it into `.env`.

## 3. API keys

Project Settings → **API**. Copy:

- **Project URL** → `SUPABASE_URL`
- **`service_role` key** → `SUPABASE_SERVICE_KEY`

The `service_role` key bypasses every policy in the database. It is server-side
only — it must never reach a browser, and Phases 3–5 must never receive it.

## 4. JWT secret

Project Settings → API → **JWT Keys** → the legacy **HS256 JWT secret** →
`SUPABASE_JWT_SECRET`.

This is the load-bearing choice in the whole setup. Signing our tokens with
Supabase's own secret means **one** token is simultaneously valid for the
FastAPI routes, for the Postgres session claims that drive RLS, and for
Supabase Storage's policies. Any other arrangement gives you two or three
identities that can silently drift apart.

**If your project only offers the newer asymmetric signing keys** and no legacy
HS256 secret: tell me, and set `STORAGE_MODE=service` in `.env`. The fallback is
documented in §7 below. Postgres RLS is unaffected either way — it validates our
claims, not Supabase's signature.

## 5. Storage bucket

Storage → **New bucket** → name `plate-photos` → **Private** (uncheck public).

Do not make it public. These are photographs taken inside Anganwadi centres, and
a public bucket is a public URL for every one of them.

The seed script calls `ensure_bucket()` and will create it if you skip this, but
creating it yourself means you have seen the private toggle with your own eyes.

## 6. Fill in `.env`

```bash
cd backend && cp .env.example .env
```

Then edit `backend/.env`. Every variable is documented inline in
`.env.example`. `.env` is gitignored and never read by anything but your local
process.

## 7. Storage modes

`STORAGE_MODE` selects how photo uploads and signed URLs authenticate:

| Mode | How it authenticates | Storage RLS | When |
|---|---|---|---|
| `rls` (default) | The caller's own JWT | Enforced by Supabase | Legacy HS256 secret available |
| `service` | The `service_role` key | Bypassed; scope enforced in app code | Only asymmetric keys available |

In `rls` mode, Storage is genuinely part of the security boundary. In `service`
mode it is not, and the honest description is "scoped by application code" —
which is what §11 of the master prompt asks us not to settle for, so prefer
`rls` when the project allows it.

Postgres RLS is load-bearing in **both** modes.

## 8. Storage policies (only for `rls` mode)

Storage → `plate-photos` → Policies → New policy → **For full customization**.
Object paths are `{awc_code}/{beneficiary_id}/{capture_id}.jpg`, so the first
path segment carries the scope.

```sql
-- SELECT
create policy "read own awc plate photos"
on storage.objects for select to authenticated
using (
  bucket_id = 'plate-photos'
  and (
    (auth.jwt() ->> 'app_role') = 'state_admin'
    or (auth.jwt() ->> 'app_role') = 'district_official'
    or (storage.foldername(name))[1] = (auth.jwt() ->> 'awc_code')
  )
);

-- INSERT
create policy "write own awc plate photos"
on storage.objects for insert to authenticated
with check (
  bucket_id = 'plate-photos'
  and (storage.foldername(name))[1] = (auth.jwt() ->> 'awc_code')
);
```

District officials are scoped by district in Postgres but not here, because a
storage path carries no district. That is a real gap and it is deliberate: the
API never hands a district official a path it has not already read through an
RLS-scoped query, so Postgres is the constraint. Closing it properly means
putting the district in the path, which is a Phase 6 decision, not a Phase 1 one.

## 9. Run it

```bash
cd backend && uv sync && uv run alembic upgrade head && uv run python -m app.seed
```

Then follow the verification steps in the project `README.md`.

## Operational note: free-tier projects pause

Supabase pauses a free project after about a week of inactivity, and a paused
project fails at the worst possible moment — the start of a demo. `GET /health/db`
exists partly for this. Ping it on a schedule during any week you might need to
present, and check it before you walk into a room.
