import { NextResponse } from "next/server";
import { storeSession } from "@/lib/session";

/**
 * Step two: exchange the code for a session.
 *
 * The tokens are written straight into httpOnly cookies and never returned to
 * the browser. Only the reviewer's name and role come back, which is all the
 * interface needs to render.
 */

export const dynamic = "force-dynamic";
const API = process.env.API_ORIGIN ?? "http://localhost:8000";

export async function POST(request: Request) {
  const body = await request.json();
  let response: Response;
  try {
    response = await fetch(`${API}/auth/otp/verify`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ phone: body.phone, otp: body.otp }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      {
        detail:
          "The PoshanNetra API is not reachable. If you are running locally, " +
          "start it with: cd backend && make serve",
      },
      { status: 503 },
    );
  }

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    return NextResponse.json(detail, { status: response.status });
  }

  const session = await response.json();
  if (session.role !== "state_admin") {
    // The API would refuse /reports/state anyway; refusing here means the
    // reviewer gets an explanation instead of an empty page.
    return NextResponse.json(
      { detail: "This surface is for state-level accounts. Use the district dashboard." },
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
