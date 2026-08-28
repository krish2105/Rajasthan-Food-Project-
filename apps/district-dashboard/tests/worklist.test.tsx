import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Worklist } from "@/components/Worklist";
import { FollowUpForm } from "@/components/FollowUpForm";
import * as api from "@/lib/api";
import type { FlaggedDay, QuietCentre, ReferralChild } from "@/lib/types";

/**
 * The worklist.
 *
 * This is the only surface in the system that tells a specific person to do a
 * specific thing, so these tests care about whether an officer can tell what
 * needs them, and whether recording what they did actually clears it.
 */

const flagged = (over: Partial<FlaggedDay> = {}): FlaggedDay => ({
  id: "c1", awc_code: "A1", district: "Banswara", date: "2026-08-22",
  name_en: "Anganwadi Centre, Ghatol-1", name_hi: "आंगनवाड़ी केंद्र, घाटोल-1",
  block: "Ghatol", block_hi: "घाटोल",
  prescribed_items: ["khichdi", "halwa", "banana"], detected_items: ["halwa"],
  missing_items: ["banana", "khichdi"], compliance_pct: 33.3,
  flag_reason_en: "Prescribed 3 items, 1 detected",
  flag_reason_hi: "निर्धारित 3 में से 1 वस्तुएँ मिलीं",
  follow_up_id: null, follow_up_outcome: null, follow_up_note: null,
  follow_up_at: null, follow_up_by: null,
  ...over,
});

const child = (over: Partial<ReferralChild> = {}): ReferralChild => ({
  beneficiary_id: "b1", name: "मनोज कटारा", gender: "M",
  poshan_tracker_id: "PT1", centre_en: "Ghatol-1", centre_hi: "घाटोल-1",
  block: "Ghatol", classification: "SAM", recorded_at: "2026-07-29",
  age_months: 67, height_cm: 100.2, weight_kg: 11.9,
  haz_score: -2.77, whz_score: -3.29, waz_score: -3.3, baz_score: null,
  ...over,
});

const quiet = (over: Partial<QuietCentre> = {}): QuietCentre => ({
  awc_code: "A2", name_en: "Ashram School", name_hi: "आश्रम विद्यालय",
  block: "Anandpuri", district: "Banswara",
  last_capture: null, total_captures: 0, ...over,
});

function stub({
  days = [flagged()],
  children = [child()],
  quietCentres = [] as QuietCentre[],
} = {}) {
  vi.spyOn(api, "getFlagged").mockResolvedValue({ since: "2026-07-29", items: days });
  vi.spyOn(api, "getQuietCentres").mockResolvedValue({ days: 3, items: quietCentres });
  vi.spyOn(api, "getReferrals").mockResolvedValue({ items: children });
  vi.spyOn(api, "getFollowUps").mockResolvedValue({ items: [] });
  vi.spyOn(api, "getCentreTrend").mockResolvedValue({ awc_code: "A1", points: [] });
}

beforeEach(() => vi.restoreAllMocks());

