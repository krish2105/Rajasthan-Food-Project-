/**
 * The statistics behind the distribution chart.
 *
 * The WHO reference curve is drawn from the definition of a z-score rather than
 * from data: by construction, the reference population is standard normal with
 * mean 0 and SD 1. That is not an approximation of anything -- it is what a
 * z-score means, which is precisely why overlaying the cohort on it is a fair
 * comparison rather than a rhetorical one.
 */

/** Standard normal density. */
export function normalPdf(z: number, mean = 0, sd = 1): number {
  const a = (z - mean) / sd;
  return Math.exp(-0.5 * a * a) / (sd * Math.SQRT2 * Math.sqrt(Math.PI));
}

/**
 * Expected counts per histogram bin if the cohort matched the WHO reference.
 *
 * Scaled to the cohort's own size, so the two curves are directly comparable:
 * the gap between them is the finding, and it would be meaningless if one were
 * a density and the other a count.
 */
export function referenceCounts(
  bins: { z: number }[],
  total: number,
  binWidth: number,
): number[] {
  return bins.map((bin) => {
    // Density at the bin's midpoint times bin width times n.
    const mid = bin.z + binWidth / 2;
    return normalPdf(mid) * binWidth * total;
  });
}

/**
 * The share of the WHO reference population below a z-score.
 *
 * Used to state the comparison in words: 2.3% of a healthy reference population
 * sits below -2 SD. Abramowitz & Stegun 7.1.26 approximation of erf, accurate
 * to ~1e-7, which is well past what a percentage on a slide needs.
 */
export function normalCdf(z: number): number {
  const sign = z < 0 ? -1 : 1;
  const x = Math.abs(z) / Math.SQRT2;
  const t = 1 / (1 + 0.3275911 * x);
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t +
      0.254829592) *
      t *
      Math.exp(-x * x);
  return 0.5 * (1 + sign * y);
}

/** WHO cut-offs, in SD. Marked on every chart that shows a z-axis. */
export const CUTOFFS = [
  { z: -3, label: "−3 SD", meaning: "severe" },
  { z: -2, label: "−2 SD", meaning: "moderate" },
] as const;
