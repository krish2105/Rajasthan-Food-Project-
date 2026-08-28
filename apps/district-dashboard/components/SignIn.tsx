"use client";

import { useState } from "react";

/**
 * Phone-OTP sign-in for the desktop surfaces.
 *
 * Two steps, one field each. The tokens never touch this component: the form
 * posts to a route handler that writes httpOnly cookies, and only the
 * reviewer's name comes back.
 *
 * Deliberately quieter than the page it guards. A sign-in screen is a door, not
 * an argument, and nobody should be persuaded of anything before they have
 * proved who they are.
 */

interface DemoAccount {
  phone: string;
  role: string;
  name: string;
  district: string | null;
}

interface Props {
  title: string;
  subtitle: string;
  /** Set by the server when a session existed but was rejected or expired. */
  reason?: string;
  onSignedIn?: () => void;
}

export function SignIn({ title, subtitle, reason, onSignedIn }: Props) {
  const [stage, setStage] = useState<"phone" | "code">("phone");
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(reason ?? null);
  const [demoCode, setDemoCode] = useState<string | null>(null);
  const [registered, setRegistered] = useState<boolean | null>(null);
  const [accounts, setAccounts] = useState<DemoAccount[]>([]);

  const post = async (path: string, body: unknown) => {
    const response = await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail ?? payload.code ?? "Something went wrong.");
    }
    return payload;
  };

  const sendCode = async (event?: React.FormEvent) => {
    event?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await post("/auth/start", { phone: phone.trim() });
      setDemoCode(result.debug_code ?? null);
      // Present only in development. The API deliberately will not say whether
      // a number is registered in its public response, but without knowing here
      // a demo hands you a correct code for an unregistered number and then
      // rejects it, which looks like a broken sign-in.
      setRegistered(result.debug_registered ?? null);
      setAccounts(result.debug_accounts ?? []);
      setStage("code");
      setOtp("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send a code.");
    } finally {
      setBusy(false);
    }
  };

  const verify = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/auth/finish", { phone: phone.trim(), otp: otp.trim() });
      if (onSignedIn) onSignedIn();
      else window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That code is not valid.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main
      style={{
        minHeight: "100dvh",
        display: "grid",
        placeItems: "center",
        padding: "var(--space-5)",
      }}
    >
      <div style={{ width: "min(100%, 420px)" }}>
        <p className="eyebrow">{subtitle}</p>
        <h1 style={{ fontSize: "var(--step-2)", marginTop: "var(--space-3)" }}>{title}</h1>

        <form
          onSubmit={stage === "phone" ? sendCode : verify}
          style={{ marginTop: "var(--space-6)" }}
        >
          {stage === "phone" ? (
            <label style={{ display: "block" }}>
              <span style={{ display: "block", marginBottom: "var(--space-2)" }}>
                Mobile number
              </span>
              <input
                className="input"
                type="tel"
                inputMode="numeric"
                autoComplete="tel"
                maxLength={10}
                value={phone}
                onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 10))}
                aria-invalid={error ? true : undefined}
                autoFocus
                required
                style={{
                  width: "100%",
                  minHeight: 44,
                  padding: "0 var(--space-3)",
                  font: "inherit",
                  fontFamily: "var(--font-mono)",
                  color: "var(--text)",
                  background: "var(--ink-700)",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius)",
                }}
              />
            </label>
          ) : (
            <>
              <p style={{ color: "var(--text-secondary)", marginBottom: "var(--space-4)" }}>
                Code sent to <span className="num">{phone}</span>{" "}
                <button
                  type="button"
                  onClick={() => {
                    setStage("phone");
                    setError(null);
                    setDemoCode(null);
                  }}
                  style={{
                    background: "none",
                    border: 0,
                    color: "var(--indigo)",
                    font: "inherit",
                    textDecoration: "underline",
                    cursor: "pointer",
                  }}
                >
                  Change
                </button>
              </p>

              {/* Populated only by the console provider outside production, so
                  a demo does not require reading a server log. A real SMS
                  provider never returns the code. */}
              {demoCode && registered !== false && (
                <p className="note" style={{ marginBottom: "var(--space-4)" }}>
                  Demo code: <strong className="num">{demoCode}</strong>
                </p>
              )}

              {/* The number is not staff, so the code will be refused however
                  correctly it is typed. Saying so, and naming the accounts that
                  do work, turns a dead end into a two-second fix. */}
              {registered === false && (
                <div
                  className="note"
                  style={{ marginBottom: "var(--space-4)", borderLeftColor: "var(--moderate)" }}
                >
                  <strong style={{ color: "var(--moderate)" }}>
                    {phone} is not a registered account.
                  </strong>
                  <div style={{ marginTop: "var(--space-2)" }}>
                    A code was generated, but sign-in will refuse it. Use one of
                    the seeded accounts:
                  </div>
                  <ul style={{ margin: "var(--space-3) 0 0", paddingLeft: "1.1rem" }}>
                    {accounts.map((account) => (
                      <li key={account.phone} style={{ marginBottom: 4 }}>
                        <button
                          type="button"
                          onClick={() => {
                            setPhone(account.phone);
                            setStage("phone");
                            setRegistered(null);
                            setError(null);
                          }}
                          className="num"
                          style={{
                            background: "none",
                            border: 0,
                            padding: 0,
                            color: "var(--indigo)",
                            font: "inherit",
                            fontFamily: "var(--font-mono)",
                            textDecoration: "underline",
                            cursor: "pointer",
                          }}
                        >
                          {account.phone}
                        </button>{" "}
                        — {account.role.replace(/_/g, " ")}
                        {account.district ? `, ${account.district}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <label style={{ display: "block" }}>
                <span style={{ display: "block", marginBottom: "var(--space-2)" }}>
                  6-digit code
                </span>
                <input
                  className="input"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  aria-invalid={error ? true : undefined}
                  autoFocus
                  required
                  style={{
                    width: "100%",
                    minHeight: 44,
                    padding: "0 var(--space-3)",
                    font: "inherit",
                    fontFamily: "var(--font-mono)",
                    letterSpacing: "0.35em",
                    color: "var(--text)",
                    background: "var(--ink-700)",
                    border: "1px solid var(--line)",
                    borderRadius: "var(--radius)",
                  }}
                />
              </label>
            </>
          )}

          {error && (
            <p role="alert" style={{ color: "var(--severe)", marginTop: "var(--space-3)" }}>
              {error}
            </p>
          )}

          <button
            type="submit"
            className="btn"
            disabled={
              busy || (stage === "phone" ? phone.length !== 10 : otp.length !== 6)
            }
            style={{ marginTop: "var(--space-5)", width: "100%" }}
          >
            {busy ? "…" : stage === "phone" ? "Send code" : "Sign in"}
          </button>
        </form>
      </div>
    </main>
  );
}
