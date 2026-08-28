import { describe, expect, it } from "vitest";
import { CUTOFFS, normalCdf, normalPdf, referenceCounts } from "@/lib/stats";

/**
 * The statistics behind the distribution chart.
 *
 * These numbers are the page's central claim — "2.3% of a healthy reference
 * population would fall below −2 SD" is stated on screen to a government
 * audience, so it had better be right.
 */

describe("normalCdf", () => {
  it("reproduces the standard normal at the WHO cut-offs", () => {
    // The two figures the page actually quotes.
    expect(normalCdf(-2)).toBeCloseTo(0.02275, 4);
    expect(normalCdf(-3)).toBeCloseTo(0.00135, 4);
  });

  it("is exactly one half at the mean", () => {
    expect(normalCdf(0)).toBeCloseTo(0.5, 6);
  });

  it("is symmetric about the mean", () => {
    for (const z of [0.5, 1, 1.96, 3]) {
      expect(normalCdf(-z)).toBeCloseTo(1 - normalCdf(z), 6);
    }
  });

  it("is monotonic", () => {
    let previous = -Infinity;
    for (let z = -6; z <= 6; z += 0.25) {
      const value = normalCdf(z);
      expect(value).toBeGreaterThan(previous);
      previous = value;
    }
  });
});

describe("normalPdf", () => {
  it("peaks at the mean with the standard normal's height", () => {
    expect(normalPdf(0)).toBeCloseTo(1 / Math.sqrt(2 * Math.PI), 6);
  });

  it("is symmetric", () => {
    expect(normalPdf(-1.5)).toBeCloseTo(normalPdf(1.5), 9);
  });
});

describe("referenceCounts", () => {
  const bins = Array.from({ length: 20 }, (_, i) => ({ z: -6 + i * 0.5 }));

  it("scales to the cohort size so the two curves are comparable", () => {
    // The gap between cohort and reference is the finding. It would be
    // meaningless if one were a density and the other a count.
    const counts = referenceCounts(bins, 120, 0.5);
    const total = counts.reduce((sum, n) => sum + n, 0);
    // Not exactly 120: the bins span −6 to +4, and a little probability mass
    // lies outside that range.
    expect(total).toBeGreaterThan(115);
    expect(total).toBeLessThanOrEqual(120);
  });

  it("peaks at zero, where the reference population is centred", () => {
    const counts = referenceCounts(bins, 120, 0.5);
    const peakIndex = counts.indexOf(Math.max(...counts));
    expect(bins[peakIndex]!.z).toBeCloseTo(-0.5, 1);
  });

  it("returns zero counts for an empty cohort rather than NaN", () => {
    expect(referenceCounts(bins, 0, 0.5).every((n) => n === 0)).toBe(true);
  });
});

describe("cut-offs", () => {
  it("marks the two WHO thresholds the page reports against", () => {
    expect(CUTOFFS.map((c) => c.z)).toEqual([-3, -2]);
  });
});
