import { useEffect, useState } from "react";
import * as api from "../api/client";
import { useI18n } from "../i18n/I18nProvider";
import { useTheme } from "../theme/ThemeProvider";
import type { Theme } from "../theme/ThemeProvider";
import type { Lang } from "../i18n/strings";
import { cacheBeneficiaries, clearAll, counts, getMeta, listAwcs } from "../db/queue";
import { estimate, formatBytes } from "../db/storage";
import * as apiClient from "../api/client";
import { AlertIcon, SunIcon } from "../components/Icon";
import type { CachedAwc } from "../db/schema";

/**
 * Settings: language, appearance, storage, sign-out.
 *
 * Both controls are radio groups rather than dropdowns or a cycling button.
 * Every option is visible without an interaction, each one is a full-width
 * touch target, and the current state is obvious at a glance -- all of which
 * matter more than compactness for a user who may not be confident with apps
 * (Section 9.1).
 */

function OptionRow({
  checked,
  onChange,
  name,
  label,
  hint,
  icon,
}: {
  checked: boolean;
  onChange: () => void;
  name: string;
  label: string;
  hint?: string;
  icon?: React.ReactNode;
}) {
  return (
    <label
      className="card"
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--space-3)",
        minHeight: "var(--touch-comfortable)",
        cursor: "pointer",
        borderColor: checked ? "var(--color-accent)" : "var(--color-border)",
        borderWidth: checked ? 2 : "var(--border-width)",
      }}
    >
      <input
        type="radio"
        name={name}
        checked={checked}
        onChange={onChange}
        style={{ width: 22, height: 22, accentColor: "var(--color-accent)" }}
      />
      {icon}
      <span style={{ flex: 1 }}>
        <span style={{ fontWeight: "var(--weight-emphasis)" }}>{label}</span>
        {hint && <span className="field__hint" style={{ marginTop: 2 }}>{hint}</span>}
      </span>
    </label>
  );
}

