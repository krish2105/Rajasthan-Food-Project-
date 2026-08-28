/** Shapes returned by the worklist and report endpoints. */

export interface FlaggedDay {
  id: string;
  awc_code: string;
  district: string;
  date: string;
  name_en: string;
  name_hi: string;
  block: string;
  block_hi: string;
  prescribed_items: string[];
  detected_items: string[];
  missing_items: string[];
  compliance_pct: number | null;
  flag_reason_en: string | null;
  flag_reason_hi: string | null;
  follow_up_id: string | null;
  follow_up_outcome: string | null;
  follow_up_note: string | null;
  follow_up_at: string | null;
  follow_up_by: string | null;
}

export interface QuietCentre {
  awc_code: string;
  name_en: string;
  name_hi: string;
  block: string;
  district: string;
  last_capture: string | null;
  total_captures: number;
}

export interface ReferralChild {
  beneficiary_id: string;
  name: string;
  gender: string;
  poshan_tracker_id: string | null;
  centre_en: string;
  centre_hi: string;
  block: string;
  classification: string;
  recorded_at: string;
  age_months: number;
  height_cm: number | null;
  weight_kg: number | null;
  haz_score: number | null;
  whz_score: number | null;
  waz_score: number | null;
  baz_score: number | null;
}

export interface TrendPoint {
  date: string;
  compliance_pct: number | null;
  flagged: boolean;
  prescribed: number;
  detected: number;
}

export interface FollowUpRecord {
  id: string;
  outcome: string;
  note: string | null;
  recorded_at: string;
}

export interface Scope {
  role: string;
  district: string | null;
  can_view_state: boolean;
}

export const OUTCOMES = [
  { value: "visited", label: "Visited the centre" },
  { value: "contacted", label: "Contacted the supervisor" },
  { value: "escalated", label: "Escalated to block office" },
  { value: "no_action_needed", label: "No action needed" },
] as const;

export const pct = (v: number | null | undefined, d = 0): string =>
  v === null || v === undefined ? "—" : `${v.toFixed(d)}%`;

export const shortDate = (iso: string): string =>
  new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });

export const daysAgo = (iso: string | null): string => {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
};
