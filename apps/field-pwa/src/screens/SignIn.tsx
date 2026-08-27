import { useState } from "react";
import * as api from "../api/client";
import { useI18n } from "../i18n/I18nProvider";
import { useOnline } from "../components/hooks";
import { AlertIcon, OfflineIcon } from "../components/Icon";

/**
 * Sign-in.
 *
 * One field. Section 9.1 asks for minimal typed input, and a phone number is
 * the only thing a worker can be expected to type -- it is also how field-worker
 * apps in India actually authenticate (Section 4), rather than an email and
 * password nobody at a centre has.
 *
 * `inputMode="numeric"` brings up the number pad rather than the full keyboard,
 * which on a small screen is the difference between a comfortable target and a
 * fiddly one.
 *
 * This is the only screen that requires connectivity, and it says so plainly
 * rather than failing with a generic error. Everything after this works offline.
 */
export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const { t, alt, lang } = useI18n();
  const online = useOnline();
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Indian mobile numbers are exactly ten digits. */
  const PHONE_LENGTH = 10;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const { token, worker } = await api.signIn(phone.trim());
      api.setSession(token, worker);
      onSignedIn();
    } catch (err) {
      if (err instanceof api.ApiError && err.status === 0) {
        setError(t("signInOffline"));
      } else if (err instanceof api.ApiError && err.titleHi) {
        // The backend already speaks both languages (Phase 1's problem+json
        // carries title_hi and title_en), so there is no client string table
        // to fall out of date.
        setError(lang === "hi" ? err.titleHi : (err.titleEn ?? err.message));
      } else {
        setError(t("signInFailed"));
      }
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
          {/* The other language stays visible rather than hidden behind the
              toggle: a worker who is unsure which is which can see both. */}
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

        <form onSubmit={submit} noValidate>
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
              // Sliced here, not left to `maxLength`. The attribute is only
              // enforced for direct keyboard entry -- paste, autofill and IME
              // input can all exceed it, and an eleven-digit number would
              // enable the button and then be rejected by the server with a
              // message that does not explain why.
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
      </div>
    </main>
  );
}
