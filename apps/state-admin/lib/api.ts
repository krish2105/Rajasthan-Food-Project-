import type { Report } from "./report";

/**
 * Server-side data fetching.
 *
 * The token is minted on the server and never reaches the browser. This is a
 * read-only reporting surface rendered for a review meeting, so there is no
 * reason for a credential to exist client-side at all.
 *
 * Phase 6 replaces the dev token endpoint with real OTP; this is the single
 * function that changes.
 */

const API = process.env.API_ORIGIN ?? "http://localhost:8000";
const REVIEWER_PHONE = process.env.REVIEWER_PHONE ?? "9999900020";

export class ApiUnavailable extends Error {}

async function token(): Promise<string> {
  const response = await fetch(`${API}/auth/dev/token`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ phone: REVIEWER_PHONE }),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new ApiUnavailable(`sign-in failed (${response.status})`);
  }
  const body = (await response.json()) as { access_token: string };
  return body.access_token;
}

export async function fetchStateReport(): Promise<Report> {
  const auth = await token();
  const response = await fetch(`${API}/reports/state`, {
    headers: { Authorization: `Bearer ${auth}` },
    // Always fresh: a review meeting looking at a cached report from last week
    // is worse than one that fails loudly.
    cache: "no-store",
  });
  if (!response.ok) {
    throw new ApiUnavailable(`report unavailable (${response.status})`);
  }
  return (await response.json()) as Report;
}
