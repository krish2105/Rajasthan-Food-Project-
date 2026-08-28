"use client";

import type { TrendPoint } from "@/lib/types";

/**
 * One centre's compliance, day by day (Section 9.2's per-AWC trend).
 *
 * A strip of bars rather than a line chart. The question an officer has is
 * "which days went wrong and are they clustering", and a bar per day answers
 * that directly while a smoothed line hides exactly the single bad day that
 * matters. Fixed 0-100% axis, because compliance has a real ceiling and a
 * self-scaled axis would make a good week look dramatic.
 */
export function CentreTrend({ points }: { points: TrendPoint[] }) {
  if (!points.length) return <p className="empty">No compliance record for this centre.</p>;

  const width = Math.max(points.length * 14, 200);
  const height = 64;

  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Daily menu compliance for this centre across ${points.length} days. ${
          points.filter((p) => p.flagged).length
        } days flagged.`}
        style={{ display: "block" }}
      >
        {[0, 50, 100].map((line) => (
          <line
            key={line}
            x1={0}
            x2={width}
            y1={height - (line / 100) * height}
            y2={height - (line / 100) * height}
            stroke="var(--line-soft)"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {points.map((point, i) => {
          const value = point.compliance_pct ?? 0;
          const barHeight = Math.max((value / 100) * height, 1);
          return (
            <rect
              key={point.date}
              x={i * 14 + 2}
              y={height - barHeight}
              width={10}
              height={barHeight}
              fill={point.flagged ? "var(--severe)" : "var(--normal)"}
              opacity={point.flagged ? 0.9 : 0.55}
            >
              <title>
                {point.date}: {value}% ({point.detected} of {point.prescribed} items)
                {point.flagged ? " — flagged" : ""}
              </title>
            </rect>
          );
        })}
      </svg>
      <figcaption className="muted" style={{ fontSize: 11, marginTop: 4 }}>
        {points.length} days · {points.filter((p) => p.flagged).length} flagged · earliest{" "}
        {points[0]!.date}
      </figcaption>
    </figure>
  );
}
