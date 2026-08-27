"""Run the Section 6.5 evaluation harness.

    python -m app.eval                 # run against the golden set
    python -m app.eval --json          # machine-readable, for CI

Exit codes: 0 when every validated metric meets its target (or nothing is
validated yet), 1 when a validated metric misses. An empty golden set is not a
failure -- it is today's honest state.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from app.ai import client, pipeline
from app.ai.compliance import PlateObservation
from app.ai.compliance import evaluate as evaluate_compliance
from app.eval import golden, metrics
from app.nutrition.recipes import DISHES_BY_CODE, Calibration


async def run() -> metrics.EvalReport:
    data = golden.load()

    truth_codes: list[set[str]] = []
    predicted_ranked: list[list[str]] = []
    portion_pairs: list[tuple[float, float]] = []
    calorie_pairs: list[tuple[float, float]] = []
    uncalibrated: set[str] = set()
    plate_results: dict[str, pipeline.PipelineResult] = {}
    skipped: list[str] = []

    for plate in data.plates:
        if not plate.image_path.exists():
            skipped.append(f"{plate.image} (file missing)")
            continue
        result = await pipeline.analyse_plate(
            image_bytes=plate.image_path.read_bytes(),
            meal_type=plate.meal_type,
            prescribed=list(plate.prescribed),
            run_anomaly_pass=False,  # advisory only; adds latency, not signal
        )
        plate_results[plate.image] = result
        if not result.ok:
            skipped.append(f"{plate.image} ({result.error})")
            continue

        costed = [i for i in result.food_items if i.get("costed")]
        ranked = [
            i["dish_code"]
            for i in sorted(costed, key=lambda i: -i["confidence"])
            if i.get("dish_code")
        ]
        truth_codes.append(plate.dish_codes)
        predicted_ranked.append(ranked)

        for item in costed:
            true_g = plate.grams_for(item.get("dish_code") or "")
            if true_g is not None:
                portion_pairs.append((true_g, float(item["cooked_grams"])))

        truth_kcal = metrics.truth_energy_kcal([(i.dish_code, i.cooked_grams) for i in plate.items])
        calorie_pairs.append((truth_kcal, result.energy_kcal or 0.0))

        for code in plate.dish_codes:
            if DISHES_BY_CODE[code].calibration == Calibration.UNCALIBRATED:
                uncalibrated.add(code)

    compliance_truth: list[bool] = []
    compliance_pred: list[bool] = []
    for day in data.compliance_days:
        observations = []
        for image in day.images:
            result = plate_results.get(image)
            if result is None or not result.ok:
                continue
            observations.append(
                PlateObservation(
                    detected_codes=tuple(
                        i["dish_code"]
                        for i in result.food_items
                        if i.get("costed") and i.get("dish_code")
                    ),
                    quality_flags=result.quality_flags,
                )
            )
        if not observations:
            skipped.append(f"{day.awc_code} {day.day} (no usable plate results)")
            continue
        outcome = evaluate_compliance(prescribed=list(day.prescribed), plates=observations)
        compliance_truth.append(day.should_flag)
        compliance_pred.append(outcome.flagged)

    report = metrics.build_report(
        truth_codes=truth_codes,
        predicted_ranked=predicted_ranked,
        portion_pairs=portion_pairs,
        calorie_pairs=calorie_pairs,
        compliance_truth=compliance_truth,
        compliance_pred=compliance_pred,
        is_mock=client.provider() == "mock",
        weighed_only=bool(data.plates) and all(p.weighed for p in data.plates),
        uncalibrated_dishes=uncalibrated,
    )

    if data.is_empty:
        report.notes.append(
            "Golden set is empty. Section 15: no labelled dataset exists for "
            "tribal-Rajasthan dishes; it must be built during pilot week 1 from "
            "roughly 200-300 photographs. See app/eval/golden/README.md."
        )
    missing = data.missing_images()
    if missing:
        report.notes.append(f"{len(missing)} labelled image(s) not found on disk.")
    if skipped:
        # Never silently drop a plate: an unreported skip makes a partial run
        # look like a complete one.
        report.notes.append(f"{len(skipped)} item(s) skipped: {'; '.join(skipped[:5])}")
    return report


def render(report: metrics.EvalReport) -> str:
    lines = [
        "PoshanNetra AI -- evaluation harness (master prompt, Section 6.5)",
        "=" * 72,
        "",
    ]
    for metric in report.metrics:
        lines.append("  " + metric.render())
        for caveat in metric.caveats:
            lines.append(f"      caveat: {caveat}")
    lines.append("")
    lines.append("  WHO z-score classification         exact match on all 10,638")
    lines.append("      published WHO values -- see tests/test_who_lms.py (Phase 1).")
    if report.blockers:
        lines += ["", "  BLOCKERS -- no accuracy metric from this run may be quoted:"]
        lines += [f"    - {b}" for b in report.blockers]
    if report.notes:
        lines += ["", "  Notes:"]
        lines += [f"    - {n}" for n in report.notes]
    lines += [
        "",
        "  Section 15 requires that any pitch cite these numbers rather than",
        "  projections. An 'unvalidated' row is the honest answer until the",
        "  golden set exists -- it is not a zero, and not a pass.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PoshanNetra eval harness")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    report = asyncio.run(run())

    if args.json:
        print(
            json.dumps(
                {
                    "metrics": [asdict(m) | {"status": m.status} for m in report.metrics],
                    "blockers": report.blockers,
                    "notes": report.notes,
                    "any_validated": report.any_validated,
                },
                indent=2,
            )
        )
    else:
        print(render(report))

    failed = [
        m
        for m in report.metrics
        if m.status in {"below target", "above target"} and not report.blockers
    ]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
