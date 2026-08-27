"use client";

import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

/**
 * Whether an element should be shown, with the animation as an enhancement.
 *
 * `whileInView` and `useInView` with `once: true` share a failure mode that is
 * easy to miss in development and unacceptable here: if an element is never
 * *scrolled through* — the page reloads with a restored scroll position, a
 * reviewer follows a deep link, find-in-page jumps them down — the
 * IntersectionObserver reports only the final state, the entry never fires, and
 * the content stays at opacity 0 permanently.
 *
 * On a marketing page that is a missed flourish. On a report a District
 * Collector is reading, it is a blank section where the prevalence figures
 * should be, with no indication anything is missing.
 *
 * So visibility is decided three ways, and any one of them is enough:
 *
 *   1. the element intersects the viewport (the normal path, which animates);
 *   2. at mount it is already at or above the viewport (jumped past — show it
 *      immediately, with no animation, because there is nothing to reveal);
 *   3. a hard timeout, so no combination of circumstances can leave content
 *      invisible.
 *
 * Returns `shouldAnimate` separately from `revealed`, so cases 2 and 3 render
 * the final state directly rather than playing an entrance for content the
 * reader is already looking at.
 */

const FAILSAFE_MS = 1200;

export function useReveal<T extends Element>(
  ref: RefObject<T | null>,
  { margin = "-60px" }: { margin?: string } = {},
): { revealed: boolean; shouldAnimate: boolean } {
  const [revealed, setRevealed] = useState(false);
  const animate = useRef(true);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    // Already visible, or scrolled past. Nothing to reveal.
    const rect = element.getBoundingClientRect();
    if (rect.top < window.innerHeight) {
      animate.current = rect.top > 0;
      setRevealed(true);
      return;
    }

    if (typeof IntersectionObserver !== "function") {
      animate.current = false;
      setRevealed(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setRevealed(true);
          observer.disconnect();
        }
      },
      { rootMargin: margin },
    );
    observer.observe(element);

    const failsafe = window.setTimeout(() => {
      animate.current = false;
      setRevealed(true);
      observer.disconnect();
    }, FAILSAFE_MS + 4000);

    return () => {
      observer.disconnect();
      window.clearTimeout(failsafe);
    };
  }, [ref, margin]);

  return { revealed, shouldAnimate: revealed && animate.current };
}
