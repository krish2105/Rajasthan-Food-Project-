import { CentreMap } from "@/components/CentreMap";
import { DistributionChart } from "@/components/DistributionChart";
import { PrecedentSection } from "@/components/PrecedentSection";
import { Reveal } from "@/components/Reveal";
import { TrendChart } from "@/components/TrendChart";
import { ApiUnavailable, NotSignedIn, fetchStateReport } from "@/lib/api";
import { SignIn } from "@/components/SignIn";
import { num, pct } from "@/lib/report";
import type { Report } from "@/lib/report";
import { normalCdf } from "@/lib/stats";
import { PrintButton } from "@/components/PrintButton";

export const dynamic = "force-dynamic";

export default async function StateReview() {
  let report: Report;
  try {
    report = await fetchStateReport();
  } catch (error) {
    if (error instanceof NotSignedIn) {
      return (
        <SignIn
          title="State review sign-in"
          subtitle="PoshanNetra · पोषण नेत्र"
        />
      );
    }
    return <Unavailable message={error instanceof ApiUnavailable ? error.message : "unknown"} />;
  }

  const { coverage, prevalence, distribution, centres, trend, compliance, period } = report;
  const expectedStunting = normalCdf(-2);

  return (
    <main>
      <Hero report={report} expectedStunting={expectedStunting} />

      {/* --- What was measured ------------------------------------------- */}
      <section className="shell">
        <Reveal>
          <p className="eyebrow">Coverage</p>
          <h2 style={{ marginTop: "var(--space-3)" }}>What this report covers</h2>
        </Reveal>
        <Reveal delay={0.06}>
          <div className="grid grid--3" style={{ marginTop: "var(--space-6)" }}>
            <Stat value={num(coverage.children)} label="children enrolled" />
            <Stat value={num(coverage.centres)} label="centres" />
            <Stat value={num(prevalence.measured)} label="children measured" />
            <Stat value={num(coverage.captures)} label="plate photographs" />
          </div>
        </Reveal>
        <Reveal delay={0.1}>
          <p className="prose" style={{ marginTop: "var(--space-6)" }}>
            Two districts of the Banswara–Dungarpur tribal belt: {centres.map((c) => c.block).join(", ")}.
            {" "}Measurements run from {period.first_measurement} to {period.last_measurement}.
            {" "}Of the children measured, {prevalence.under_five} are under five and scored against
            the WHO Child Growth Standards; {prevalence.school_age} are of school age and scored
            against the WHO 2007 reference, which uses different indices entirely.
          </p>
        </Reveal>
      </section>

      {/* --- The signature: the distribution ------------------------------ */}
      <section className="shell">
        <Reveal>
          <p className="eyebrow">Finding</p>
          <h2 style={{ marginTop: "var(--space-3)", maxWidth: "18ch" }}>
            The whole cohort sits left of the standard
          </h2>
          <p className="prose" style={{ marginTop: "var(--space-4)" }}>
            Height-for-age is the clearest single measure of chronic undernutrition, because
            height accumulates. A z-score compares a child against the population the WHO
            standard was built from. Below is every measured child in the pilot, against that
            reference.
          </p>
        </Reveal>
        <Reveal delay={0.08}>
          <div style={{ marginTop: "var(--space-7)" }}>
            <DistributionChart distribution={distribution} />
          </div>
        </Reveal>
      </section>

      {/* --- Prevalence --------------------------------------------------- */}
      <section className="shell">
        <Reveal>
          <p className="eyebrow">Prevalence</p>
          <h2 style={{ marginTop: "var(--space-3)" }}>Against WHO thresholds</h2>
        </Reveal>
        <Reveal delay={0.06}>
          <div className="grid grid--3" style={{ marginTop: "var(--space-6)" }}>
            <Stat value={pct(prevalence.stunting_rate)} label="stunted (height-for-age below −2 SD)"
                  accent="var(--severe)"
                  sub={`${prevalence.severely_stunted} severely`} />
            <Stat value={pct(prevalence.underweight_rate)} label="underweight (weight-for-age below −2 SD)"
                  accent="var(--moderate)"
                  sub={`${prevalence.severely_underweight} severely`} />
            <Stat value={pct(prevalence.wasting_rate)} label="acute malnutrition"
                  accent="var(--moderate)"
                  sub={`${prevalence.sam} SAM · ${prevalence.mam} MAM`} />
          </div>
        </Reveal>
        <Reveal delay={0.1}>
          <p className="note" style={{ marginTop: "var(--space-6)", maxWidth: "62ch" }}>
            Every figure here is computed by threshold lookup on a WHO z-score, from vendored
            reference tables. No model is involved in this path, and the arithmetic is unit-tested
            against WHO&rsquo;s own published values across all 10,638 rows of those tables.
            A child can be counted in more than one column: stunting, underweight and wasting are
            different measurements, not a severity scale.
          </p>
        </Reveal>
      </section>

      {/* --- Where ---------------------------------------------------------- */}
      <section className="shell">
        <Reveal>
          <p className="eyebrow">Distribution</p>
          <h2 style={{ marginTop: "var(--space-3)" }}>By centre</h2>
          <p className="prose" style={{ marginTop: "var(--space-4)" }}>
            Column height is stunting prevalence; width is the number of children enrolled, so a
            small centre with a bad rate cannot be mistaken for a large one.
          </p>
        </Reveal>
        <Reveal delay={0.08}>
          <div style={{ marginTop: "var(--space-6)" }}>
            <CentreMap centres={centres} />
          </div>
        </Reveal>
        <Reveal delay={0.1}>
          <table style={{ marginTop: "var(--space-6)" }}>
            <caption style={{ textAlign: "left", color: "var(--text-muted)",
                              fontSize: "var(--step--1)", paddingBottom: "var(--space-2)" }}>
              Centres in the pilot
            </caption>
            <thead>
              <tr>
                <th scope="col">Centre</th>
                <th scope="col">Block</th>
                <th scope="col">Type</th>
                <th scope="col" className="num">Children</th>
                <th scope="col" className="num">Stunting</th>
                <th scope="col" className="num">SAM</th>
                <th scope="col" className="num">Menu compliance</th>
                <th scope="col" className="num">Days flagged</th>
              </tr>
            </thead>
            <tbody>
              {centres.map((centre) => (
                <tr key={centre.awc_code}>
                  <td>
                    {centre.name_en}
                    <div className="deva" style={{ color: "var(--text-muted)" }}>
                      {centre.name_hi}
                    </div>
                  </td>
                  <td>{centre.block}</td>
                  <td>{centre.centre_type === "anganwadi" ? "Anganwadi" : "Ashram school"}</td>
                  <td className="num">{centre.children}</td>
                  <td className="num">{pct(centre.stunting_rate)}</td>
                  <td className="num">{centre.sam}</td>
                  <td className="num">
                    {centre.compliance_pct === null ? "—" : `${centre.compliance_pct}%`}
                  </td>
                  <td className="num">
                    {centre.flagged_days} / {centre.menu_days}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Reveal>
      </section>

      {/* --- Trend --------------------------------------------------------- */}
      <section className="shell">
        <Reveal>
          <p className="eyebrow">Baseline</p>
          <h2 style={{ marginTop: "var(--space-3)" }}>Six months, no intervention yet</h2>
          <p className="prose" style={{ marginTop: "var(--space-4)" }}>
            This is the period before anything changed. A flat line is the expected and correct
            shape — it is the baseline any future intervention has to be measured against, and
            the axis is fixed at 0–60% so that month-to-month noise cannot be read as movement.
          </p>
        </Reveal>
        <Reveal delay={0.08}>
          <div style={{ marginTop: "var(--space-7)" }}>
            <TrendChart trend={trend} />
          </div>
        </Reveal>
      </section>

      {/* --- Compliance ---------------------------------------------------- */}
      <section className="shell">
        <Reveal>
          <p className="eyebrow">Menu compliance</p>
          <h2 style={{ marginTop: "var(--space-3)" }}>What a register cannot record</h2>
          <p className="prose" style={{ marginTop: "var(--space-4)" }}>
            The prescribed PM POSHAN menu for each day, checked against the plates actually
            served. Aggregated per centre per day, not per child: two children skipping a banana
            is not a menu that was not served.
          </p>
        </Reveal>
        <Reveal delay={0.06}>
          <div className="grid grid--3" style={{ marginTop: "var(--space-6)" }}>
            <Stat value={num(compliance.days)} label="centre-days assessed" />
            <Stat value={num(compliance.flagged)} label="days flagged for follow-up"
                  accent="var(--moderate)" sub={pct(compliance.flag_rate)} />
            <Stat
              value={compliance.mean_compliance_pct === null
                ? "—" : `${compliance.mean_compliance_pct}%`}
              label="mean menu compliance" />
          </div>
        </Reveal>
        {compliance.top_reasons.length > 0 && (
          <Reveal delay={0.1}>
            <table style={{ marginTop: "var(--space-6)", maxWidth: 620 }}>
              <caption style={{ textAlign: "left", color: "var(--text-muted)",
                                fontSize: "var(--step--1)", paddingBottom: "var(--space-2)" }}>
                Most common reasons a day was flagged
              </caption>
              <thead>
                <tr>
                  <th scope="col">Reason</th>
                  <th scope="col" className="num">Days</th>
                </tr>
              </thead>
              <tbody>
                {compliance.top_reasons.map((reason) => (
                  <tr key={reason.reason}>
                    <td>{reason.reason}</td>
                    <td className="num">{reason.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Reveal>
        )}
      </section>

      <PrecedentSection />
      <Limitations report={report} />
      <Footer report={report} />
    </main>
  );
}

/* ------------------------------------------------------------------------ */

function Hero({ report, expectedStunting }: { report: Report; expectedStunting: number }) {
  const { prevalence, distribution, coverage } = report;
  return (
    <header
      className="chart-ground"
      style={{
        paddingBlock: "clamp(4rem, 12vh, 9rem)",
        borderBottom: "1px solid var(--line-soft)",
      }}
    >
      <div className="shell">
        <Reveal>
          <p className="eyebrow">
            PoshanNetra · <span className="deva">पोषण नेत्र</span> · State review
          </p>
        </Reveal>
        <Reveal delay={0.06}>
          {/* The thesis, stated as a sentence rather than as a stat block. The
              number that matters is the distance between two distributions,
              and that is a comparison, not a figure. */}
          <h1 style={{ marginTop: "var(--space-5)", maxWidth: "16ch" }}>
            {pct(prevalence.stunting_rate, 0)} of children here are stunted.
          </h1>
        </Reveal>
        <Reveal delay={0.12}>
          <p
            className="prose"
            style={{ marginTop: "var(--space-5)", fontSize: "var(--step-1)" }}
          >
            In the population the WHO growth standard was built from,{" "}
            <span className="num">{(expectedStunting * 100).toFixed(1)}%</span> would be.
            That gap, across {num(coverage.children)} children in{" "}
            {coverage.centres} centres of the Banswara–Dungarpur belt, is what this system
            measures — and what it now photographs the evidence for.
          </p>
        </Reveal>
        <Reveal delay={0.18}>
          <dl
            style={{
              display: "flex", flexWrap: "wrap", gap: "var(--space-7)",
              marginTop: "var(--space-8)",
            }}
          >
            <HeroFigure
              value={distribution.mean_z === null ? "—" : `${distribution.mean_z} SD`}
              label="cohort mean height-for-age"
              accent="var(--brass)"
            />
            <HeroFigure value={`${prevalence.sam}`} label="children at severe acute malnutrition"
                        accent="var(--severe)" />
            <HeroFigure value={num(coverage.captures)} label="plates photographed" />
          </dl>
        </Reveal>
        <Reveal delay={0.24}>
          <div style={{ marginTop: "var(--space-7)" }}>
            <PrintButton />
          </div>
        </Reveal>
      </div>
    </header>
  );
}

function HeroFigure({ value, label, accent }: { value: string; label: string; accent?: string }) {
  return (
    <div>
      <dt className="stat__label" style={{ order: 2 }}>{label}</dt>
      <dd
        className="num"
        style={{ margin: 0, fontSize: "var(--step-2)", color: accent ?? "var(--text)" }}
      >
        {value}
      </dd>
    </div>
  );
}

function Stat({ value, label, sub, accent }: {
  value: string; label: string; sub?: string; accent?: string;
}) {
  return (
    <div className="card">
      <div className="stat__value num" style={{ color: accent ?? "var(--text)" }}>{value}</div>
      <div className="stat__label" style={{ marginTop: "var(--space-2)" }}>{label}</div>
      {sub && (
        <div className="num" style={{ marginTop: "var(--space-2)", color: "var(--text-muted)",
                                      fontSize: "var(--step--1)" }}>
          {sub}
        </div>
      )}
    </div>
  );
}

/**
 * The limitations section.
 *
 * Section 15 asks for these to be stated explicitly, on the grounds that being
 * upfront is more credible than hiding them. It is placed before the footer
 * rather than in one — a reviewer should reach it while still reading, not
 * find it in small print after the conclusion.
 */
function Limitations({ report }: { report: Report }) {
  const { data_quality: quality, prevalence } = report;
  return (
    <section className="shell">
      <Reveal>
        <p className="eyebrow">Limitations</p>
        <h2 style={{ marginTop: "var(--space-3)" }}>What these numbers do not show</h2>
      </Reveal>
      <Reveal delay={0.06}>
        <div className="grid grid--2" style={{ marginTop: "var(--space-6)" }}>
          {quality.ai_is_mock && (
            <div className="card" style={{ borderColor: "var(--moderate)" }}>
              <span className="tag tag--warn">Not yet real</span>
              <p className="prose" style={{ marginTop: "var(--space-3)" }}>
                The food-recognition pipeline is running on an offline stand-in provider, so no
                nutrition estimate on this page comes from an actual model. The growth figures
                above are unaffected — they are arithmetic over WHO tables, not model output.
              </p>
            </div>
          )}
          <div className="card">
            <span className="tag">Synthetic cohort</span>
            <p className="prose" style={{ marginTop: "var(--space-3)" }}>
              This dataset is generated, not collected. No real child&rsquo;s data enters this
              system before consent and legal sign-off. Prevalence is tuned toward NFHS-5 figures
              for the tribal belt so the surface is realistic, and must not be quoted as a finding.
            </p>
          </div>
          <div className="card">
            <span className="tag">Unvalidated recognition</span>
            <p className="prose" style={{ marginTop: "var(--space-3)" }}>
              No labelled dataset exists for tribal-Rajasthan dishes. The evaluation harness is
              built and runs, and reports every accuracy metric as unvalidated until roughly
              200–300 plate photographs are labelled during pilot week one.
            </p>
          </div>
          <div className="card">
            <span className="tag">Uncalibrated portions</span>
            <p className="prose" style={{ marginTop: "var(--space-3)" }}>
              Cooked-serving weights come from standard kitchen values, not weighed plates. A
              dietitian calibration session is required before any calorie figure is quoted.
            </p>
          </div>
          <div className="card">
            <span className="tag">Proposed integration</span>
            <p className="prose" style={{ marginTop: "var(--space-3)" }}>
              Raj-Poshan and Poshan Tracker integration is a drafted data contract built from
              publicly documented field categories, not a confirmed API. It needs NIC and WCD
              engagement before the pilot goes live.
            </p>
          </div>
          {quality.flagged_measurements > 0 && (
            <div className="card">
              <span className="tag">Excluded readings</span>
              <p className="prose" style={{ marginTop: "var(--space-3)" }}>
                {quality.flagged_measurements} measurement
                {quality.flagged_measurements === 1 ? " was" : "s were"} outside WHO&rsquo;s
                plausible range and excluded from every figure above. They are retained in the
                record for audit. {prevalence.measured} measurements were used.
              </p>
            </div>
          )}
        </div>
      </Reveal>
    </section>
  );
}

function Footer({ report }: { report: Report }) {
  return (
    <footer className="shell" style={{ paddingBlock: "var(--space-8)",
                                       borderTop: "1px solid var(--line-soft)" }}>
      <p style={{ color: "var(--text-muted)", fontSize: "var(--step--1)", maxWidth: "72ch" }}>
        Growth classification uses the WHO Child Growth Standards (2006) and WHO Growth Reference
        (2007), vendored from who.int. Nutrition values are from the Indian Food Composition
        Tables 2017, ICMR-National Institute of Nutrition. Menu norms follow PM POSHAN per-child
        entitlements. Report generated {report.period.generated_on} from{" "}
        {num(report.prevalence.measured)} measurements.
      </p>
    </footer>
  );
}

function Unavailable({ message }: { message: string }) {
  return (
    <main className="shell" style={{ paddingBlock: "var(--space-9)" }}>
      <p className="eyebrow">PoshanNetra</p>
      <h1 style={{ marginTop: "var(--space-4)", maxWidth: "18ch" }}>
        The report service is not reachable
      </h1>
      <p className="prose" style={{ marginTop: "var(--space-5)" }}>
        This page reads live figures from the PoshanNetra API. Start the backend and reload.
      </p>
      <pre
        className="card num"
        style={{ marginTop: "var(--space-5)", maxWidth: 640, whiteSpace: "pre-wrap" }}
      >
        cd backend &amp;&amp; make serve{"\n"}
        {message}
      </pre>
    </main>
  );
}
