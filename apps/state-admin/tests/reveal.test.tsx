import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Reveal } from "@/components/Reveal";

/**
 * The reveal.
 *
 * These tests exist because of a bug that made the whole page blank. The
 * original used Motion's `whileInView` with `once: true`, which never fires if
 * a section is *jumped past* rather than scrolled through — a reload with a
 * restored scroll position, a deep link, find-in-page. The content stayed at
 * opacity zero permanently, with no error and nothing missing from the markup.
 *
 * The rule this encodes: content is visible unless something actively hides it,
 * never the other way round.
 */

describe("Reveal", () => {
  it("renders its children into the document regardless of visibility", () => {
    render(<Reveal>Prevalence figures</Reveal>);
    expect(screen.getByText("Prevalence figures")).toBeInTheDocument();
  });

  it("reveals content that is already on screen", async () => {
    // jsdom reports a zero-height rect at top 0, which is inside the viewport,
    // so the mount check should show it immediately.
    const { container } = render(<Reveal>Visible now</Reveal>);
    await waitFor(() => {
      expect(container.querySelector(".reveal")).toHaveAttribute("data-revealed", "true");
    });
  });

  it("shows content when IntersectionObserver is unavailable", async () => {
    // Rather than leaving the page blank on a browser without it.
    const original = window.IntersectionObserver;
    // @ts-expect-error deliberately removing the API
    delete window.IntersectionObserver;
    const { container } = render(<Reveal>No observer here</Reveal>);
    await waitFor(() => {
      expect(container.querySelector(".reveal")).toHaveAttribute("data-revealed", "true");
    });
    window.IntersectionObserver = original;
  });

  it("uses CSS classes rather than inline animation state", () => {
    // The end state lives in the stylesheet, so a JavaScript failure leaves
    // content readable instead of invisible.
    const { container } = render(<Reveal>Styled by CSS</Reveal>);
    expect(container.querySelector(".reveal")).toBeInTheDocument();
  });
});