describe("Worklist", () => {
  it("leads with what the officer can act on today", async () => {
    stub({ children: [child(), child({ beneficiary_id: "b2", classification: "MAM" })] });
    render(<Worklist district="Banswara" />);
    await waitFor(() =>
      expect(screen.getByText("children at severe acute malnutrition")).toBeInTheDocument(),
    );
    // One SAM, one MAM, one flagged day, no quiet centres.
    const values = screen.getAllByText(/^[0-9]+$/).map((e) => e.textContent);
    expect(values.slice(0, 4)).toEqual(["1", "1", "1", "0"]);
  });

  it("names the missing menu items rather than only a percentage", async () => {
    // The officer acts on the gap, not on 33%.
    stub();
    render(<Worklist district="Banswara" />);
    expect(await screen.findByText("banana, khichdi")).toBeInTheDocument();
  });

  it("shows the flag reason a supervisor can act on", async () => {
    stub();
    render(<Worklist district="Banswara" />);
    expect(await screen.findByText("Prescribed 3 items, 1 detected")).toBeInTheDocument();
  });

  it("distinguishes outstanding items from resolved ones", async () => {
    stub({ days: [flagged({ follow_up_id: "f1", follow_up_outcome: "visited" })] });
    render(<Worklist district="Banswara" />);
    expect(await screen.findByText("visited")).toBeInTheDocument();
    expect(screen.queryByText("open")).not.toBeInTheDocument();
  });

  it("offers History rather than Follow up once something was recorded", async () => {
    stub({ days: [flagged({ follow_up_id: "f1", follow_up_outcome: "visited" })] });
    render(<Worklist district="Banswara" />);
    expect(await screen.findByRole("button", { name: "History" })).toBeInTheDocument();
  });

  it("expands a flagged day to show the centre's compliance and a form", async () => {
    stub();
    render(<Worklist district="Banswara" />);
    await userEvent.click(await screen.findByRole("button", { name: "Follow up" }));
    await waitFor(() =>
      expect(screen.getByText("This centre’s compliance")).toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Outcome")).toBeInTheDocument();
  });

  it("shows the flag reason in Hindi in the expanded detail", async () => {
    // The reason was authored bilingually upstream; the dashboard should not
    // silently drop half of it.
    stub();
    render(<Worklist district="Banswara" />);
    await userEvent.click(await screen.findByRole("button", { name: "Follow up" }));
    expect(await screen.findByText("निर्धारित 3 में से 1 वस्तुएँ मिलीं")).toBeInTheDocument();
  });

  it("orders referrals with the most severe first", async () => {
    stub({
      children: [
        child({ beneficiary_id: "a", classification: "SAM", name: "SAM child" }),
        child({ beneficiary_id: "b", classification: "MAM", name: "MAM child" }),
      ],
    });
    render(<Worklist district="Banswara" />);
    const table = (await screen.findAllByRole("table"))[0]!;
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]!.textContent).toContain("SAM child");
  });

  it("surfaces centres that have stopped uploading", async () => {
    // Silence is indistinguishable from compliance unless something looks.
    stub({ quietCentres: [quiet()] });
    render(<Worklist district="Banswara" />);
    expect(await screen.findByText("Ashram School")).toBeInTheDocument();
    expect(screen.getByText("never")).toBeInTheDocument();
  });

  it("says so plainly when there is nothing flagged", async () => {
    stub({ days: [] });
    render(<Worklist district="Banswara" />);
    expect(await screen.findByText(/Nothing flagged in the last 30 days/)).toBeInTheDocument();
  });

  it("offers a retry when the worklist cannot load", async () => {
    vi.spyOn(api, "getFlagged").mockRejectedValue(new api.ApiError("network down", 0));
    vi.spyOn(api, "getQuietCentres").mockResolvedValue({ days: 3, items: [] });
    vi.spyOn(api, "getReferrals").mockResolvedValue({ items: [] });
    render(<Worklist district="Banswara" />);
    expect(await screen.findByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("states that acting on a flag is the officer's job, not the system's", async () => {
    // Section 15: this system flags and documents; it does not fix.
    stub();
    render(<Worklist district="Banswara" />);
    expect(await screen.findByText(/the visit is yours/)).toBeInTheDocument();
  });
});

describe("FollowUpForm", () => {
  it("requires a reason before overruling a flag", async () => {
    // Enforced here, in the API, and by a database CHECK. Three layers for the
    // one field an officer is most likely to skip.
    const record = vi.spyOn(api, "recordFollowUp");
    render(<FollowUpForm complianceId="c1" onRecorded={() => {}} />);
    await userEvent.selectOptions(screen.getByLabelText("Outcome"), "no_action_needed");
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Say why this flag did not need acting on",
    );
    expect(record).not.toHaveBeenCalled();
  });

  it("marks the note required only for that outcome", async () => {
    render(<FollowUpForm complianceId="c1" onRecorded={() => {}} />);
    expect(screen.getByText("Note (optional)")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Outcome"), "no_action_needed");
    expect(screen.getByText("Note (required)")).toBeInTheDocument();
  });

  it("records the outcome and note", async () => {
    const record = vi.spyOn(api, "recordFollowUp").mockResolvedValue({
      id: "f1", outcome: "visited", note: "Supply chased.", recorded_at: "2026-08-28T10:00:00Z",
    });
    const onRecorded = vi.fn();
    render(<FollowUpForm complianceId="c1" onRecorded={onRecorded} />);
    await userEvent.type(screen.getByLabelText(/^Note/), "Supply chased.");
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    await waitFor(() =>
      expect(record).toHaveBeenCalledWith("c1", {
        outcome: "visited",
        note: "Supply chased.",
      }),
    );
    expect(onRecorded).toHaveBeenCalled();
  });

  it("reports a save failure instead of pretending it worked", async () => {
    vi.spyOn(api, "recordFollowUp").mockRejectedValue(new api.ApiError("conflict", 409));
    render(<FollowUpForm complianceId="c1" onRecorded={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("conflict");
  });
});
