import { NextResponse } from "next/server";

/**
 * Step one of sign-in: ask the API to send a code.
 *
 * A thin proxy rather than a direct call from the browser, so the API origin
 * stays server-side and the throttle sees one client rather than one per
 * reviewer's network.
 */

export const dynamic = "force-dynamic";
const API = process.env.API_ORIGIN ?? "http://localhost:8000";

export async function POST(request: Request) {
  const body = await request.json();
  const response = await fetch(`${API}/auth/otp/request`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ phone: body.phone }),
    cache: "no-store",
  });
  const payload = await response.json().catch(() => ({}));
  return NextResponse.json(payload, { status: response.status });
}
