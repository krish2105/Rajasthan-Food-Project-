import { NextResponse } from "next/server";

/**
 * Mints the session token server-side.
 *
 * The dashboard writes follow-ups, so it needs a token in the browser. What it
 * does not need is the dev-token phone number in the bundle, which is why the
 * exchange happens here: the client asks this route for a token and never sees
 * how it was obtained.
 *
 * Phase 6 replaces the body of this handler with a real OTP exchange. The
 * client contract -- GET /session returns { token } -- does not change.
 */

export const dynamic = "force-dynamic";

const API = process.env.API_ORIGIN ?? "http://localhost:8000";
const OFFICER_PHONE = process.env.OFFICER_PHONE ?? "9999900010";

export async function GET() {
  const response = await fetch(`${API}/auth/dev/token`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ phone: OFFICER_PHONE }),
    cache: "no-store",
  });
  if (!response.ok) {
    return NextResponse.json(
      { error: "sign-in failed", status: response.status },
      { status: 502 },
    );
  }
  const body = (await response.json()) as { access_token: string };
  return NextResponse.json({ token: body.access_token });
}
