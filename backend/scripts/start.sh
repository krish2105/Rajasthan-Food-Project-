#!/usr/bin/env bash
# Render start command.
#
# A blueprint creates the service and deploys it immediately, which means the
# first deploy runs before anyone has had a chance to fill the env vars marked
# `sync: false`. Without this script that deploy dies inside Alembic with a
# stack trace, and the dashboard reports only "failed" -- which reads as a
# broken build rather than as configuration that is not finished yet.
#
# So: name the missing variables plainly, exit, and let the operator fill them
# in and redeploy. Starting anyway is not an option worth having. The health
# check would pass, the service would look up, and every request touching data
# would fail -- which is a worse outcome than a deploy that says why it stopped.
set -euo pipefail

missing=()
for var in DATABASE_URL SUPABASE_JWT_SECRET; do
  [[ -n "${!var:-}" ]] || missing+=("$var")
done

if (( ${#missing[@]} )); then
  cat >&2 <<EOF

================================================================
  PoshanNetra API cannot start: configuration incomplete
================================================================

  Not set: ${missing[*]}

  These are marked 'sync: false' in render.yaml, so Render cannot
  supply them -- they hold secrets and must be entered by hand.

  Render dashboard -> poshannetra-api -> Environment, then set:

    DATABASE_URL          Supabase -> Connect -> Session pooler
                          (port 5432, NOT the 6543 transaction pooler)
    SUPABASE_JWT_SECRET   Supabase -> Settings -> JWT Keys -> legacy secret
    SUPABASE_URL          Supabase -> Settings -> API -> Project URL
    SUPABASE_SERVICE_KEY  Supabase -> Settings -> API Keys -> service_role
    ALLOWED_ORIGINS       your three Vercel origins, comma-separated

  Then click Manual Deploy. The first blueprint deploy failing here
  is expected: there is no earlier point at which these can be set.

================================================================

EOF
  exit 1
fi

echo "==> Running database migrations"
alembic upgrade head

echo "==> Starting gunicorn on port ${PORT:-8000}"
exec gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind "0.0.0.0:${PORT:-8000}" \
  --timeout 120 \
  --access-logfile -
