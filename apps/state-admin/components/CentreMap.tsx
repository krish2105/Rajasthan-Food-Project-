"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import type { Centre } from "@/lib/report";
import { FlatMap } from "./map/FlatMap";

/**
 * Where the pilot is, and how each centre is doing.
 *
 * Three columns at three real coordinates. Deliberately not a shaded district
 * map: we have three centres, not a district census, and colouring in the whole
 * of Banswara from 90 children would imply coverage this system does not have.
 * The view is honest about its own scale, which matters more here than looking
 * comprehensive.
 *
 * The 3D scene is a lazily-loaded chunk and the flat map renders immediately,
 * so the page is never blank while three.js loads, never broken when WebGL is
 * refused — common on the locked-down laptops and remote-desktop sessions this
 * will actually be shown from — and never printed as an empty canvas.
 */

const Scene3D = dynamic(() => import("./map/Scene3D"), {
  ssr: false,
  loading: () => (
    <div
      style={{
        aspectRatio: "16 / 10",
        background: "var(--ink-800)",
        display: "grid",
        placeItems: "center",
        color: "var(--text-muted)",
        fontFamily: "var(--font-mono)",
        fontSize: "var(--step--1)",
      }}
    >
      Loading 3D view…
    </div>
  ),
});

function webglAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

export function CentreMap({ centres }: { centres: Centre[] }) {
  const [mode, setMode] = useState<"3d" | "flat">("flat");
  const [webgl, setWebgl] = useState<boolean | null>(null);

  useEffect(() => {
    // Checked after mount so the server render is always the flat map. Starting
    // flat and upgrading is the progressive-enhancement order; the reverse
    // shows a broken canvas first.
    const ok = webglAvailable();
    setWebgl(ok);
    if (ok) setMode("3d");
  }, []);

  const show3d = mode === "3d" && webgl === true;

  return (
    <div>
      <div className="no-print" style={{ display: "flex", gap: "var(--space-2)",
                                         marginBottom: "var(--space-4)" }}>
        <button type="button" className="btn" aria-pressed={show3d}
                onClick={() => setMode("3d")} disabled={webgl === false}>
          3D
        </button>
        <button type="button" className="btn" aria-pressed={!show3d}
                onClick={() => setMode("flat")}>
          Flat map
        </button>
      </div>

      {show3d ? <Scene3D centres={centres} /> : <FlatMap centres={centres} />}

      {webgl === false && (
        <p className="note" style={{ marginTop: "var(--space-3)" }}>
          3D is unavailable on this display. The flat map shows the same figures.
        </p>
      )}

      <div className="only-print">
        <FlatMap centres={centres} />
      </div>
    </div>
  );
}
