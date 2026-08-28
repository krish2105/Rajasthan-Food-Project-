# Phase 6 setup — authentication

Sign-in is phone OTP. Nothing needs configuring to run it locally: the default
provider logs the code to the server console and returns it to the sign-in
screen, so a demo is two fields and no SMS.

```bash
OTP_PROVIDER=console    # the default
```

Real SMS needs MSG91, below.

---

## What changed

The development token endpoint that carried Phases 1–5 is **gone**. It was
gated on `APP_ENV` and tested, but an authentication bypass that exists only
outside production is still one environment variable away from being live, and
this is the phase that was always going to remove it.

The scope model did not change. Roles, claims and every row-level security
policy have been real and tested since Phase 1 — only the way a caller proves
who they are is different.

| | |
|---|---|
| `POST /auth/otp/request` | send a code |
| `POST /auth/otp/verify` | exchange it for an access + refresh token |
| `POST /auth/refresh` | rotate the pair |
| `POST /auth/logout` | revoke this device |

## The one design tension worth knowing

Section 11 asks for one-hour access tokens. Section 7 requires the Field PWA to
work through days without connectivity. A worker with no signal cannot refresh
anything.

They are reconciled by making the access token short and the **refresh token
30 days**. Nothing a worker does — photograph a plate, record a weight — ever
consults token state; those write to IndexedDB. Only syncing needs a token, and
syncing already assumes the network is usually absent. When signal returns, the
sync engine refreshes once and carries on.

If the session has genuinely ended (30 days, or a revocation), the worker signs
in again and **the queue is untouched** — signing in drains it. Losing a day of
plate photographs because a token lapsed would be the worst possible reading of
Section 7.

## Hardening

A six-digit code is one of a million, so:

- **Codes expire in 5 minutes** and die after **5 wrong attempts**.
- **One code at a time per number.** Requesting again invalidates the previous.
- **Throttled**: 30 seconds between requests, 5 per 15 minutes — so the endpoint
  cannot be used to bombard someone's phone.
- **Stored as HMACs keyed on the server secret**, bound to the phone number. A
  plain hash of six digits is a million-entry rainbow table anyone can build; the
  keyed HMAC means a database copy alone is not enough.
- **Failure is uninformative.** An unregistered number, a wrong code and an
  expired code produce the same response, and the throttle applies to unknown
  numbers too. Otherwise this endpoint enumerates which phone numbers belong to
  Anganwadi workers.

Refresh tokens **rotate on every use**. A token presented twice was either
replayed or cloned, so the whole chain is revoked and the worker signs in again.

Both tables have row-level security enabled and **no policies at all**, which
denies the `authenticated` role everything. The auth flow necessarily runs
before a caller has an identity and uses the owner connection; nothing arriving
through a request session has any business reading a one-time code.

---

## MSG91

Section 10 advises against spending build time on a real SMS integration until
there is a district partner in hand. That advice was overridden deliberately, so
the client is complete rather than a placeholder — but it cannot be exercised
against the live service without an account, and the console provider remains
the default and what tests use.

### What you need

1. An **MSG91 account** with SMS credits.
2. An **authkey** — MSG91 panel → Settings → API.
3. A **DLT-approved template**. This is the part that takes time: Indian
   regulation (TRAI DLT) requires every transactional SMS template to be
   registered and approved before it will be delivered. Register the entity and
   the sender ID first, then the template, then take its **template ID** from
   the MSG91 panel.
4. A **sender ID** (six alphanumeric characters, e.g. `POSHAN`), also
   DLT-registered.

```bash
OTP_PROVIDER=msg91
MSG91_AUTHKEY=<your authkey>
MSG91_TEMPLATE_ID=<template id from the panel>
MSG91_SENDER=POSHAN
```

### Two things about their API worth knowing

**It returns HTTP 200 on failure.** An invalid authkey, an unapproved template
and a malformed number all come back as `200` with `{"type": "error"}` in the
body. Checking the status code alone reports every misconfiguration as a
successful send, and the worker waits for a message that was never dispatched.
The client checks the `type` field; there is a test for it.

**We supply our own code.** MSG91 can generate and verify one itself, but then
the expiry, the attempt limit and the throttle would be its policy rather than
ours, and would change if the provider did. The code is ours; MSG91 is the
transport.

### Verifying it

There is no way to test a real send without credits. Once configured:

```bash
curl -X POST localhost:8000/auth/otp/request \
  -H 'content-type: application/json' -d '{"phone":"9999900001"}'
```

The response omits `debug_code` under a real provider. Check the `otp_codes`
table's `delivery_status` — `sent` means MSG91 accepted it, `failed` records
their reason verbatim, which is how a misconfigured template is distinguished
from a worker who never typed the code.

---

## Sessions in the three apps

| | Storage | Why |
|---|---|---|
| Field PWA | `localStorage` | Must survive being offline; cookies do not help there |
| District Dashboard | httpOnly cookies, access token exposed via `/session` | Writes follow-ups from the browser, so it needs a bearer token |
| State Admin | httpOnly cookies, never exposed | Renders server-side; no credential need reach the browser at all |

Both Next apps refresh in `middleware.ts` rather than in the page. That is not
incidental: the API rotates the refresh token on every use, and a server
component cannot write cookies. A page that refreshed and could only keep the
*access* token would leave the spent refresh token in the cookie — presenting it
again looks like a leaked credential, the API revokes the whole chain, and the
reviewer is signed out on their second visit with the log recording a compromise
that never happened.

## Revoking a lost phone

There is no admin UI for this yet. Until Phase 7, revoke directly:

```sql
UPDATE refresh_tokens SET revoked_at = now(), revoked_reason = 'lost_device'
WHERE worker_id = (SELECT id FROM field_workers WHERE phone = '9999900001')
  AND revoked_at IS NULL;
```

The access token still works for up to an hour. Shortening `JWT_TTL_SECONDS`
narrows that window at the cost of more refresh traffic.

## Known limitations

- **No admin surface for revocation.** The SQL above is the whole story.
- **The throttle is per phone number, not per IP.** An attacker with many
  numbers can still make many requests; a proxy-level rate limit belongs in
  Phase 7's deployment.
- **No account lockout.** Repeated wrong codes burn the code, not the account,
  so a worker cannot be locked out by someone else guessing at their number.
  That is the right trade for this user, and it means brute force is bounded by
  code lifetime rather than by attempts across codes.