export function Settings({ onSignedOut }: { onSignedOut: () => void }) {
  const { t, lang, setLang } = useI18n();
  const { theme, setTheme } = useTheme();
  const worker = api.getWorker();

  const [storage, setStorage] = useState({ used: 0, quota: 0, supported: false });
  const [pending, setPending] = useState(0);
  const [lastSync, setLastSync] = useState<string | undefined>();
  const [awc, setAwc] = useState<CachedAwc | undefined>();
  const [confirmSignOut, setConfirmSignOut] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    void (async () => {
      const [est, queue, updated, awcs] = await Promise.all([
        estimate(),
        counts(),
        getMeta<string>("beneficiariesUpdatedAt"),
        listAwcs(),
      ]);
      setStorage({ used: est.usageBytes, quota: est.quotaBytes, supported: est.supported });
      setPending(queue.pending + queue.failed + queue.syncing);
      setLastSync(updated);
      setAwc(awcs.find((a) => a.awcCode === worker?.awcCode) ?? awcs[0]);
    })();
  }, [worker?.awcCode]);

  const refreshChildren = async () => {
    setRefreshing(true);
    try {
      const rows = await apiClient.fetchBeneficiaries();
      await cacheBeneficiaries(
        rows.map((r) => ({
          id: r.id,
          name: r.name,
          awcCode: r.awc_code,
          dob: r.dob,
          gender: r.gender,
          ageMonths: r.age_months ?? 0,
          poshanTrackerId: r.poshan_tracker_id,
        })),
      );
      setLastSync(new Date().toISOString());
    } catch {
      /* offline; the cached list stays usable, which is the point */
    } finally {
      setRefreshing(false);
    }
  };

  const signOut = async () => {
    await clearAll();
    api.clearSession();
    onSignedOut();
  };

  return (
    <main className="app__main" id="main">
      <h2 className="section-title">{t("settingsTitle")}</h2>

      {awc && (
        <div className="card">
          <div className="card__meta">{t("centre")}</div>
          <div className="card__title">{lang === "hi" ? awc.nameHi : awc.nameEn}</div>
          <div className="card__meta">
            {lang === "hi" ? `${awc.blockHi}, ${awc.districtHi}` : `${awc.block}, ${awc.district}`}
          </div>
        </div>
      )}

      <section style={{ marginTop: "var(--space-6)" }}>
        <h3 className="section-title" id="lang-heading">
          {t("language")}
        </h3>
        <div role="radiogroup" aria-labelledby="lang-heading">
          {(["hi", "en"] as Lang[]).map((option) => (
            <OptionRow
              key={option}
              name="language"
              checked={lang === option}
              onChange={() => setLang(option)}
              label={option === "hi" ? "हिन्दी" : "English"}
            />
          ))}
        </div>
      </section>

      <section style={{ marginTop: "var(--space-6)" }}>
        <h3 className="section-title" id="theme-heading">
          {t("theme")}
        </h3>
        <div role="radiogroup" aria-labelledby="theme-heading">
          {(["light", "dark", "system", "sunlight"] as Theme[]).map((option) => (
            <OptionRow
              key={option}
              name="theme"
              checked={theme === option}
              onChange={() => setTheme(option)}
              icon={option === "sunlight" ? <SunIcon size={22} /> : undefined}
              label={
                option === "light"
                  ? t("themeLight")
                  : option === "dark"
                    ? t("themeDark")
                    : option === "system"
                      ? t("themeSystem")
                      : t("themeSunlight")
              }
              hint={option === "sunlight" ? t("themeSunlightHint") : undefined}
            />
          ))}
        </div>
      </section>

      <section style={{ marginTop: "var(--space-6)" }}>
        <h3 className="section-title">{t("storageTitle")}</h3>
        <div className="card">
          {storage.supported ? (
            <>
              <div className="row row--between">
                <span>{t("storageUsed")}</span>
                <span className="numeric">
                  {formatBytes(storage.used)} / {formatBytes(storage.quota)}
                </span>
              </div>
              {storage.quota > 0 && storage.used / storage.quota >= 0.7 && (
                <p className="field__error" style={{ marginTop: "var(--space-3)" }}>
                  <AlertIcon size={16} />
                  <span>{t("storageLow")}</span>
                </p>
              )}
            </>
          ) : (
            <span className="text-secondary">—</span>
          )}
          <div className="row row--between" style={{ marginTop: "var(--space-3)" }}>
            <span>{t("lastUpdated")}</span>
            <span className="numeric">
              {lastSync ? new Date(lastSync).toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN") : t("never")}
            </span>
          </div>
          <button
            type="button"
            className="btn btn--secondary btn--block"
            style={{ marginTop: "var(--space-4)" }}
            onClick={refreshChildren}
            disabled={refreshing}
          >
            {refreshing ? <span className="spinner" /> : null}
            {t("refreshChildren")}
          </button>
        </div>
      </section>

      <section style={{ marginTop: "var(--space-7)" }}>
        {confirmSignOut ? (
          <div className="banner banner--error" role="alertdialog">
            <AlertIcon size={20} />
            <div className="banner__body">
              {/* Signing out clears the local queue, so unsent work is warned
                  about explicitly rather than lost quietly. */}
              {pending > 0 && <div>{t("signOutWarning")}</div>}
              <div className="row" style={{ marginTop: "var(--space-3)" }}>
                <button type="button" className="btn btn--danger" onClick={signOut}>
                  {t("confirm")}
                </button>
                <button
                  type="button"
                  className="btn btn--secondary"
                  onClick={() => setConfirmSignOut(false)}
                >
                  {t("cancel")}
                </button>
              </div>
            </div>
          </div>
        ) : (
          <button
            type="button"
            className="btn btn--secondary btn--block"
            onClick={() => setConfirmSignOut(true)}
          >
            {t("signOut")}
          </button>
        )}
      </section>
    </main>
  );
}
