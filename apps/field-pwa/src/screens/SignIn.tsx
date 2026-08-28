import { useEffect, useState } from "react";
import * as api from "../api/client";
import { useI18n } from "../i18n/I18nProvider";
import { useOnline } from "../components/hooks";
import { AlertIcon, CheckIcon, OfflineIcon } from "../components/Icon";

/**
 * Phone-OTP sign-in (Sections 4, 10).
 *
 * Two steps, one field each. Section 9.1 asks for minimal typed input, and a
 * phone number followed by a six-digit code is close to the floor for
 * authenticating someone who has no email address and no password manager.
 *
 * This is the only screen in the app that requires connectivity, and it says so
 * rather than failing with a generic error. Once a worker is through it they
 * hold a thirty-day refresh token, so this screen should be seen roughly once a
 * month rather than once a day.
 */

type Stage = "phone" | "code";

export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const { t, alt, lang } = useI18n();
  const online = useOnline();

  const [stage, setStage] = useState<Stage>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demoCode, setDemoCode] = useState<string | null>(null);
  const [registered, setRegistered] = useState<boolean | null>(null);
  const [accounts, setAccounts] = useState<api.DemoAccount[]>([]);
  const [secondsLeft, setSecondsLeft] = useState(0);

  const PHONE_LENGTH = 10;
  const CODE_LENGTH = 6;

  // Counts the code's life down so a worker can see whether it is worth typing
  // or whether they should ask for another.
  useEffect(() => {
    if (secondsLeft <= 0) return;
    const timer = window.setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [secondsLeft]);

  const describe = (err: unknown): string => {
    if (err instanceof api.ApiError) {
      if (err.status === 0) return t("signInOffline");
      if (err.status === 429) return t("otpTooMany");
      if (err.titleHi) return lang === "hi" ? err.titleHi : (err.titleEn ?? err.message);
    }
    return t("errorGeneric");
  };

  const sendCode = async (event?: React.FormEvent) => {
    event?.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await api.requestOtp(phone.trim());
      setSecondsLeft(result.expiresIn);
      setDemoCode(result.debugCode ?? null);
      setRegistered(result.debugRegistered ?? null);
      setAccounts(result.debugAccounts ?? []);
      setStage("code");
      setCode("");
    } catch (err) {
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  };

  const verify = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.verifyOtp(phone.trim(), code.trim());
      onSignedIn();
    } catch (err) {
      setError(err instanceof api.ApiError && err.status === 401 ? t("otpWrong") : describe(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="app__main" id="main">
      <div className="stack" style={{ paddingTop: "var(--space-7)" }}>
        <div className="text-center">
          <h1 style={{ fontSize: "calc(var(--font-2xl) * var(--font-scale))" }}>
            {t("appName")}
          </h1>
          <p className="text-secondary">{t("appTagline")}</p>
          <p className="text-secondary" style={{ fontSize: "var(--font-sm)" }}>
            {alt("appName")}
          </p>
        </div>

        {!online && (
          <div className="banner banner--offline" role="status">
            <OfflineIcon size={20} />
            <div className="banner__body">
              <strong className="banner__title">{t("offlineBanner")}</strong>
              <div>{t("signInOffline")}</div>
            </div>
          </div>
        )}

        {stage === "phone" ? (
          <form onSubmit={sendCode} noValidate>
            <div className="field">
              <label className="field__label" htmlFor="phone">
                {t("phoneLabel")}
              </label>
              <input
                id="phone"
                className="input numeric"
                type="tel"
                inputMode="numeric"
                autoComplete="tel"
                pattern="[0-9]*"
                maxLength={PHONE_LENGTH}
                value={phone}
                onChange={(e) =>
                  setPhone(e.target.value.replace(/\D/g, "").slice(0, PHONE_LENGTH))
                }
                aria-describedby="phone-hint"
                aria-invalid={error ? true : undefined}
                required
              />
              <span className="field__hint" id="phone-hint">
                {t("phoneHint")}
              </span>
              {error && (
                <p className="field__error" role="alert">
                  <AlertIcon size={18} />
                  <span>{error}</span>
                </p>
              )}
            </div>
            <button
              type="submit"
              className="btn btn--primary btn--block btn--capture"
              disabled={busy || phone.length !== PHONE_LENGTH}
            >
              {busy ? <span className="spinner" /> : null}
              {busy ? t("loading") : t("signInAction")}
            </button>
          </form>
        ) : (
          <form onSubmit={verify} noValidate>
            <p className="text-secondary">
              {t("otpSentTo")} <span className="numeric">{phone}</span>{" "}
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
                  color: "var(--color-accent)",
                  font: "inherit",
                  textDecoration: "underline",
                  cursor: "pointer",
                  minHeight: "var(--touch-min)",
                }}
              >
                {t("changeNumber")}
              </button>
            </p>

            {/* Shown only when the backend is using the console provider outside
                production, so a demo does not require reading a server log. A
                real SMS provider never populates this. */}
            {demoCode && registered !== false && (
              <div className="banner banner--info" role="status">
                <CheckIcon size={20} />
                <span className="banner__body">
                  {t("otpDemoCode")}: <strong className="numeric">{demoCode}</strong>
                </span>
              </div>
            )}

            {/* The number is not staff, so the code will be refused however
                correctly it is typed. Development only; a real SMS provider
                never returns this, and the API will not reveal registration in
                its public response. */}
            {registered === false && (
              <div className="banner banner--offline" role="status">
                <AlertIcon size={20} />
                <div className="banner__body">
                  <strong className="banner__title">{t("notRegistered")}</strong>
                  <div>{t("notRegisteredHelp")}</div>
                  <ul style={{ margin: "var(--space-2) 0 0", paddingLeft: "1.1rem" }}>
                    {accounts
                      .filter((account) => account.role === "field_worker")
                      .map((account) => (
                        <li key={account.phone} style={{ marginBottom: "var(--space-1)" }}>
                          <button
                            type="button"
                            onClick={() => {
                              setPhone(account.phone);
                              setStage("phone");
                              setRegistered(null);
                              setError(null);
                            }}
                            className="numeric"
                            style={{
                              background: "none",
                              border: 0,
                              padding: 0,
                              color: "var(--color-accent)",
                              font: "inherit",
                              textDecoration: "underline",
                              cursor: "pointer",
                              minHeight: "var(--touch-min)",
                            }}
                          >
                            {account.phone}
                          </button>{" "}
                          — {account.name}
                        </li>
                      ))}
                  </ul>
                </div>
              </div>
            )}

            <div className="field">
              <label className="field__label" htmlFor="otp">
                {t("otpLabel")}
              </label>
              <input
                id="otp"
                className="input numeric"
                type="text"
                inputMode="numeric"
                // Lets the phone offer the code straight from the SMS.
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength={CODE_LENGTH}
                value={code}
                onChange={(e) =>
                  setCode(e.target.value.replace(/\D/g, "").slice(0, CODE_LENGTH))
                }
                aria-describedby="otp-hint"
                aria-invalid={error ? true : undefined}
                autoFocus
                required
              />
              <span className="field__hint" id="otp-hint">
                {t("otpHint")}
                {secondsLeft > 0 && (
                  <>
                    {" · "}
                    {t("otpExpiresIn")}{" "}
                    <span className="numeric">
                      {Math.floor(secondsLeft / 60)}:
                      {String(secondsLeft % 60).padStart(2, "0")}
                    </span>
                  </>
                )}
              </span>
              {error && (
                <p className="field__error" role="alert">
                  <AlertIcon size={18} />
                  <span>{error}</span>
                </p>
              )}
            </div>

            <button
              type="submit"
              className="btn btn--primary btn--block btn--capture"
              disabled={busy || code.length !== CODE_LENGTH}
            >
              {busy ? <span className="spinner" /> : null}
              {busy ? t("loading") : t("otpVerify")}
            </button>

            <button
              type="button"
              className="btn btn--secondary btn--block"
              style={{ marginTop: "var(--space-3)" }}
              onClick={() => void sendCode()}
              disabled={busy}
            >
              {t("otpResend")}
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
