import type { Centre } from "@/lib/report";
import { pct } from "@/lib/report";
import { project, severityColor } from "./geo";

/**
 * The flat view.
 *
 * Not a degraded fallback -- it carries the same two variables as the 3D scene
 * (prevalence as colour, cohort size as radius) and is what gets printed, what
 * renders without WebGL, and what a Collector who finds the 3D gimmicky can
 * switch to. It lives in the main bundle so the page has a map before three.js
 * has finished loading.
 */
export function FlatMap({ centres }: { centres: Centre[] }) {
  const points = project(centres);
  if (!points.length) return <p className="prose">No centre coordinates available.</p>;

  const xs = points.map((p) => p.x);
  const zs = points.map((p) => p.z);
  const pad = 1.6;
  const minX = Math.min(...xs) - pad;
  const maxX = Math.max(...xs) + pad;
  const minZ = Math.min(...zs) - pad;
  const maxZ = Math.max(...zs) + pad;

  return (
    <svg
      viewBox={`${minX} ${minZ} ${maxX - minX} ${maxZ - minZ}`}
      width="100%"
      style={{ aspectRatio: "16 / 10", background: "var(--ink-800)" }}
      role="img"
      aria-label="Pilot centres positioned by their real coordinates, sized by cohort and coloured by stunting prevalence"
    >
      {points.map(({ centre, x, z }) => (
        <g key={centre.awc_code}>
          <circle
            cx={x} cy={z}
            r={0.28 + (centre.children / 120) * 0.35}
            fill={severityColor(centre.stunting_rate)}
            opacity="0.85"
          />
          <text x={x} y={z - 0.55} textAnchor="middle" fill="var(--text-secondary)"
                fontSize="0.32" fontFamily="var(--font-mono)">
            {centre.block}
          </text>
          <text x={x} y={z + 0.85} textAnchor="middle" fill="var(--text-muted)"
                fontSize="0.28" fontFamily="var(--font-mono)">
            {pct(centre.stunting_rate, 0)}
          </text>
        </g>
      ))}
    </svg>
  );
}
