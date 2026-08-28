import { NextResponse } from "next/server";
import { clearSession, readTokens } from "@/lib/session";

export const dynamic = "force-dynamic";
const API = process.env.API_ORIGIN ?? "http://localhost:8000";

/** Revokes the refresh token server-side, then clears the cookies. */
export async function POST() {
  const { refresh } = await readTokens();
  if (refresh) {
    await fetch(`${API}/auth/logout`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
      cache: "no-store",
    }).catch(() => undefined);
  }
  await clearSession();
  return new NextResponse(null, { status: 204 });
}
