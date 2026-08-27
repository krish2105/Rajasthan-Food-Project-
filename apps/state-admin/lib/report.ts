/** Shapes returned by GET /reports/state and /reports/district/{district}. */

export interface Coverage {
  districts: number;
  centres: number;
  children: number;
  captures: number;
  growth_entries: number;
}

export interface Prevalence {
  measured: number;
  stunted: number;
  severely_stunted: number;
  underweight: number;
  severely_underweight: number;
  wasted: number;
  sam: number;
  mam: number;
  under_five: number;
  school_age: number;
  stunting_rate: number | null;
  underweight_rate: number | null;
  wasting_rate: number | null;
  sam_rate: number | null;
}

export interface DistributionBin {
  z: number;
  count: number;
}

export interface Distribution {
  index: string;
  bins: DistributionBin[];
  mean_z: number | null;
  n: number;
  bin_width: number;
}

export interface Centre {
  awc_code: string;
  name_en: string;
  name_hi: string;
  centre_type: string;
  district: string;
  district_hi: string;
  block: string;
  block_hi: string;
  latitude: number | null;
  longitude: number | null;
  children: number;
  measured: number;
  stunted: number;
  sam: number;
  menu_days: number;
  flagged_days: number;
  compliance_pct: number | null;
  captures: number;
  stunting_rate: number | null;
}

export interface TrendPoint {
  month: string;
  measured: number;
  stunted: number;
  underweight: number;
  sam: number;
  mean_haz: number | null;
  stunting_rate: number | null;
  underweight_rate: number | null;
}

export interface ComplianceSummary {
  days: number;
  flagged: number;
  mean_compliance_pct: number | null;
  first_day: string | null;
  last_day: string | null;
  flag_rate: number | null;
  top_reasons: { reason: string; count: number }[];
}

export interface DataQuality {
  flagged_measurements: number;
  captures_analysed: number;
  captures_pending: number;
  captures_from_mock: number;
  ai_is_mock: boolean;
}

export interface Report {
  scope: string;
  district: string | null;
  period: {
    first_measurement: string | null;
    last_measurement: string | null;
    generated_on: string;
  };
  coverage: Coverage;
  prevalence: Prevalence;
  distribution: Distribution;
  centres: Centre[];
  trend: TrendPoint[];
  compliance: ComplianceSummary;
  data_quality: DataQuality;
}

export const pct = (value: number | null | undefined, digits = 1): string =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;

export const num = (value: number | null | undefined): string =>
  value === null || value === undefined ? "—" : value.toLocaleString("en-IN");
