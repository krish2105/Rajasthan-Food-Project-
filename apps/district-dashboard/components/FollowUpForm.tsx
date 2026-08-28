"use client";

import { useState } from "react";
import { OUTCOMES } from "@/lib/types";
import * as api from "@/lib/api";

/**
 * Record what was done about a flagged day.
 *
 * Section 15 is the boundary this form sits on: the system flags and documents,
 * a human acts. This documents the action; it does not perform one.
 *
 * `no_action_needed` requires a reason, enforced here, in the API and by a
 * database CHECK. Overruling a flag is the one outcome where the next person to
 * read the record needs to know why, and three layers is not excessive for the
 * one field an officer is most likely to skip.
 */
export function FollowUpForm({
  complianceId,
  onRecorded,
}: {
  complianceId: string;
  onRecorded: () => void;
}) {
  const [outcome, setOutcome] = useState<string>(OUTCOMES[0].value);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const needsNote = outcome === "no_action_needed";

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (needsNote && !note.trim()) {
      setError("Say why this flag did not need acting on.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.recordFollowUp(complianceId, {
        outcome,
        note: note.trim() || undefined,
      });
      setNote("");
      onRecorded();
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <div className="field-row">
        <div className="field" style={{ minWidth: 220 }}>
          <label htmlFor={`outcome-${complianceId}`}>Outcome</label>
          <select
            id={`outcome-${complianceId}`}
            className="input"
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
          >
            {OUTCOMES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ flex: 1, minWidth: 260 }}>
          <label htmlFor={`note-${complianceId}`}>
            Note{needsNote ? " (required)" : " (optional)"}
          </label>
          <input
            id={`note-${complianceId}`}
            className="input"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={
              needsNote
                ? "Why did this flag not need acting on?"
                : "What did you find, and what happens next?"
            }
            aria-invalid={error ? true : undefined}
          />
        </div>
        <button type="submit" className="btn btn--primary" disabled={busy}>
          {busy ? "Saving…" : "Record"}
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
