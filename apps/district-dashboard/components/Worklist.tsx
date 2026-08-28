"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import { CentreTrend } from "./CentreTrend";
import { FollowUpForm } from "./FollowUpForm";
import type { FlaggedDay, FollowUpRecord, QuietCentre, ReferralChild, TrendPoint } from "@/lib/types";
import { daysAgo, pct, shortDate } from "@/lib/types";

/**
 * The worklist: what needs this officer's attention.
 *
 * Ordered by what a block officer can actually do something about. Children at
 * severe acute malnutrition come first because that is a referral today; flagged
 * menu days come second because they are this week; centres that have gone
 * quiet come last because that is usually a broken phone rather than a broken
 * kitchen — but it still hides everything else, so it cannot be left off.
 *
 * No entrance animations anywhere on this surface. Section 9.2 asks for a
 * working tool, and a busy official should not wait for content to fade in.
 */

export function Worklist({ district }: { district: string | null }) {
  const [flagged, setFlagged] = useState<FlaggedDay[]>([]);
  const [quiet, setQuiet] = useState<QuietCentre[]>([]);
  const [referrals, setReferrals] = useState<ReferralChild[]>([]);
  const [showResolved, setShowResolved] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [flaggedResult, quietResult] = await Promise.all([
        api.getFlagged({ includeResolved: showResolved }),
        api.getQuietCentres(3),
      ]);
      setFlagged(flaggedResult.items);
      setQuiet(quietResult.items);
      if (district) {
        const referralResult = await api.getReferrals(district, ["SAM", "MAM"]);
        setReferrals(referralResult.items);
      }
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Could not load the worklist.");
    } finally {
      setLoading(false);
    }
  }, [district, showResolved]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <p className="empty">Loading…</p>;
  if (error) {
    return (
      <div className="panel">
        <div className="panel__body">
          <p className="error">{error}</p>
          <button type="button" className="btn" onClick={() => void load()}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  const sam = referrals.filter((c) => c.classification === "SAM");
  const outstanding = flagged.filter((f) => !f.follow_up_id);

  return (
    <>
      <div className="summary-row">
        <div className={`summary ${sam.length ? "summary--alert" : ""}`}>
          <div className="summary__value">{sam.length}</div>
          <div className="summary__label">children at severe acute malnutrition</div>
        </div>
        <div className={`summary ${outstanding.length ? "summary--warn" : ""}`}>
          <div className="summary__value">{outstanding.length}</div>
          <div className="summary__label">flagged days awaiting follow-up</div>
        </div>
        <div className="summary">
          <div className="summary__value">{referrals.length - sam.length}</div>
          <div className="summary__label">children at moderate acute malnutrition</div>
        </div>
        <div className={`summary ${quiet.length ? "summary--warn" : ""}`}>
          <div className="summary__value">{quiet.length}</div>
          <div className="summary__label">centres not uploading</div>
        </div>
      </div>

      <ReferralSection referrals={referrals} />

      <section className="panel">
        <div className="panel__body">
          <div className="section-head">
            <h2>Flagged days</h2>
            <span className="count">
              {outstanding.length} outstanding
              {showResolved ? ` · ${flagged.length - outstanding.length} resolved` : ""}
            </span>
            <label
              style={{ marginLeft: "auto", fontSize: 12, display: "flex", gap: 6 }}
            >
              <input
                type="checkbox"
                checked={showResolved}
                onChange={(e) => setShowResolved(e.target.checked)}
              />
              Show resolved
            </label>
          </div>
          <p className="note" style={{ marginBottom: "var(--space-3)" }}>
            A flagged day is a menu the plates did not match, or a food-quality
            problem seen across most plates. This system records the flag; the
            visit is yours.
          </p>
        </div>

        {flagged.length === 0 ? (
          <p className="empty">Nothing flagged in the last 30 days.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Centre</th>
                  <th scope="col" className="num">Compliance</th>
                  <th scope="col">Missing</th>
                  <th scope="col">Reason</th>
                  <th scope="col">Status</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {flagged.map((day) => (
                  <FlaggedRow
                    key={day.id}
                    day={day}
                    expanded={expanded === day.id}
                    onToggle={() => setExpanded(expanded === day.id ? null : day.id)}
                    onRecorded={() => {
                      setExpanded(null);
                      void load();
                    }}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <QuietSection quiet={quiet} />
    </>
  );
}

function ReferralSection({ referrals }: { referrals: ReferralChild[] }) {
  return (
    <section className="panel">
      <div className="panel__body">
        <div className="section-head">
          <h2>Children needing referral</h2>
          <span className="count">{referrals.length} from the latest measurement</span>
        </div>
        <p className="note">
          Classified by WHO z-score from each child&rsquo;s most recent plausible
          measurement — the same basis as every prevalence figure in the report tab.
        </p>
      </div>
      {referrals.length === 0 ? (
        <p className="empty">No child is currently classified SAM or MAM.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Child</th>
                <th scope="col">Centre</th>
                <th scope="col">Status</th>
                <th scope="col" className="num">Age</th>
                <th scope="col" className="num">Height</th>
                <th scope="col" className="num">Weight</th>
                <th scope="col" className="num">WHZ</th>
                <th scope="col" className="num">HAZ</th>
                <th scope="col">Last measured</th>
              </tr>
            </thead>
            <tbody>
              {referrals.map((child) => (
                <tr key={child.beneficiary_id}>
                  <td>
                    {child.name}
                    {child.poshan_tracker_id && (
                      <div className="muted" style={{ fontSize: 11 }}>
                        {child.poshan_tracker_id}
                      </div>
                    )}
                  </td>
                  <td>
                    {child.block}
                    <div className="muted deva" style={{ fontSize: 11 }}>
                      {child.centre_hi}
                    </div>
                  </td>
                  <td>
                    <span
                      className={`pill pill--${child.classification.toLowerCase()}`}
                    >
                      {child.classification}
                    </span>
                  </td>
                  <td className="num">{child.age_months}m</td>
                  <td className="num">{child.height_cm ?? "—"}</td>
                  <td className="num">{child.weight_kg ?? "—"}</td>
                  <td className="num">{child.whz_score ?? child.baz_score ?? "—"}</td>
                  <td className="num">{child.haz_score ?? "—"}</td>
                  {/* Recency matters: an SAM child last seen six weeks ago is a
                      more urgent visit than one measured yesterday. */}
                  <td className={daysAgoIsStale(child.recorded_at) ? "" : "muted"}>
                    {daysAgo(child.recorded_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function daysAgoIsStale(iso: string): boolean {
  return Date.now() - new Date(iso).getTime() > 30 * 86_400_000;
}

function FlaggedRow({
  day,
  expanded,
  onToggle,
  onRecorded,
}: {
  day: FlaggedDay;
  expanded: boolean;
  onToggle: () => void;
  onRecorded: () => void;
}) {
  const [trail, setTrail] = useState<FollowUpRecord[]>([]);
  const [trend, setTrend] = useState<TrendPoint[]>([]);

  useEffect(() => {
    if (!expanded) return;
    void api.getFollowUps(day.id).then((r) => setTrail(r.items)).catch(() => setTrail([]));
    void api.getCentreTrend(day.awc_code).then((r) => setTrend(r.points)).catch(() => setTrend([]));
  }, [expanded, day.id, day.awc_code]);

  return (
    <>
      <tr>
        <td className="num">{shortDate(day.date)}</td>
        <td>
          {day.block}
          <div className="muted deva" style={{ fontSize: 11 }}>{day.name_hi}</div>
        </td>
        <td className="num">{pct(day.compliance_pct)}</td>
        <td>{day.missing_items.length ? day.missing_items.join(", ") : "—"}</td>
        <td style={{ maxWidth: 320 }}>{day.flag_reason_en ?? "—"}</td>
        <td>
          {day.follow_up_id ? (
            <span className="pill pill--done">{day.follow_up_outcome}</span>
          ) : (
            <span className="pill pill--open">open</span>
          )}
        </td>
        <td>
          <button
            type="button"
            className="btn btn--sm"
            onClick={onToggle}
            aria-expanded={expanded}
          >
            {expanded ? "Close" : day.follow_up_id ? "History" : "Follow up"}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={7} className="detail">
            <div style={{ display: "grid", gap: "var(--space-4)" }}>
              <div>
                <strong style={{ fontSize: 13 }}>{day.name_en}</strong>
                <p className="muted deva" style={{ fontSize: 12 }}>
                  {day.flag_reason_hi}
                </p>
                <p className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                  Prescribed: {day.prescribed_items.join(", ")} · Detected:{" "}
                  {day.detected_items.join(", ") || "none"}
                </p>
              </div>

              <div>
                <div className="section-head">
                  <h2 style={{ fontSize: 13 }}>This centre&rsquo;s compliance</h2>
                </div>
                <CentreTrend points={trend} />
              </div>

              {trail.length > 0 && (
                <div>
                  <div className="section-head">
                    <h2 style={{ fontSize: 13 }}>Follow-up history</h2>
                    <span className="count">append-only</span>
                  </div>
                  <ul className="trail">
                    {trail.map((entry) => (
                      <li key={entry.id}>
                        <strong>{entry.outcome}</strong> ·{" "}
                        {new Date(entry.recorded_at).toLocaleString("en-IN")}
                        {entry.note && <div>{entry.note}</div>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <FollowUpForm complianceId={day.id} onRecorded={onRecorded} />
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function QuietSection({ quiet }: { quiet: QuietCentre[] }) {
  return (
    <section className="panel">
      <div className="panel__body">
        <div className="section-head">
          <h2>Centres not uploading</h2>
          <span className="count">{quiet.length} with nothing in 3 days</span>
        </div>
        <p className="note">
          Usually a phone or a connection rather than a kitchen (Section 7 treats
          connectivity as the likeliest failure point). Either way, a centre that
          sends nothing is invisible to every other view on this page.
        </p>
      </div>
      {quiet.length === 0 ? (
        <p className="empty">Every centre has uploaded recently.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Centre</th>
                <th scope="col">Block</th>
                <th scope="col">Last upload</th>
                <th scope="col" className="num">Total captures</th>
              </tr>
            </thead>
            <tbody>
              {quiet.map((centre) => (
                <tr key={centre.awc_code}>
                  <td>
                    {centre.name_en}
                    <div className="muted deva" style={{ fontSize: 11 }}>{centre.name_hi}</div>
                  </td>
                  <td>{centre.block}</td>
                  <td>{daysAgo(centre.last_capture)}</td>
                  <td className="num">{centre.total_captures}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
