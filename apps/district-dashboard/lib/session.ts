import { cookies } from "next/headers";

/**
 * Server-side session for the review surface.
 *
 * Tokens live in httpOnly cookies rather than localStorage, and this app never
 * hands one to the browser at all: every request to the API is made from the
 * server. A cross-site scripting bug on a page that renders district-level
 * child nutrition data should not also be a credential theft.
 *
 * Phase 6 replaced the development token endpoint that carried Phases 1 to 5.
 * The scope model is unchanged -- the same claims, the same row-level security
 * policies -- but a caller now has to prove who they are with a code sent to
 * their phone.
 */

const ACCESS_COOKIE = "pn_access";
const REFRESH_COOKIE = "pn_refresh";
const API = process.env.API_ORIGIN ?? "http://localhost:8000";

export interface SessionTokens {
  access: string;
  refresh: string;
}

export interface SessionUser {
  name: string;
  role: string;
  district: string | null;
}

/** Cookie options. Secure in production; `lax` so a normal navigation carries them. */
function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  };
}

export async function storeSession(tokens: {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}): Promise<void> {
  const jar = await cookies();
  jar.set(ACCESS_COOKIE, tokens.access_token, cookieOptions(tokens.expires_in));
  // Outlives the access token by a wide margin, which is the whole point: a
  // reviewer opening this a week later gets a silent refresh rather than a
  // sign-in screen.
  jar.set(REFRESH_COOKIE, tokens.refresh_token, cookieOptions(30 * 24 * 60 * 60));
}

export async function clearSession(): Promise<void> {
  const jar = await cookies();
  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
}

export async function readTokens(): Promise<Partial<SessionTokens>> {
  const jar = await cookies();
  return {
    access: jar.get(ACCESS_COOKIE)?.value,
    refresh: jar.get(REFRESH_COOKIE)?.value,
  };
}

export interface RefreshedPair {
  access: string;
  refresh: string;
  expiresIn: number;
}

/**
 * Exchange the refresh cookie for a new pair.
 *
 * **Both tokens must be persisted by the caller.** The API rotates on every
 * use, so the token just spent is revoked server-side; keeping it in the cookie
 * would present it again on the next refresh, and the API treats a re-presented
 * token as a leak and revokes the entire chain. Storing only the access token
 * would therefore sign the reviewer out on their *second* visit, with the log
 * blaming a compromise that never happened.
 *
 * Server components cannot write cookies, which is why `middleware.ts` does the
 * refresh instead of the page.
 */
export async function refreshAccess(refresh: string): Promise<RefreshedPair | null> {
  try {
    const response = await fetch(`${API}/auth/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
      cache: "no-store",
    });
    if (!response.ok) return null;
    const body = (await response.json()) as {
      access_token: string;
      refresh_token: string;
      expires_in: number;
    };
    return {
      access: body.access_token,
      refresh: body.refresh_token,
      expiresIn: body.expires_in,
    };
  } catch {
    return null;
  }
}

export const COOKIE_NAMES = { access: ACCESS_COOKIE, refresh: REFRESH_COOKIE } as const;
