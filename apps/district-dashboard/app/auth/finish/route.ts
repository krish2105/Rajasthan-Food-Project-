import { NextResponse } from "next/server";
import { storeSession } from "@/lib/session";

/**
 * Step two: exchange the code for a session.
 *
 * The refresh token is written into an httpOnly cookie and never reaches the
 * browser. The short-lived access token is stored the same way but *is* handed
 * out by /session, because this surface writes follow-ups from the client and
 * would otherwise need every API call proxied through Next.
 *
 * The trade-off is deliberate and bounded: a script on this page could read a
 * token that expires within the hour, but not the credential that renews it.
 */

export const dynamic = "force-dynamic";
const API = process.env.API_ORIGIN ?? "http://localhost:8000";

export async function POST(request: Request) {
  const body = await request.json();
  const response = await fetch(`${API}/auth/otp/verify`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ phone: body.phone, otp: body.otp }),
    cache: "no-store",
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    return NextResponse.json(detail, { status: response.status });
  }

  const session = await response.json();
  if (session.role === "field_worker") {
    // A field worker's app is the capture PWA. The API would give them an
    // empty dashboard rather than an error, which is more confusing than
    // saying so here.
    return NextResponse.json(
      { detail: "This dashboard is for supervisors. Use the capture app on your phone." },
      { status: 403 },
    );
  }

  await storeSession(session);
  return NextResponse.json({
    name: session.name,
    role: session.role,
    district: session.district,
  });
}
