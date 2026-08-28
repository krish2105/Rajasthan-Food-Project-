/**
 * Backend client.
 *
 * Thin on purpose. Every call is expected to fail routinely -- that is the
 * normal operating condition in the Banswara belt, not an exception -- so the
 * useful shape is a small function that either resolves or throws a typed
 * error the sync engine can classify.
 *
 * Nothing here retries. Retry policy belongs to the sync engine, which knows
 * how many attempts an item has already had and can back off across app
 * launches. A retry loop buried in a fetch wrapper would fight it.
 */

const BASE = "/api";
const TOKEN_KEY = "poshannetra.token";
const REFRESH_KEY = "poshannetra.refresh";
const WORKER_KEY = "poshannetra.worker";

export interface Worker {
  workerId: string;
  name: string;
  role: string;
  awcCode: string | null;
  district: string | null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Bilingual titles from the backend's RFC 7807 problem+json responses. */
    readonly titleHi?: string,
    readonly titleEn?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /**
   * Whether retrying could ever help.
   *
   * A 4xx means the request itself is wrong -- retrying a malformed capture
   * forever just burns battery and hides the problem from the worker. 408 and
   * 429 are the exceptions: both mean "not now" rather than "not ever".
   */
  get retryable(): boolean {
    if (this.status === 0) return true; // network failure
    if (this.status === 408 || this.status === 429) return true;
    return this.status >= 500;
  }

  /** A stale or expired token; the worker has to sign in again. */
  get isAuthFailure(): boolean {
    return this.status === 401 || this.status === 403;
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

export function setSession(token: string, refreshToken: string, worker: Worker): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(REFRESH_KEY, refreshToken);
    localStorage.setItem(WORKER_KEY, JSON.stringify(worker));
  } catch {
    /* non-persistent session is still a usable session */
  }
}

export function getWorker(): Worker | null {
  try {
    const raw = localStorage.getItem(WORKER_KEY);
    return raw ? (JSON.parse(raw) as Worker) : null;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(WORKER_KEY);
  } catch {
    /* ignore */
  }
}

/**
 * Exchange the refresh token for a new access token.
 *
 * This is what reconciles Section 11's one-hour access token with Section 7's
 * requirement that the app keep working through days offline. The access token
 * expires constantly; the worker never notices, because nothing they do -- take
 * a photograph, record a weight -- consults it. Only syncing does, and syncing
 * already assumes the network is absent most of the time.
 *
 * Returns false when the refresh token itself is gone or rejected, which is the
 * only case where the worker genuinely has to sign in again.
 */
