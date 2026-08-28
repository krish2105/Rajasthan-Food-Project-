"use client";

import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import { ReportTab } from "@/components/ReportTab";
import { Worklist } from "@/components/Worklist";
import type { Scope } from "@/lib/types";
import { SignIn } from "@/components/SignIn";

/**
 * District Dashboard (Section 9.2).
 *
 * Two tabs, and the order is the argument: the worklist opens first because a
 * block officer arrives with "what needs me today", and the report is what they
 * consult second. A Collector wanting the report is one click away; an officer
 * wanting their queue is zero.
 *
 * Deliberately plainer than the state review. Same palette, denser tables, no
 * entrance animations — Section 9.2 asks for a working tool, not a showcase.
 */

type Tab = "worklist" | "report";
type Status = "checking" | "signed-out" | "ready" | "error";

export default function Dashboard() {
  const [tab, setTab] = useState<Tab>("worklist");
  const [scope, setScope] = useState<Scope | null>(null);
  const [status, setStatus] = useState<Status>("checking");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .getScope()
      .then((result) => {
        setScope(result);
        setStatus("ready");
      })
      .catch((err) => {
        // 401 means no session, not a broken deployment. Those need different
        // screens: one is a door, the other is a fault.
        if (err instanceof api.ApiError && (err.status === 401 || err.status === 0)) {
          setStatus("signed-out");
          return;
        }
        setError("The API is not reachable. Start the backend and reload.");
        setStatus("error");
      });
  }, []);

  if (status === "checking") return null;

  if (status === "signed-out") {
    return (
      <SignIn
        title="District dashboard sign-in"
        subtitle="PoshanNetra · पोषण नेत्र"
      />
    );
  }

  if (error) {
    return (
      <main className="shell">
        <div className="panel" style={{ marginTop: "var(--space-7)" }}>
          <div className="panel__body">
            <h1 style={{ fontSize: 18, marginBottom: "var(--space-3)" }}>
              District Dashboard unavailable
            </h1>
            <p className="muted" style={{ fontSize: 13 }}>{error}</p>
            <pre
              className="note"
              style={{ marginTop: "var(--space-4)", fontSize: 12, whiteSpace: "pre-wrap" }}
            >
              cd backend &amp;&amp; make serve
            </pre>
          </div>
        </div>
      </main>
    );
  }

  return (
    <>
      <header className="topbar">
        <div className="shell topbar__inner">
          <div className="brand">
            PoshanNetra
            <small>District Dashboard</small>
          </div>
          <nav className="tabs" role="tablist" aria-label="Dashboard views">
            <button
              type="button" role="tab" className="tab"
              aria-selected={tab === "worklist"}
              aria-controls="panel-worklist"
              onClick={() => setTab("worklist")}
            >
              Worklist
            </button>
            <button
              type="button" role="tab" className="tab"
              aria-selected={tab === "report"}
              aria-controls="panel-report"
              onClick={() => setTab("report")}
            >
              Report
            </button>
          </nav>
          <div className="scope">
            {scope ? (
              <>
                {scope.district ?? "All districts"} · {scope.role.replace("_", " ")}
              </>
            ) : (
              "…"
            )}
          </div>
        </div>
      </header>

      <main className="shell">
        {tab === "worklist" ? (
          <div id="panel-worklist" role="tabpanel">
            <Worklist district={scope?.district ?? null} />
          </div>
        ) : (
          <div id="panel-report" role="tabpanel">
            <ReportTab district={scope?.district ?? null} />
          </div>
        )}
      </main>
    </>
  );
}
