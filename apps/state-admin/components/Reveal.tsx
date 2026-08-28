"use client";

import { useRef } from "react";
import type { ReactNode } from "react";
import { useReveal } from "@/lib/useReveal";

/**
 * A short entrance for a block of content as it comes into view.
 *
 * CSS transitions rather than an animation library, and that is a deliberate
 * reversal after two of them failed here in the same way: React Three Fiber's
 * reconciler threw during hydration, and Motion rendered its `initial` values
 * as inline styles and then never ran the animation, leaving every section on
 * the page at opacity zero. Both failures were invisible in the markup and
 * total on screen — the worst combination for a surface that has to work in a
 * room full of officials.
 *
 * A CSS transition on `opacity` and `transform` cannot fail that way: the
 * end state is what the stylesheet says, and if the transition never runs the
 * content is simply there. It also costs nothing to load and is composited off
 * the main thread. Reduced motion is handled by the global rule in globals.css,
 * which collapses every transition on the page.
 *
 * `useReveal` decides visibility rather than `whileInView`, because content a
 * reviewer jumped straight to must appear immediately rather than waiting for a
 * scroll event that already happened.
 */
export function Reveal({ children, delay = 0 }: { children: ReactNode; delay?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const { revealed, shouldAnimate } = useReveal(ref);

  return (
    <div
      ref={ref}
      className="reveal"
      data-revealed={revealed ? "true" : "false"}
      style={shouldAnimate ? { transitionDelay: `${delay}s` } : { transition: "none" }}
    >
      {children}
    </div>
  );
}
