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

export function setSession(token: string, worker: Worker): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
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
    localStorage.removeItem(WORKER_KEY);
  } catch {
    /* ignore */
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
// Phase 6 replaces this with real phone OTP. The PWA only needs the token and
// the worker's scope, both of which keep the same shape, so this call is the
// single thing that changes here.

export async function signIn(phone: string): Promise<{ token: string; worker: Worker }> {
  const body = await request<{
    access_token: string;
    role: string;
    awc_code: string | null;
    district: string | null;
  }>("/auth/dev/token", { method: "POST", body: JSON.stringify({ phone }) });

  const token = body.access_token;
  // /me is the authoritative source for scope; the token response is a
  // convenience. Asking the server who we are avoids trusting a decoded claim.
  const me = await (async () => {
    const headers = new Headers({ Authorization: `Bearer ${token}` });
    const response = await fetch(`${BASE}/me`, { headers });
    if (!response.ok) throw await toApiError(response);
    return response.json();
  })();

  return {
    token,
    worker: {
      workerId: me.worker_id,
      name: me.name,
      role: me.role,
      awcCode: me.awc_code,
      district: me.district,
    },
  };
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
