"use client";

import { useRef } from "react";
import { useReveal } from "@/lib/useReveal";
import type { TrendPoint } from "@/lib/report";
import { pct } from "@/lib/report";

/**
 * Prevalence month by month.
 *
 * Plotted with a deliberately un-zoomed y-axis running 0–60%, because a chart
 * scaled to its own data makes two points of noise look like a trend. Over a
 * six-month baseline with no intervention, flat is the correct and expected
 * shape, and the chart should show that rather than manufacture movement.
 */

const W = 900;
const H = 260;
const PAD = { top: 20, right: 24, bottom: 40, left: 52 };
const Y_MAX = 0.6;

export function TrendChart({ trend }: { trend: TrendPoint[] }) {
  const ref = useRef<SVGSVGElement>(null);
  const { revealed, shouldAnimate } = useReveal(ref, { margin: "-60px" });

  if (trend.length < 2) {
    return <p className="prose">Not enough months recorded to show a trend.</p>;
  }

  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (i / (trend.length - 1)) * plotW;
  const y = (rate: number) => PAD.top + plotH - (rate / Y_MAX) * plotH;

  const series = [
    { key: "stunting_rate" as const, color: "var(--severe)", label: "Stunting" },
    { key: "underweight_rate" as const, color: "var(--moderate)", label: "Underweight" },
  ];

  return (
    <figure style={{ margin: 0 }}>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
           aria-labelledby="trend-title" style={{ display: "block" }}>
        <title id="trend-title">
          Stunting and underweight prevalence by month across the pilot cohort
        </title>

        {[0, 0.2, 0.4, 0.6].map((tick) => (
          <g key={tick}>
            <line x1={PAD.left} y1={y(tick)} x2={PAD.left + plotW} y2={y(tick)}
                  stroke="var(--line-soft)" />
            <text x={PAD.left - 10} y={y(tick) + 4} textAnchor="end"
                  fill="var(--text-muted)" fontSize="12" fontFamily="var(--font-mono)">
              {`${tick * 100}%`}
            </text>
          </g>
        ))}

        {trend.map((point, i) => (
          <text key={point.month} x={x(i)} y={H - 14} textAnchor="middle"
                fill="var(--text-muted)" fontSize="12" fontFamily="var(--font-mono)">
            {point.month.slice(5)}
          </text>
        ))}

        {series.map((s) => {
          const path = trend
            .map((point, i) => {
              const rate = point[s.key];
              if (rate === null) return "";
              return `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(rate).toFixed(1)}`;
            })
            .filter(Boolean)
            .join(" ");
          return (
            <path
              key={s.key}
              className="draw"
              data-revealed={revealed ? "true" : "false"}
              d={path}
              fill="none"
              stroke={s.color}
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              // The dash length is an over-estimate of the path length, which
              // is all the technique needs: any value at least as long as the
              // path hides it completely at full offset.
              style={
                {
                  "--len": "2000",
                  strokeDasharray: 2000,
                  transition: shouldAnimate ? undefined : "none",
                } as React.CSSProperties
              }
            />
          );
        })}

        {series.map((s) =>
          trend.map((point, i) =>
            point[s.key] === null ? null : (
              <circle key={`${s.key}-${point.month}`} cx={x(i)} cy={y(point[s.key]!)}
                      r="3.5" fill={s.color} />
            ),
          ),
        )}
      </svg>

      <div style={{ display: "flex", gap: "var(--space-5)", marginTop: "var(--space-3)" }}>
        {series.map((s) => (
          <span key={s.key} style={{ display: "inline-flex", alignItems: "center", gap: 8,
                                     color: "var(--text-secondary)", fontSize: "var(--step--1)" }}>
            <span style={{ width: 14, height: 3, background: s.color, borderRadius: 2 }} />
            {s.label}
          </span>
        ))}
      </div>

      <table style={{ marginTop: "var(--space-5)" }}>
        <caption style={{ textAlign: "left", color: "var(--text-muted)",
                          fontSize: "var(--step--1)", paddingBottom: "var(--space-2)" }}>
          Prevalence by month
        </caption>
        <thead>
          <tr>
            <th scope="col">Month</th>
            <th scope="col" className="num">Measured</th>
            <th scope="col" className="num">Stunting</th>
            <th scope="col" className="num">Underweight</th>
            <th scope="col" className="num">SAM</th>
            <th scope="col" className="num">Mean HAZ</th>
          </tr>
        </thead>
        <tbody>
          {trend.map((point) => (
            <tr key={point.month}>
              <td className="num">{point.month}</td>
              <td className="num">{point.measured}</td>
              <td className="num">{pct(point.stunting_rate)}</td>
              <td className="num">{pct(point.underweight_rate)}</td>
              <td className="num">{point.sam}</td>
              <td className="num">{point.mean_haz ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
