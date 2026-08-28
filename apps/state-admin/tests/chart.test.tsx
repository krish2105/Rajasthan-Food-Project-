import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { DistributionChart } from "@/components/DistributionChart";
import type { Distribution } from "@/lib/report";

/**
 * The signature chart.
 *
 * Two classes of test: the arithmetic on screen must be right, and the chart
 * must be readable without seeing it. This report goes to a District
 * Collector's office and gets printed; a figure that only exists as SVG
 * geometry is a figure half the audience cannot read.
 */

const distribution: Distribution = {
  index: "haz",
  bin_width: 0.5,
  mean_z: -1.774,
  n: 10,
  bins: [
    { z: -6, count: 0 }, { z: -5.5, count: 0 }, { z: -5, count: 1 },
    { z: -4.5, count: 0 }, { z: -4, count: 0 }, { z: -3.5, count: 1 },
    { z: -3, count: 2 }, { z: -2.5, count: 2 }, { z: -2, count: 2 },
    { z: -1.5, count: 1 }, { z: -1, count: 1 }, { z: -0.5, count: 0 },
    { z: 0, count: 0 }, { z: 0.5, count: 0 },
  ],
};

describe("DistributionChart", () => {
  it("counts children below the −2 SD cut-off correctly", () => {
    // Bins ending at or before −2: −5, −3.5, −3, −2.5 => 1 + 1 + 2 + 2 = 6.
    render(<DistributionChart distribution={distribution} />);
    expect(screen.getByText(/6 of 10 children/)).toBeInTheDocument();
  });

  it("states what the WHO reference population would show", () => {
    // The comparison is the argument. Without it, a percentage is just a
    // number a reviewer has no scale for.
    render(<DistributionChart distribution={distribution} />);
    expect(screen.getByText(/2\.3% would/)).toBeInTheDocument();
  });

  it("reports the cohort mean against a reference mean of zero", () => {
    render(<DistributionChart distribution={distribution} />);
    expect(screen.getByText(/-1\.774 SD/)).toBeInTheDocument();
    expect(screen.getByText(/reference mean of 0/)).toBeInTheDocument();
  });

  it("describes itself for a screen reader", () => {
    render(<DistributionChart distribution={distribution} />);
    const figure = screen.getByRole("img");
    expect(figure).toHaveAccessibleName(/z-score distribution/i);
  });

  it("carries the same data as a table", () => {
    // Two of them, deliberately: one behind a <details> for screen, one always
    // present for print. The stylesheet hides the print copy on screen, but
    // jsdom loads no CSS, so both are queryable here.
    render(<DistributionChart distribution={distribution} />);
    const tables = screen.getAllByRole("table");
    expect(tables).toHaveLength(2);
    expect(within(tables[0]!).getByText(/-3.0 to -2.5/)).toBeInTheDocument();
  });

  it("prints a table when the chart itself cannot be printed", () => {
    // A reviewer reading this on A4 gets numbers, not a missing image.
    const { container } = render(<DistributionChart distribution={distribution} />);
    expect(container.querySelector(".only-print table")).toBeInTheDocument();
  });

  it("marks both WHO cut-offs on the axis", () => {
    const { container } = render(<DistributionChart distribution={distribution} />);
    const labels = [...container.querySelectorAll("text")].map((t) => t.textContent);
    expect(labels).toContain("−3 SD");
    expect(labels).toContain("−2 SD");
  });

  it("colours bars by severity band rather than uniformly", () => {
    // Colour alone never carries meaning here -- the cut-off rules and the
    // table say the same thing -- but it must at least be correct.
    const { container } = render(<DistributionChart distribution={distribution} />);
    const fills = [...container.querySelectorAll("rect.bar")].map((r) => r.getAttribute("fill"));
    expect(fills).toContain("var(--severe)");
    expect(fills).toContain("var(--moderate)");
    expect(fills).toContain("var(--indigo)");
  });

  it("says so plainly when there is nothing to plot", () => {
    render(
      <DistributionChart
        distribution={{ ...distribution, n: 0, bins: [], mean_z: null }}
      />,
    );
    expect(screen.getByText(/No measurements yet/)).toBeInTheDocument();
  });

  it("renders every bar, so severe children in the tail are never dropped", () => {
    const { container } = render(<DistributionChart distribution={distribution} />);
    expect(container.querySelectorAll("rect.bar")).toHaveLength(distribution.bins.length);
  });
});
