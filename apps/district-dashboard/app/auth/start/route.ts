import { NextResponse } from "next/server";

/**
 * Step one of sign-in: ask the API to send a code.
 *
 * A thin proxy rather than a direct call from the browser, so the API origin
 * stays server-side and the throttle sees one client rather than one per
 * caller's network.
 */

export const dynamic = "force-dynamic";
const API = process.env.API_ORIGIN ?? "http://localhost:8000";

export async function POST(request: Request) {
  const body = await request.json();

  let response: Response;
  try {
    response = await fetch(`${API}/auth/otp/request`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ phone: body.phone }),
      cache: "no-store",
    });
  } catch {
    // An unreachable API used to surface in the browser as "Failed to fetch",
    // which tells the person in front of the screen nothing they can act on.
    // Naming the cause is the difference between a dead end and a fix.
    return NextResponse.json(
      {
        detail:
          "The PoshanNetra API is not reachable. If you are running locally, " +
          "start it with: cd backend && make serve",
      },
      { status: 503 },
    );
  }

  const payload = await response.json().catch(() => ({}));
  return NextResponse.json(payload, { status: response.status });
}
