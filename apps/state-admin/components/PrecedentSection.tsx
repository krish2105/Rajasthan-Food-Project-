import { Reveal } from "./Reveal";

/**
 * The Gadchiroli precedent.
 *
 * Section 9.3 asks for a before/after case study "mirroring the Gadchiroli
 * 61→20 framing". Those figures are Gadchiroli's, from Gadchiroli's own
 * programme — and they are presented here as exactly that, attributed and
 * dated, rather than dressed up as something PoshanNetra has achieved.
 *
 * This pilot has not run. A screen showing 61→20 over a Banswara heading would
 * be a fabricated result put in front of government reviewers, which Section 15
 * forbids and which any official who knows the sector would catch. Argument by
 * attributed precedent is both honest and, in that room, the stronger move.
 */

const GADCHIROLI = {
  place: "Gadchiroli district, Maharashtra",
  programme: "SEARCH / community-based child nutrition monitoring",
  before: 61,
  after: 20,
  unit: "% underweight children",
  note:
    "Reported by the implementing programme in Gadchiroli. Not a PoshanNetra result, and not measured by this system.",
};

export function PrecedentSection() {
  return (
    <section className="shell">
      <Reveal>
        <p className="eyebrow">Precedent</p>
        <h2 style={{ marginTop: "var(--space-3)" }}>
          The approach has worked before, elsewhere in India
        </h2>
        <p className="prose" style={{ marginTop: "var(--space-4)" }}>
          PoshanNetra is modelled on a documented intervention in {GADCHIROLI.place}, where
          community-level nutrition monitoring and a structured response reduced underweight
          prevalence over the life of the programme.
        </p>
      </Reveal>

      <Reveal delay={0.08}>
        <div className="card" style={{ marginTop: "var(--space-6)", maxWidth: 640 }}>
          <p className="eyebrow">{GADCHIROLI.place}</p>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: "var(--space-4)",
              marginTop: "var(--space-4)",
            }}
          >
            <span className="num" style={{ fontSize: "var(--step-3)", color: "var(--severe)" }}>
              {GADCHIROLI.before}%
            </span>
            <span aria-hidden style={{ color: "var(--text-muted)" }}>→</span>
            <span className="num" style={{ fontSize: "var(--step-3)", color: "var(--normal)" }}>
              {GADCHIROLI.after}%
            </span>
            <span style={{ color: "var(--text-secondary)", fontSize: "var(--step--1)" }}>
              {GADCHIROLI.unit}
            </span>
          </div>
          {/* The attribution is not fine print. It is the reason the number can
              be shown at all. */}
          <p className="note" style={{ marginTop: "var(--space-5)" }}>
            {GADCHIROLI.note}
          </p>
        </div>
      </Reveal>

      <Reveal delay={0.12}>
        <p className="prose" style={{ marginTop: "var(--space-6)" }}>
          What PoshanNetra adds to that model is evidence: a photograph of the plate a child
          was actually served, checked against the day&rsquo;s prescribed PM POSHAN menu. Two
          specific failures become auditable — menu non-compliance, and food-quality problems
          that a paper register cannot record.
        </p>
        <p className="prose">
          The figures throughout the rest of this report are PoshanNetra&rsquo;s own baseline.
          There is no intervention period yet to compare them against.
        </p>
      </Reveal>
    </section>
  );
}
