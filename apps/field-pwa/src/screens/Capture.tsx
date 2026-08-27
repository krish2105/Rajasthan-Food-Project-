import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { detectCapability, grabFrame, openStream, stopStream } from "../capture/camera";
import type { CaptureMode } from "../capture/camera";
import { blobToArrayBuffer } from "../capture/bytes";
import { MAX_COMPRESSED_BYTES, compressPhoto } from "../capture/compress";
import { ChildPicker } from "../components/ChildPicker";
import { useAnnounce } from "../components/hooks";
import { AlertIcon, CameraIcon, CheckIcon } from "../components/Icon";
import { enqueue, listBeneficiaries, newId } from "../db/queue";
import { ensureRoom } from "../db/storage";
import type { CachedBeneficiary, QueuedCapture } from "../db/schema";
import { useI18n } from "../i18n/I18nProvider";

/**
 * Plate capture -- the screen that gets used dozens of times a day.
 *
 * Two capture paths, per the decision recorded in Phase 3's plan: an in-app
 * viewfinder where it works, the phone's own camera app where it does not. The
 * file input is not a degraded mode bolted on afterwards; it is the default
 * that the viewfinder has to earn its way past, because it is what runs on the
 * oldest devices in the pilot.
 *
 * Nothing here awaits the network. `save` writes to IndexedDB and returns --
 * Section 7's rule is that the worker never waits for an upload to move to the
 * next plate, and the cleanest way to guarantee that is for this screen to have
 * no code path that could wait.
 */

type Stage = "form" | "viewfinder" | "review" | "saved";

