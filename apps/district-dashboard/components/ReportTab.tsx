"use client";

import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import { pct } from "@/lib/types";

/**
 * The district report.
 *
 * The same aggregation the state review uses, scoped down by RLS — not a
 * second implementation. Presented as tables rather than as the review
 * surface's charts, because this reader is comparing centres and will annotate
 * the result, not being persuaded by it.
 *
 * The one number carried over verbatim is the growth-classification
 * distribution across the block, which Section 9.2 asks for by name.
 */

interface Report {
  coverage: { centres: number; children: number; captures: number; growth_entries: number };
  prevalence: {
    measured: number; stunted: number; severely_stunted: number;
    underweight: number; severely_underweight: number; wasted: number;
    sam: number; mam: number; under_five: number; school_age: number;
    stunting_rate: number | null; underweight_rate: number | null;
    wasting_rate: number | null;
  };
  centres: Array<{
    awc_code: string; name_en: string; name_hi: string; block: string;
    centre_type: string; children: number; measured: number; stunted: number;
    sam: number; menu_days: number; flagged_days: number;
    compliance_pct: number | null; captures: number; stunting_rate: number | null;
  }>;
  trend: Array<{
    month: string; measured: number; stunting_rate: number | null;
    underweight_rate: number | null; sam: number; mean_haz: number | null;
  }>;
  compliance: {
    days: number; flagged: number; mean_compliance_pct: number | null;
    flag_rate: number | null; top_reasons: Array<{ reason: string; count: number }>;
  };
  data_quality: { flagged_measurements: number; ai_is_mock: boolean };
  period: { first_measurement: string | null; last_measurement: string | null };
}

const rate = (value: number | null) => (value === null ? "—" : `${(value * 100).toFixed(1)}%`);

