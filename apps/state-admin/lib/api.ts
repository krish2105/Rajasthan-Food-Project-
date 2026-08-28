import type { Report } from "./report";
import { readTokens } from "./session";

/**
 * Server-side data fetching.
 *
 * The token never reaches the browser: it lives in an httpOnly cookie and every
 * request to the API is made from the server. A cross-site scripting bug on a
 * page rendering district-level child nutrition data should not also be a
 * credential theft.
 *
 * Phase 6 replaced the development token endpoint with phone OTP. The scope
 * model did not change -- same claims, same row-level security -- only the way
 * a caller proves who they are.
 */

const API = process.env.API_ORIGIN ?? "http://localhost:8000";

export class ApiUnavailable extends Error {}

/** No session at all -- the caller should render the sign-in screen. */
export class NotSignedIn extends Error {}

export async function fetchStateReport(): Promise<Report> {
  const { access, refresh } = await readTokens();
  if (!access && !refresh) throw new NotSignedIn();

  const get = async (token: string) =>
    fetch(`${API}/reports/state`, {
      headers: { Authorization: `Bearer ${token}` },
      // Always fresh: a review meeting looking at a cached report from last
      // week is worse than one that fails loudly.
      cache: "no-store",
    });

  // `middleware.ts` refreshes the cookie before this runs, so by the time the
  // page renders the access token is either valid or genuinely gone. Doing the
  // refresh here instead would lose the rotated refresh token, because a server
  // component cannot write cookies.
  if (!access) throw new NotSignedIn();
  const response = await get(access);
  void refresh;
  if (response.status === 401 || response.status === 403) throw new NotSignedIn();
  if (!response.ok) throw new ApiUnavailable(`report unavailable (${response.status})`);
  return (await response.json()) as Report;
}
