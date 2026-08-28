# Moving to the right regions

Neither Supabase nor Render can change a region after a project or service is
created. Both have to be recreated. Doing that costs a few minutes while the
database is empty and a data migration once it is not, which is the whole reason
to do it now.

## Why this is worth the interruption

**Supabase (the database) → Mumbai, `ap-south-1`.** This is the one that
matters. Section 12 places this system under India's **DPDP Act, 2023**, and it
holds names, dates of birth and anthropometry for tribal-belt children. At a
DoIT&C or Collector's-office review, "where does this data rest" is an early
question, and an answer of "Seoul" turns a technical review into a legal one.
Latency from Rajasthan — roughly 900 km to Mumbai against 5,000 to Seoul — is
the smaller half of the argument.

**Render (the API) → Singapore.** Render operates no Indian region, so
Singapore is the closest available. This is a latency decision, not a legal
one: the API holds nothing between requests, so no data rests there. Worth
saying plainly at review rather than leaving to be discovered — cross-border
*processing* is permitted under Section 16 of the DPDP Act, which restricts
transfer only to countries the government has notified against, and Singapore
is not among them.

## 1. Supabase → Mumbai

The dashboard reporting **No migrations** and **No backups** means the database
is empty and nothing is lost.

1. Old project → Settings → General → **Delete project**. Do this first, so the
   free-tier project limit does not block the new one.
2. **New project**, Region **South Asia (Mumbai)**. Note the new project ref.
3. Storage → **New bucket** → `plate-photos`, **Private**.
4. Update `backend/.env` with the four new values (see [DEPLOY.md](../DEPLOY.md)).
5. Verify before going further:

   ```bash
   cd backend && uv run python scripts/check_supabase.py
   ```

   A region outside India now **fails** rather than warns. It is not advice: it
   cannot be corrected later without moving every row.

6. Migrate and seed:

   ```bash
   cd backend && uv run alembic upgrade head && APP_ENV=demo uv run python -m app.seed
   ```

## 2. Render → Singapore

`render.yaml` already asks for `region: singapore`, but a service keeps the
region it was created in, so editing that line does not move `poshannetra-api`.

First confirm it actually needs moving — Render dashboard → **poshannetra-api**
→ **Settings** → Region. If it already says Singapore, skip this section.

1. Settings → **Delete service** (`poshannetra-api`).
2. **New → Blueprint** → this repository. It creates the service in Singapore.
3. **The first deploy will fail**, by design — a blueprint deploys in the same
   motion as it creates, before any `sync: false` secret exists. The log will
   say `configuration incomplete` and name what is missing.
4. Environment → set `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
   `SUPABASE_JWT_SECRET` (and `ALLOWED_ORIGINS` once the Vercel URLs exist).
5. **Manual Deploy.**

## Confirming it worked

```bash
curl -s https://poshannetra-api.onrender.com/health/db
```

```json
{
  "status": "ok",
  "rls_policies": 11,
  "data_residency": { "region": "ap-south-1", "in_india": true }
}
```

`data_residency` is served unauthenticated on purpose: where children's data
rests is something a reviewer should be able to check for themselves rather
than take on trust. Only the region code is exposed — never the host or the
connection string.

`"in_india": null` means the region could not be read from the connection
string, which happens with Supabase's direct-connection host
(`db.<ref>.supabase.co`). That is distinct from `false`, and means "cannot
tell" rather than "not in India". Switch to the session pooler URI, which names
its region, so the answer is verifiable.