export async function refreshSession(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;
  try {
    const response = await fetch(`${BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) {
      // A 401 means the token is spent, revoked or reused. Anything else is a
      // server or network problem, and the session should survive it -- an
      // outage must not sign a worker out mid-shift.
      if (response.status === 401) clearSession();
      return false;
    }
    const body = (await response.json()) as SessionResponse;
    setSession(body.access_token, body.refresh_token, toWorker(body));
    return true;
  } catch {
    // Network failure. Keep the session; this will be retried when signal
    // returns.
    return false;
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  let titleHi: string | undefined;
  let titleEn: string | undefined;
  let detail = response.statusText;
  try {
    const body = await response.json();
    titleHi = body.title_hi;
    titleEn = body.title_en;
    detail = body.detail ?? body.code ?? detail;
  } catch {
    /* not problem+json; the status alone will have to do */
  }
  return new ApiError(detail, response.status, titleHi, titleEn);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch (error) {
    // fetch rejects on DNS failure, no route to host, aeroplane mode. Status 0
    // is our marker for "the network, not the server, said no".
    throw new ApiError(
      error instanceof Error ? error.message : "network unavailable",
      0,
    );
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// --- Auth -----------------------------------------------------------------
// Phone OTP (Sections 4, 10). Two steps: request a code, then exchange it for
// an access token and a long-lived refresh token.

interface SessionResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  refresh_expires_at: string;
  role: string;
  name: string;
  awc_code: string | null;
  district: string | null;
}

function toWorker(body: SessionResponse): Worker {
  return {
    workerId: "",
    name: body.name,
    role: body.role,
    awcCode: body.awc_code,
    district: body.district,
  };
}

export interface OtpRequestResult {
  expiresIn: number;
  messageHi: string;
  messageEn: string;
  /** Only present outside production with the console provider, for demos. */
  debugCode?: string;
}

export async function requestOtp(phone: string): Promise<OtpRequestResult> {
  const body = await request<{
    expires_in: number;
    message_hi: string;
    message_en: string;
    debug_code?: string;
  }>("/auth/otp/request", { method: "POST", body: JSON.stringify({ phone }) });
  return {
    expiresIn: body.expires_in,
    messageHi: body.message_hi,
    messageEn: body.message_en,
    debugCode: body.debug_code,
  };
}

export async function verifyOtp(phone: string, otp: string): Promise<Worker> {
  const body = await request<SessionResponse>("/auth/otp/verify", {
    method: "POST",
    body: JSON.stringify({ phone, otp }),
  });
  const worker = toWorker(body);
  setSession(body.access_token, body.refresh_token, worker);
  return worker;
}

export async function signOut(): Promise<void> {
  const refreshToken = getRefreshToken();
  if (refreshToken) {
    try {
      await fetch(`${BASE}/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch {
      // Offline sign-out still clears the device. The token expires on its own.
    }
  }
  clearSession();
}

// --- Reference data -------------------------------------------------------

export interface ApiBeneficiary {
  id: string;
  name: string;
  awc_code: string;
  dob: string;
  gender: string;
  age_months: number | null;
  poshan_tracker_id: string | null;
}

export async function fetchBeneficiaries(): Promise<ApiBeneficiary[]> {
  const page = await request<{ items: ApiBeneficiary[]; next_cursor: string | null }>(
    "/beneficiaries?limit=200",
  );
  const items = [...page.items];
  let cursor = page.next_cursor;
  // A centre has tens of children, not thousands, so paging through fully on
  // first sync is cheap and means the offline list is genuinely complete.
  while (cursor) {
    const next = await request<{ items: ApiBeneficiary[]; next_cursor: string | null }>(
      `/beneficiaries?limit=200&cursor=${encodeURIComponent(cursor)}`,
    );
    items.push(...next.items);
    cursor = next.next_cursor;
  }
  return items;
}

export interface ApiAwc {
  awc_code: string;
  name_en: string;
  name_hi: string;
  district: string;
  district_hi: string;
  block: string;
  block_hi: string;
  centre_type: string;
}

export function fetchAwcs(): Promise<ApiAwc[]> {
  return request<ApiAwc[]>("/awcs");
}

// --- Writes ---------------------------------------------------------------

export async function uploadCapture(input: {
  beneficiaryId: string;
  mealType: string;
  capturedAt: string;
  photo: Blob;
}): Promise<{ id: string }> {
  const form = new FormData();
  form.append("beneficiary_id", input.beneficiaryId);
  form.append("meal_type", input.mealType);
  form.append("captured_at", input.capturedAt);
  form.append("photo", input.photo, "plate.jpg");
  return request<{ id: string }>("/captures", { method: "POST", body: form });
}

export interface GrowthResult {
  entry: {
    id: string;
    classification: string;
    standard_used: string;
    waz_score: number | null;
    haz_score: number | null;
    whz_score: number | null;
    baz_score: number | null;
    data_quality_flags: string[];
  };
  notes: string[];
}

export function recordGrowth(input: {
  beneficiaryId: string;
  recordedAt: string;
  heightCm: number;
  weightKg: number;
}): Promise<GrowthResult> {
  return request<GrowthResult>("/growth", {
    method: "POST",
    body: JSON.stringify({
      beneficiary_id: input.beneficiaryId,
      recorded_at: input.recordedAt,
      height_cm: input.heightCm,
      weight_kg: input.weightKg,
    }),
  });
}
