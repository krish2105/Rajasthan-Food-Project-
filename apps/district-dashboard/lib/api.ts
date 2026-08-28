/**
 * Backend client.
 *
 * Runs in the browser, unlike the state review's server-side fetch, because
 * this surface writes: an officer records a follow-up and the queue has to
 * update underneath them. The token is minted once on the server and handed to
 * the client through a route handler, so the dev-token phone number is never in
 * the bundle.
 *
 * Phase 6 replaces the token source with real OTP. Nothing else here changes.
 */

import type {
  FlaggedDay,
  FollowUpRecord,
  QuietCentre,
  ReferralChild,
  Scope,
  TrendPoint,
} from "./types";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

let token: string | null = null;

async function ensureToken(): Promise<string> {
  if (token) return token;
  const response = await fetch("/session", { cache: "no-store" });
  if (!response.ok) throw new ApiError("could not start a session", response.status);
  const body = (await response.json()) as { token: string };
  token = body.token;
  return token;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = await ensureToken();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${auth}`);
  if (init.body) headers.set("Content-Type", "application/json");

  const response = await fetch(`/api${path}`, { ...init, headers, cache: "no-store" });
  if (response.status === 401) {
    // The token expired mid-session. Drop it and let the caller retry rather
    // than showing an officer an authentication error they cannot act on.
    token = null;
    throw new ApiError("session expired", 401);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? body.code ?? detail;
    } catch {
      /* not problem+json */
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const getScope = () => request<Scope>("/reports/scope");

export const getFlagged = (params: { since?: string; includeResolved?: boolean }) => {
  const query = new URLSearchParams();
  if (params.since) query.set("since", params.since);
  if (params.includeResolved) query.set("include_resolved", "true");
  return request<{ since: string; items: FlaggedDay[] }>(
    `/compliance/flagged?${query.toString()}`,
  );
};

export const getQuietCentres = (days = 3) =>
  request<{ days: number; items: QuietCentre[] }>(`/compliance/quiet-centres?days=${days}`);

export const getReferrals = (district: string, classifications: string[]) => {
  const query = classifications.map((c) => `classification=${encodeURIComponent(c)}`).join("&");
  return request<{ items: ReferralChild[] }>(
    `/reports/district/${encodeURIComponent(district)}/children?${query}`,
  );
};

export const getCentreTrend = (awcCode: string, since?: string) =>
  request<{ awc_code: string; points: TrendPoint[] }>(
    `/compliance/${encodeURIComponent(awcCode)}/trend${since ? `?since=${since}` : ""}`,
  );

export const getFollowUps = (complianceId: string) =>
  request<{ items: FollowUpRecord[] }>(`/compliance/${complianceId}/follow-ups`);

export const recordFollowUp = (
  complianceId: string,
  body: { outcome: string; note?: string },
) =>
  request<FollowUpRecord>(`/compliance/${complianceId}/follow-up`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getDistrictReport = (district: string) =>
  request<Record<string, unknown>>(`/reports/district/${encodeURIComponent(district)}`);
