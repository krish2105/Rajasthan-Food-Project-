import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Keeps the access cookie fresh.
 *
 * The refresh has to happen here rather than in the page because a server
 * component cannot write cookies, and the API rotates the refresh token on
 * every use. A page that refreshed and could only keep the *access* token
 * would leave the spent refresh token in the cookie; presenting it again would
 * look like a leaked credential to the API, which revokes the whole chain. The
 * reviewer would be signed out on their second visit and the audit log would
 * record a compromise that never happened.
 *
 * Middleware can write cookies, so both halves of the rotated pair are stored
 * together and that cannot happen.
 */

const ACCESS = "pn_access";
const REFRESH = "pn_refresh";
const API = process.env.API_ORIGIN ?? "http://localhost:8000";

export async function middleware(request: NextRequest) {
  const access = request.cookies.get(ACCESS)?.value;
  const refresh = request.cookies.get(REFRESH)?.value;

  // Nothing to do: either the session is live, or there is none to renew.
  if (access || !refresh) return NextResponse.next();

  try {
    const response = await fetch(`${API}/auth/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
      cache: "no-store",
    });

    if (!response.ok) {
      // Expired, revoked, or reuse detected. Clear the cookie so the next
      // request renders the sign-in screen rather than retrying forever.
      const cleared = NextResponse.next();
      cleared.cookies.delete(REFRESH);
      return cleared;
    }

    const body = (await response.json()) as {
      access_token: string;
      refresh_token: string;
      expires_in: number;
    };

    const next = NextResponse.next();
    const secure = process.env.NODE_ENV === "production";
    next.cookies.set(ACCESS, body.access_token, {
      httpOnly: true, sameSite: "lax", secure, path: "/", maxAge: body.expires_in,
    });
    next.cookies.set(REFRESH, body.refresh_token, {
      httpOnly: true, sameSite: "lax", secure, path: "/", maxAge: 30 * 24 * 60 * 60,
    });
    return next;
  } catch {
    // The API is unreachable. Leave the session alone -- an outage must not
    // sign anyone out.
    return NextResponse.next();
  }
}

export const config = {
  // Pages only. The auth routes manage their own cookies, and running this
  // against them would refresh a token mid-sign-in.
  matcher: ["/((?!auth|_next/static|_next/image|favicon.ico).*)"],
};
