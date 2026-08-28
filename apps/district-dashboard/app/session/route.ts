import { NextResponse } from "next/server";
import { readTokens } from "@/lib/session";

/**
 * Hands the client a usable access token.
 *
 * This dashboard writes -- an officer records a follow-up and the queue updates
 * underneath them -- so the browser needs a bearer token. It gets the
 * short-lived one only; the refresh token stays in an httpOnly cookie and is
 * never exposed. `middleware.ts` keeps the access cookie fresh, so by the time
 * this runs it is either valid or the session is genuinely over.
 *
 * The trade-off is deliberate and bounded: a script on this page could read a
 * token that expires within the hour, but not the credential that renews it.
 *
 * Phase 6 replaced the development token this route used to mint. The client
 * contract is unchanged: GET /session returns { token }.
 */

export const dynamic = "force-dynamic";

export async function GET() {
  const { access } = await readTokens();
  if (!access) {
    return NextResponse.json({ error: "not signed in" }, { status: 401 });
  }
  return NextResponse.json({ token: access });
}
