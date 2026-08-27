"use client";

import { useRef } from "react";
import { useReveal } from "@/lib/useReveal";
import type { Distribution } from "@/lib/report";
import { CUTOFFS, normalCdf, referenceCounts } from "@/lib/stats";

/**
 * The page's signature element.
 *
 * A prevalence percentage tells a reviewer how many children fall past a
 * threshold. This shows the whole cohort sitting to the left of the population
 * WHO built the standard from — the same shape, moved. That is a harder claim
 * to argue with than a number, and it is the actual finding.
 *
 * The reference curve is not fitted to anything: a z-score is defined against a
 * standard normal, so the grey curve is what the histogram would look like if
 * these children were growing like the reference population. The gap is the
 * malnutrition.
 *
 * Drawn as SVG rather than canvas or a charting library: it prints, it scales
 * on a projector, it is readable by a screen reader through the table beneath
 * it, and it costs nothing to load.
 */

const W = 900;
const H = 380;
const PAD = { top: 28, right: 24, bottom: 52, left: 52 };

export function DistributionChart({ distribution }: { distribution: Distribution }) {
  const ref = useRef<SVGSVGElement>(null);
  const { revealed, shouldAnimate } = useReveal(ref, { margin: "-80px" });

  const { bins, n, mean_z: meanZ, bin_width: binWidth } = distribution;
  if (!bins.length || n === 0) {
    return (
      <p className="prose">
        No measurements yet. The distribution appears once growth data is recorded.
      </p>
    );
  }

  const reference = referenceCounts(bins, n, binWidth);
  const maxCount = Math.max(...bins.map((b) => b.count), ...reference, 1);

  const zMin = bins[0]!.z;
  const zMax = bins[bins.length - 1]!.z + binWidth;
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const x = (z: number) => PAD.left + ((z - zMin) / (zMax - zMin)) * plotW;
  const y = (count: number) => PAD.top + plotH - (count / maxCount) * plotH;
  const barW = plotW / bins.length;

  const referencePath = reference
    .map((count, i) => {
      const px = x(bins[i]!.z + binWidth / 2);
      const py = y(count);
      return `${i === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .join(" ");

  const belowMinus2 = bins
    .filter((b) => b.z + binWidth <= -2)
    .reduce((sum, b) => sum + b.count, 0);
  const expectedBelowMinus2 = normalCdf(-2);

  const ticks = [-6, -5, -4, -3, -2, -1, 0, 1, 2, 3, 4].filter(
    (t) => t >= zMin && t <= zMax,
  );

  return (
    <figure style={{ margin: 0 }}>
      <svg
        ref={ref}
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-labelledby="dist-title dist-desc"
        style={{ display: "block", overflow: "visible" }}
      >
        <title id="dist-title">
          Height-for-age z-score distribution across the pilot cohort
        </title>
        <desc id="dist-desc">
          {`${n} children. Mean height-for-age z-score ${meanZ}. `}
          {`${belowMinus2} children fall below −2 SD, against `}
          {`${(expectedBelowMinus2 * 100).toFixed(1)}% expected in the WHO reference population. `}
          The full figures are in the table below this chart.
        </desc>

        {/* Cut-off bands. Drawn first so bars sit above them. */}
        <rect
          x={x(zMin)} y={PAD.top} width={x(-3) - x(zMin)} height={plotH}
          fill="var(--severe)" opacity="0.09"
        />
        <rect
          x={x(-3)} y={PAD.top} width={x(-2) - x(-3)} height={plotH}
          fill="var(--moderate)" opacity="0.09"
        />

        {/* Axes */}
        <line
          x1={PAD.left} y1={PAD.top + plotH} x2={PAD.left + plotW} y2={PAD.top + plotH}
          stroke="var(--line)" strokeWidth="1"
        />
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={x(t)} y1={PAD.top + plotH} x2={x(t)} y2={PAD.top + plotH + 5}
              stroke="var(--line)"
            />
            <text
              x={x(t)} y={PAD.top + plotH + 20} textAnchor="middle"
              fill="var(--text-muted)" fontSize="12" fontFamily="var(--font-mono)"
            >
              {t > 0 ? `+${t}` : t === 0 ? "0" : `−${Math.abs(t)}`}
            </text>
          </g>
        ))}

        {/* Cohort histogram. Bars grow from the axis: the animation is the
            data arriving, not decoration, and it is skipped under
            prefers-reduced-motion. */}
        {bins.map((bin, i) => {
          const height = (bin.count / maxCount) * plotH;
          const severity =
            bin.z + binWidth <= -3
              ? "var(--severe)"
              : bin.z + binWidth <= -2
                ? "var(--moderate)"
                : "var(--indigo)";
          return (
            <rect
              key={bin.z}
              className="bar"
              data-revealed={revealed ? "true" : "false"}
              x={x(bin.z) + 1}
              y={PAD.top + plotH - height}
              width={Math.max(barW - 2, 1)}
              height={height}
              // Staggered by index so the distribution builds left to right,
              // which reads as the shape assembling rather than a wall
              // appearing. Skipped entirely when the reader jumped here.
              style={
                shouldAnimate
                  ? { transitionDelay: `${0.15 + i * 0.018}s` }
                  : { transition: "none" }
              }
              fill={severity}
              opacity="0.85"
            />
          );
        })}

        {/* WHO reference population */}
        {/* The WHO reference population. Dashed, so it reads as the standard
            being compared against rather than a second measurement. */}
        <path
          d={referencePath}
          fill="none"
          stroke="var(--reference)"
          strokeWidth="2"
          strokeDasharray="5 4"
          opacity={revealed ? 1 : 0}
          style={{
            transition: shouldAnimate ? "opacity 700ms ease-out 500ms" : "none",
          }}
        />

        {/* Cut-off rules */}
        {CUTOFFS.map((cut) => (
          <g key={cut.z}>
            <line
              x1={x(cut.z)} y1={PAD.top - 8} x2={x(cut.z)} y2={PAD.top + plotH}
              stroke={cut.meaning === "severe" ? "var(--severe)" : "var(--moderate)"}
              strokeWidth="1.5"
            />
            <text
              x={x(cut.z) + 6} y={PAD.top - 12}
              fill={cut.meaning === "severe" ? "var(--severe)" : "var(--moderate)"}
              fontSize="12" fontFamily="var(--font-mono)"
            >
              {cut.label}
            </text>
          </g>
        ))}

        {/* Cohort mean, against the reference mean of 0 — the whole point of
            the chart in one mark. */}
        {meanZ !== null && (
          <g>
            <line
              x1={x(meanZ)} y1={PAD.top} x2={x(meanZ)} y2={PAD.top + plotH}
              stroke="var(--brass)" strokeWidth="2"
            />
            <text
              x={x(meanZ)} y={PAD.top + plotH + 40} textAnchor="middle"
              fill="var(--brass)" fontSize="12" fontFamily="var(--font-mono)"
            >
              {`cohort mean ${meanZ}`}
            </text>
          </g>
        )}

        <text
          x={PAD.left} y={H - 6} fill="var(--text-muted)" fontSize="12"
          fontFamily="var(--font-mono)"
        >
          height-for-age z-score
        </text>
      </svg>

      <figcaption className="prose" style={{ marginTop: "var(--space-4)" }}>
        <strong style={{ color: "var(--text)" }}>{belowMinus2} of {n} children</strong>{" "}
        measure below −2 SD height-for-age. In the population WHO built the
        standard from, {(expectedBelowMinus2 * 100).toFixed(1)}% would.
        {meanZ !== null && (
          <>
            {" "}The cohort mean sits at{" "}
            <span className="num" style={{ color: "var(--brass)" }}>{meanZ} SD</span>,
            against a reference mean of 0.
          </>
        )}
      </figcaption>

      {/* The same data as a table. Not a fallback -- the accessible reading of
          the chart, and what the print stylesheet keeps when the SVG is
          dropped. */}
      <details style={{ marginTop: "var(--space-4)" }} className="no-print">
        <summary
          style={{ cursor: "pointer", color: "var(--text-muted)", fontSize: "var(--step--1)" }}
        >
          Distribution as a table
        </summary>
        <DistributionTable distribution={distribution} reference={reference} />
      </details>
      <div className="only-print">
        <DistributionTable distribution={distribution} reference={reference} />
      </div>
    </figure>
  );
}

function DistributionTable({
  distribution,
  reference,
}: {
  distribution: Distribution;
  reference: number[];
}) {
  const { bins, bin_width: binWidth } = distribution;
  return (
    <table style={{ marginTop: "var(--space-3)" }}>
      <caption
        style={{
          textAlign: "left",
          color: "var(--text-muted)",
          fontSize: "var(--step--1)",
          paddingBottom: "var(--space-2)",
        }}
      >
        Height-for-age z-score distribution, cohort against WHO reference
      </caption>
      <thead>
        <tr>
          <th scope="col">z-score band</th>
          <th scope="col" className="num">Children</th>
          <th scope="col" className="num">Expected (WHO)</th>
        </tr>
      </thead>
      <tbody>
        {bins
          // Bands where neither the cohort nor the reference has anything to
          // say are dropped, so the printed table is a page rather than three.
          .map((bin, index) => ({ bin, expected: reference[index] ?? 0 }))
          .filter(({ bin, expected }) => bin.count > 0 || expected >= 0.5)
          .map(({ bin, expected }) => (
            <tr key={bin.z}>
              <td className="num">
                {bin.z.toFixed(1)} to {(bin.z + binWidth).toFixed(1)}
              </td>
              <td className="num">{bin.count}</td>
              <td className="num" style={{ color: "var(--text-muted)" }}>
                {expected.toFixed(1)}
              </td>
            </tr>
          ))}
      </tbody>
    </table>
  );
}
