import { useEffect, useState } from "react";
import * as api from "../api/client";
import { ChildPicker } from "../components/ChildPicker";
import { useAnnounce, useOnline } from "../components/hooks";
import { AlertIcon, CheckIcon } from "../components/Icon";
import { enqueue, listBeneficiaries, newId } from "../db/queue";
import type { CachedBeneficiary, QueuedGrowth } from "../db/schema";
import { useI18n } from "../i18n/I18nProvider";
import type { StringKey } from "../i18n/strings";

/**
 * Height and weight entry.
 *
 * The classification is never computed here. Section 6.4 is categorical that
 * a child's nutritional status is deterministic WHO arithmetic over vendored
 * reference tables, and putting a copy of those tables in a phone bundle would
 * create a second implementation that can silently drift from the audited one.
 * So the device records the measurement and the server returns the status.
 *
 * The consequence is honest rather than hidden: recording works offline, but
 * the status appears when the entry syncs. The worker is told that in their own
 * language instead of being shown a blank field.
 */

const CLASS_LABEL: Record<string, StringKey> = {
  normal: "classNormal",
  MAM: "classMam",
  SAM: "classSam",
  stunted: "classStunted",
  underweight: "classUnderweight",
};

export function Growth() {
  const { t } = useI18n();
  const announce = useAnnounce();
  const online = useOnline();
  const worker = api.getWorker();

  const [children, setChildren] = useState<CachedBeneficiary[]>([]);
  const [childId, setChildId] = useState("");
  const [height, setHeight] = useState("");
  const [weight, setWeight] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ classification: string; notes: string[] } | null>(null);
  const [queuedOffline, setQueuedOffline] = useState(false);

  useEffect(() => {
    void listBeneficiaries().then(setChildren);
  }, []);

  const parse = (raw: string): number | null => {
    const value = Number.parseFloat(raw.replace(",", "."));
    return Number.isFinite(value) && value > 0 ? value : null;
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    setQueuedOffline(false);

    const heightCm = parse(height);
    const weightKg = parse(weight);
    if (!childId) return setError(t("noChildSelected"));
    if (heightCm === null || weightKg === null) return setError(t("invalidNumber"));

    setBusy(true);
    const child = children.find((c) => c.id === childId);
    const recordedAt = new Date().toISOString().slice(0, 10);

    const queued: QueuedGrowth = {
      id: newId(),
      kind: "growth",
      status: "pending",
      beneficiaryId: childId,
      beneficiaryName: child?.name ?? "",
      awcCode: worker?.awcCode ?? child?.awcCode ?? "",
      recordedAt,
      heightCm,
      weightKg,
      attempts: 0,
      createdAt: new Date().toISOString(),
    };

    try {
      // Queued first, sent second. If the request fails, the measurement is
      // already durable -- the worker does not have to remember the numbers
      // and re-enter them later.
      await enqueue(queued);

      if (!online) {
        setQueuedOffline(true);
        announce(t("growthSaved"));
        return;
      }

      const response = await api.recordGrowth({ beneficiaryId: childId, recordedAt, heightCm, weightKg });
      const { entry, notes } = response;

      await enqueue({
        ...queued,
        status: "synced",
        serverId: entry.id,
        classification: entry.classification,
        attempts: 1,
        lastAttemptAt: new Date().toISOString(),
      });

      // The server flags biologically implausible readings (WHO Anthro
      // bounds). Surfacing that as "measure again" is far more useful to the
      // worker than a status computed from a typo.
      if (entry.data_quality_flags.length > 0) {
        setError(t("implausibleReading"));
      }
      setResult({ classification: entry.classification, notes });
      announce(t("growthSaved"));
    } catch {
      setQueuedOffline(true);
      announce(t("growthSaved"));
    } finally {
      setBusy(false);
      setHeight("");
      setWeight("");
    }
  };

  const classKey = result ? CLASS_LABEL[result.classification] : undefined;
  const severe = result?.classification === "SAM";

  return (
    <main className="app__main" id="main">
      <h2 className="section-title">{t("growthTitle")}</h2>

      {!online && (
        <div className="banner banner--offline" role="status">
          <AlertIcon size={20} />
          <span className="banner__body">{t("growthNeedsInternet")}</span>
        </div>
      )}

      <form onSubmit={submit} noValidate>
        <ChildPicker children={children} value={childId} onChange={setChildId} />

        <div className="field">
          <label className="field__label" htmlFor="height">
            {t("heightLabel")}
          </label>
          <input
            id="height"
            className="input numeric"
            type="text"
            // `decimal` rather than `numeric`: a height is 88.5, and the
            // numeric pad on Android has no decimal point.
            inputMode="decimal"
            value={height}
            onChange={(e) => setHeight(e.target.value)}
            aria-describedby="height-hint"
            required
          />
          <span className="field__hint" id="height-hint">
            {t("heightHint")}
          </span>
        </div>

        <div className="field">
          <label className="field__label" htmlFor="weight">
            {t("weightLabel")}
          </label>
          <input
            id="weight"
            className="input numeric"
            type="text"
            inputMode="decimal"
            value={weight}
            onChange={(e) => setWeight(e.target.value)}
            aria-describedby="weight-hint"
            required
          />
          <span className="field__hint" id="weight-hint">
            {t("weightHint")}
          </span>
        </div>

        {error && (
          <p className="field__error" role="alert">
            <AlertIcon size={18} />
            <span>{error}</span>
          </p>
        )}

        <button type="submit" className="btn btn--primary btn--block btn--capture" disabled={busy}>
          {busy ? <span className="spinner" /> : null}
          {busy ? t("loading") : t("saveGrowth")}
        </button>
      </form>

      {queuedOffline && (
        <div className="banner banner--success" role="status" style={{ marginTop: "var(--space-5)" }}>
          <CheckIcon size={20} />
          <div className="banner__body">
            <strong className="banner__title">{t("growthSaved")}</strong>
            <div>{t("captureSavedDetail")}</div>
          </div>
        </div>
      )}

      {result && classKey && (
        <div
          className={`banner ${severe ? "banner--error" : "banner--success"}`}
          role="status"
          style={{ marginTop: "var(--space-5)" }}
        >
          {severe ? <AlertIcon size={20} /> : <CheckIcon size={20} />}
          <div className="banner__body">
            <strong className="banner__title">
              {t("classification")}: {t(classKey)}
            </strong>
            {/* Severe acute malnutrition is a referral today, not a statistic.
                The worker gets told what to do, not just what was measured. */}
            {severe && <div>{t("samAdvice")}</div>}
          </div>
        </div>
      )}
    </main>
  );
}
