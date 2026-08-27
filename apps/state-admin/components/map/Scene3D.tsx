"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Centre } from "@/lib/report";
import { pct } from "@/lib/report";
import { project, severityColor } from "./geo";

/**
 * The 3D centre view, in plain three.js.
 *
 * Written imperatively rather than with React Three Fiber, and that is a
 * deliberate reversal. R3F was the obvious choice and it was removed after it
 * broke: its `react-reconciler` reads React internals that were undefined in
 * this combination, and because a reconciler failure throws during hydration it
 * took *the entire page* down with it — every section stuck at opacity zero,
 * not just the canvas.
 *
 * A dependency that can blank a government pitch surface has to earn its place,
 * and R3F's value is declarative composition of complex scenes. This scene is
 * three boxes, a grid and an orbit camera. Doing it directly removes the
 * reconciler, drops roughly 90 kB, and means the worst a WebGL problem can do
 * is leave this one component empty.
 *
 * Labels are HTML positioned over the canvas rather than 3D text: they stay
 * crisp at any zoom, inherit the page's Devanagari font, and are selectable and
 * readable by a screen reader.
 */

interface ScreenLabel {
  code: string;
  name: string;
  x: number;
  y: number;
}

export default function Scene3D({ centres }: { centres: Centre[] }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [labels, setLabels] = useState<ScreenLabel[]>([]);
  const [hovered, setHovered] = useState<Centre | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const points = project(centres);

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setFailed(true);
      return;
    }

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0d121a");

    const camera = new THREE.PerspectiveCamera(42, 16 / 10, 0.1, 100);
    camera.position.set(6, 6, 8);

    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    mount.appendChild(renderer.domElement);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    renderer.domElement.style.display = "block";

    scene.add(new THREE.AmbientLight(0xffffff, 0.75));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(4, 8, 5);
    scene.add(key);
    scene.add(new THREE.GridHelper(14, 14, 0x253044, 0x1a2231));

    // One column per centre. Height is stunting prevalence, width is cohort
    // size -- the second variable is why this is 3D at all, since a flat map
    // would need a separate legend to say the same thing.
    const columns: { mesh: THREE.Mesh; centre: Centre; top: THREE.Vector3 }[] = [];
    for (const { centre, x, z } of points) {
      const height = Math.max((centre.stunting_rate ?? 0) * 6, 0.35);
      const width = 0.35 + (centre.children / 120) * 0.5;
      const mesh = new THREE.Mesh(
        new THREE.BoxGeometry(width, height, width),
        new THREE.MeshStandardMaterial({
          color: new THREE.Color(severityColor(centre.stunting_rate)),
          roughness: 0.45,
          metalness: 0.1,
        }),
      );
      mesh.position.set(x, height / 2, z);
      mesh.userData.awc = centre.awc_code;
      scene.add(mesh);

      const halo = new THREE.Mesh(
        new THREE.CircleGeometry(width * 0.9, 24),
        new THREE.MeshBasicMaterial({ color: 0x5b7ce0, transparent: true, opacity: 0.22 }),
      );
      halo.rotation.x = -Math.PI / 2;
      halo.position.set(x, 0.005, z);
      scene.add(halo);

      columns.push({ mesh, centre, top: new THREE.Vector3(x, height + 0.45, z) });
    }

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enablePan = false;
    controls.enableDamping = true;
    controls.minDistance = 6;
    controls.maxDistance = 18;
    controls.minPolarAngle = 0.35;
    controls.maxPolarAngle = Math.PI / 2.3;
    // Idle rotation is exactly the ambient movement prefers-reduced-motion asks
    // us to stop.
    controls.autoRotate = !reduceMotion;
    controls.autoRotateSpeed = 0.4;

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let pointerActive = false;

    const onPointerMove = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      pointerActive = true;
    };
    const onPointerLeave = () => {
      pointerActive = false;
      setHovered(null);
    };
    renderer.domElement.addEventListener("pointermove", onPointerMove);
    renderer.domElement.addEventListener("pointerleave", onPointerLeave);

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = mount;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(mount);

    let raf = 0;
    let lastHovered: string | null = null;
    const project3d = new THREE.Vector3();

    const tick = () => {
      controls.update();

      if (pointerActive) {
        raycaster.setFromCamera(pointer, camera);
        const hit = raycaster.intersectObjects(columns.map((c) => c.mesh))[0];
        const code = (hit?.object.userData.awc as string | undefined) ?? null;
        if (code !== lastHovered) {
          lastHovered = code;
          setHovered(columns.find((c) => c.centre.awc_code === code)?.centre ?? null);
        }
      }

      // Project each column top to screen space so the HTML labels track it.
      const rect = renderer.domElement.getBoundingClientRect();
      setLabels(
        columns.map(({ centre, top }) => {
          project3d.copy(top).project(camera);
          return {
            code: centre.awc_code,
            name: centre.block,
            x: ((project3d.x + 1) / 2) * rect.width,
            y: ((-project3d.y + 1) / 2) * rect.height,
          };
        }),
      );

      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    };
    tick();

    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointermove", onPointerMove);
      renderer.domElement.removeEventListener("pointerleave", onPointerLeave);
      controls.dispose();
      // Geometries and materials are not garbage-collected with the scene
      // graph; leaking them across a route change is how a long-running review
      // session ends up out of GPU memory.
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          object.geometry.dispose();
          const material = object.material;
          if (Array.isArray(material)) material.forEach((m) => m.dispose());
          else material.dispose();
        }
      });
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, [centres]);

  if (failed) {
    return (
      <p className="note">3D is unavailable on this display. Use the flat map.</p>
    );
  }

  return (
    <div style={{ position: "relative", aspectRatio: "16 / 10", background: "var(--ink-800)" }}>
      <div ref={mountRef} style={{ position: "absolute", inset: 0 }} />
      {labels.map((label) => (
        <span
          key={label.code}
          aria-hidden
          style={{
            position: "absolute",
            left: label.x,
            top: label.y,
            transform: "translate(-50%, -100%)",
            pointerEvents: "none",
            fontFamily: "var(--font-mono)",
            fontSize: "0.75rem",
            color: "var(--text)",
            textShadow: "0 1px 3px #070a0f",
            whiteSpace: "nowrap",
          }}
        >
          {label.name}
        </span>
      ))}
      {hovered && (
        <div
          className="card"
          style={{
            position: "absolute",
            top: "var(--space-4)",
            left: "var(--space-4)",
            minWidth: 220,
            fontSize: "0.85rem",
            background: "var(--ink-600)",
            pointerEvents: "none",
          }}
        >
          <strong>{hovered.name_en}</strong>
          <div className="deva" style={{ color: "var(--text-secondary)" }}>{hovered.name_hi}</div>
          <div style={{ marginTop: 8, color: "var(--text-secondary)" }}>
            {hovered.children} children · {hovered.measured} measured
            <br />
            Stunting {pct(hovered.stunting_rate)} · SAM {hovered.sam}
          </div>
        </div>
      )}
    </div>
  );
}