export function Capture() {
  const { t } = useI18n();
  const announce = useAnnounce();
  const worker = api.getWorker();

  const [children, setChildren] = useState<CachedBeneficiary[]>([]);
  const [childId, setChildId] = useState("");
  const [mealType, setMealType] = useState<"breakfast" | "lunch" | "thr">("lunch");
  const [stage, setStage] = useState<Stage>("form");
  const [mode, setMode] = useState<CaptureMode>(() => detectCapability().mode);
  const [photo, setPhoto] = useState<Blob | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void listBeneficiaries().then(setChildren);
  }, []);

  // The preview object URL is revoked on replacement and on unmount; leaking
  // these keeps decoded bitmaps alive, which on a 1 GB phone is the difference
  // between a smooth session and the tab being killed mid-shift.
  useEffect(() => {
    if (!photo) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(photo);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  const closeCamera = useCallback(() => {
    stopStream(streamRef.current);
    streamRef.current = null;
  }, []);

  useEffect(() => closeCamera, [closeCamera]);

  const openFilePicker = useCallback(() => {
    setMode("file-input");
    setStage("form");
    fileRef.current?.click();
  }, []);

  const startCapture = useCallback(async () => {
    if (!childId) {
      setError(t("noChildSelected"));
      return;
    }
    setError(null);

    if (mode === "file-input") {
      openFilePicker();
      return;
    }

    const { stream, fallback, reason } = await openStream();
    if (fallback || !stream) {
      // Every viewfinder failure lands here, and lands the worker in the
      // system camera rather than on an error screen. A permission denial, an
      // insecure context and an unsupported WebView are all the same event as
      // far as someone holding a plate is concerned.
      setNotice(reason === "NotAllowedError" ? t("cameraPermission") : t("cameraUnavailable"));
      openFilePicker();
      return;
    }
    streamRef.current = stream;
    setStage("viewfinder");
    // Assigned after the stage switch so the <video> element exists.
    window.setTimeout(() => {
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        void videoRef.current.play().catch(() => {
          setNotice(t("cameraUnavailable"));
          closeCamera();
          openFilePicker();
        });
      }
    }, 0);
  }, [childId, mode, t, openFilePicker, closeCamera]);

  const takeFromViewfinder = useCallback(async () => {
    if (!videoRef.current) return;
    try {
      const raw = await grabFrame(videoRef.current);
      closeCamera();
      setPhoto(raw);
      setStage("review");
    } catch {
      setNotice(t("cameraUnavailable"));
      closeCamera();
      openFilePicker();
    }
  }, [closeCamera, openFilePicker, t]);

  const onFileChosen = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // Reset so choosing the same file twice still fires a change event.
    event.target.value = "";
    if (!file) return;
    setPhoto(file);
    setStage("review");
  };

  const save = async () => {
    if (!photo || !childId) return;
    setBusy(true);
    setError(null);
    try {
      const child = children.find((c) => c.id === childId);
      const compressed = await compressPhoto(photo);

      if (compressed.bytes > MAX_COMPRESSED_BYTES) {
        setError(t("photoTooLarge"));
        return;
      }

      // Sheds original files from older queued captures if the device is
      // filling up, before adding another one.
      const { low } = await ensureRoom();

      const item: QueuedCapture = {
        id: newId(),
        kind: "capture",
        status: "pending",
        beneficiaryId: childId,
        beneficiaryName: child?.name ?? "",
        awcCode: worker?.awcCode ?? child?.awcCode ?? "",
        mealType,
        capturedAt: new Date().toISOString(),
        photoData: await blobToArrayBuffer(compressed.blob),
        photoType: compressed.blob.type || "image/jpeg",
        // Held until the server confirms receipt, then dropped by the sync
        // engine. Skipped entirely when the photo passed through uncompressed,
        // since there would be nothing to compare it against.
        originalData: compressed.passthrough ? undefined : await blobToArrayBuffer(photo),
        photoBytes: compressed.bytes,
        originalBytes: compressed.passthrough ? 0 : compressed.originalBytes,
        attempts: 0,
        createdAt: new Date().toISOString(),
      };

      await enqueue(item);
      if (low) setNotice(t("storageLow"));

      setStage("saved");
      announce(t("captureSaved"));
    } catch {
      setError(t("errorGeneric"));
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setPhoto(null);
    setStage("form");
    setError(null);
  };

  // --- Viewfinder ---------------------------------------------------------
  if (stage === "viewfinder") {
    return (
      <main className="app__main" id="main">
        <div className="stack">
          <p className="banner banner--info" role="note">
            <AlertIcon size={20} />
            <span className="banner__body">{t("plateOnly")}</span>
          </p>
          <video
            ref={videoRef}
            playsInline
            muted
            aria-label={t("captureTitle")}
            style={{
              width: "100%",
              borderRadius: "var(--radius-lg)",
              background: "var(--color-surface-sunken)",
              aspectRatio: "3 / 4",
              objectFit: "cover",
            }}
          />
          <button type="button" className="btn btn--primary btn--block btn--capture" onClick={takeFromViewfinder}>
            <CameraIcon />
            {t("takePhoto")}
          </button>
          <button
            type="button"
            className="btn btn--secondary btn--block"
            onClick={() => {
              closeCamera();
              setStage("form");
            }}
          >
            {t("cancel")}
          </button>
        </div>
      </main>
    );
  }

  // --- Review -------------------------------------------------------------
  if (stage === "review" && previewUrl) {
    return (
      <main className="app__main" id="main">
        <div className="stack">
          <img
            src={previewUrl}
            alt={t("captureTitle")}
            style={{ width: "100%", borderRadius: "var(--radius-lg)" }}
          />
          {error && (
            <p className="field__error" role="alert">
              <AlertIcon size={18} />
              <span>{error}</span>
            </p>
          )}
          <button
            type="button"
            className="btn btn--primary btn--block btn--capture"
            onClick={save}
            disabled={busy}
          >
            {busy ? <span className="spinner" /> : <CheckIcon />}
            {busy ? t("loading") : t("usePhoto")}
          </button>
          <button type="button" className="btn btn--secondary btn--block" onClick={reset}>
            {t("retakePhoto")}
          </button>
        </div>
      </main>
    );
  }

  // --- Saved --------------------------------------------------------------
  if (stage === "saved") {
    return (
      <main className="app__main" id="main">
        <div className="stack text-center" style={{ paddingTop: "var(--space-7)" }}>
          <div style={{ color: "var(--color-success)" }}>
            <CheckIcon size={64} />
          </div>
          <h2 className="section-title">{t("captureSaved")}</h2>
          {/* Says explicitly that the work is safe and will send itself. A
              worker with no signal needs to be told that, not left to infer it
              from an absence of errors. */}
          <p className="text-secondary">{t("captureSavedDetail")}</p>
          <button
            type="button"
            className="btn btn--primary btn--block btn--capture"
            onClick={() => {
              setChildId("");
              reset();
            }}
          >
            <CameraIcon />
            {t("captureAnother")}
          </button>
        </div>
      </main>
    );
  }

  // --- Form ---------------------------------------------------------------
  return (
    <main className="app__main" id="main">
      <h2 className="section-title">{t("captureTitle")}</h2>

      {notice && (
        <div className="banner banner--info" role="status">
          <AlertIcon size={20} />
          <span className="banner__body">{notice}</span>
        </div>
      )}

      <ChildPicker children={children} value={childId} onChange={setChildId} />

      <fieldset className="field" style={{ border: 0, padding: 0 }}>
        <legend className="field__label">{t("mealType")}</legend>
        <select
          className="select"
          value={mealType}
          onChange={(e) => setMealType(e.target.value as typeof mealType)}
          aria-label={t("mealType")}
        >
          <option value="breakfast">{t("mealBreakfast")}</option>
          <option value="lunch">{t("mealLunch")}</option>
          <option value="thr">{t("mealThr")}</option>
        </select>
      </fieldset>

      {error && (
        <p className="field__error" role="alert">
          <AlertIcon size={18} />
          <span>{error}</span>
        </p>
      )}

      <button
        type="button"
        className="btn btn--primary btn--block btn--capture"
        onClick={startCapture}
      >
        <CameraIcon />
        {t("takePhoto")}
      </button>

      {/* Always mounted, never visible. Both capture paths funnel through it,
          so the fallback cannot be broken by a state the viewfinder left behind. */}
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={onFileChosen}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        data-testid="file-input"
      />

      <p className="field__hint" style={{ marginTop: "var(--space-4)" }}>
        {t("plateOnly")}
      </p>
    </main>
  );
}