export function ReportTab({ district }: { district: string | null }) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!district) {
      setError("No district on this account.");
      return;
    }
    void api
      .getDistrictReport(district)
      .then((r) => setReport(r as unknown as Report))
      .catch((err) =>
        setError(err instanceof api.ApiError ? err.message : "Could not load the report."),
      );
  }, [district]);

  if (error) return <p className="empty">{error}</p>;
  if (!report) return <p className="empty">Loading…</p>;

  const { coverage, prevalence, centres, trend, compliance, data_quality: quality } = report;

  return (
    <>
      <div className="summary-row">
        <Cell value={coverage.children} label="children enrolled" />
        <Cell value={prevalence.measured} label="measured" />
        <Cell value={coverage.centres} label="centres" />
        <Cell value={coverage.captures} label="plate photographs" />
      </div>

      <section className="panel">
        <div className="panel__body">
          <div className="section-head">
            <h2>Growth classification across the block</h2>
            <span className="count">
              latest measurement per child · {prevalence.measured} children
            </span>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Condition</th>
                <th scope="col" className="num">Children</th>
                <th scope="col" className="num">Of those severe</th>
                <th scope="col" className="num">Prevalence</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Stunted (height-for-age &lt; −2 SD)</td>
                <td className="num">{prevalence.stunted}</td>
                <td className="num">{prevalence.severely_stunted}</td>
                <td className="num">{rate(prevalence.stunting_rate)}</td>
              </tr>
              <tr>
                <td>Underweight (weight-for-age &lt; −2 SD)</td>
                <td className="num">{prevalence.underweight}</td>
                <td className="num">{prevalence.severely_underweight}</td>
                <td className="num">{rate(prevalence.underweight_rate)}</td>
              </tr>
              <tr>
                <td>Acute malnutrition</td>
                <td className="num">{prevalence.wasted}</td>
                <td className="num">{prevalence.sam}</td>
                <td className="num">{rate(prevalence.wasting_rate)}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="panel__body">
          {/* A child can appear in more than one row. Saying so prevents an
              officer summing the column and reporting a number larger than the
              cohort. */}
          <p className="note">
            A child can be counted in more than one row: stunting, underweight and
            wasting are different measurements, not a severity scale.{" "}
            {prevalence.under_five} children are under five and scored against the WHO
            2006 standards; {prevalence.school_age} are of school age and scored against
            the WHO 2007 reference.
          </p>
        </div>
      </section>

      <section className="panel">
        <div className="panel__body">
          <div className="section-head">
            <h2>By centre</h2>
            <span className="count">{centres.length} centres</span>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Centre</th>
                <th scope="col">Block</th>
                <th scope="col">Type</th>
                <th scope="col" className="num">Children</th>
                <th scope="col" className="num">Measured</th>
                <th scope="col" className="num">Stunting</th>
                <th scope="col" className="num">SAM</th>
                <th scope="col" className="num">Compliance</th>
                <th scope="col" className="num">Flagged</th>
                <th scope="col" className="num">Captures</th>
              </tr>
            </thead>
            <tbody>
              {centres.map((centre) => (
                <tr key={centre.awc_code}>
                  <td>
                    {centre.name_en}
                    <div className="muted deva" style={{ fontSize: 11 }}>{centre.name_hi}</div>
                  </td>
                  <td>{centre.block}</td>
                  <td>{centre.centre_type === "anganwadi" ? "Anganwadi" : "Ashram school"}</td>
                  <td className="num">{centre.children}</td>
                  <td className="num">{centre.measured}</td>
                  <td className="num">{rate(centre.stunting_rate)}</td>
                  <td className="num">{centre.sam}</td>
                  <td className="num">{pct(centre.compliance_pct, 1)}</td>
                  <td className="num">
                    {centre.flagged_days} / {centre.menu_days}
                  </td>
                  <td className="num">{centre.captures}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel__body">
          <div className="section-head">
            <h2>Month by month</h2>
            <span className="count">
              {report.period.first_measurement} to {report.period.last_measurement}
            </span>
          </div>
        </div>
        <div className="table-wrap">
          <table>
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
              {trend.map((month) => (
                <tr key={month.month}>
                  <td className="num">{month.month}</td>
                  <td className="num">{month.measured}</td>
                  <td className="num">{rate(month.stunting_rate)}</td>
                  <td className="num">{rate(month.underweight_rate)}</td>
                  <td className="num">{month.sam}</td>
                  <td className="num">{month.mean_haz ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel__body">
          <div className="section-head">
            <h2>Menu compliance</h2>
            <span className="count">
              {compliance.flagged} of {compliance.days} centre-days flagged
            </span>
          </div>
          {compliance.top_reasons.length > 0 && (
            <table style={{ marginTop: "var(--space-3)" }}>
              <thead>
                <tr>
                  <th scope="col">Most common reason</th>
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
          )}
        </div>
      </section>

      <section className="panel">
        <div className="panel__body">
          <div className="section-head">
            <h2>Before quoting any of this</h2>
          </div>
          <ul style={{ paddingLeft: "1.1rem", color: "var(--text-secondary)", fontSize: 13 }}>
            {quality.ai_is_mock && (
              <li>
                The food-recognition pipeline is running on an offline stand-in, so no
                nutrition estimate here comes from a real model. The growth figures are
                unaffected — those are arithmetic over WHO tables.
              </li>
            )}
            {quality.flagged_measurements > 0 && (
              <li>
                {quality.flagged_measurements} measurement
                {quality.flagged_measurements === 1 ? "" : "s"} fell outside WHO&rsquo;s
                plausible range and {quality.flagged_measurements === 1 ? "is" : "are"}{" "}
                excluded from every figure above, but retained for audit.
              </li>
            )}
            <li>
              This cohort is synthetic pilot data. It must not be quoted as a finding.
            </li>
          </ul>
        </div>
      </section>
    </>
  );
}

function Cell({ value, label }: { value: number; label: string }) {
  return (
    <div className="summary">
      <div className="summary__value">{value.toLocaleString("en-IN")}</div>
      <div className="summary__label">{label}</div>
    </div>
  );
}
