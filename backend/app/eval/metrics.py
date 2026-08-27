"""Section 6.5 metrics, and the rules about when they may be reported.

The targets, verbatim from the master prompt:

    Food item recognition (top-3 accuracy)   >= 80%
    Portion / quantity estimate              MAE <= 25 g per item
    Calorie estimate                         MAE <= 15% of true value
    Menu compliance flag                     precision >= 0.85, recall >= 0.85
    WHO z-score classification               100% exact  (done in Phase 1)

Three refusals are built in, because the failure mode this harness exists to
prevent is a confident number with nothing behind it:

1. **n = 0 reports `unvalidated`,** never 0% and never a default. An empty
   golden set is the honest state today (Section 15), not a failing score.
2. **Mock-provider runs cannot produce accuracy metrics.** The offline provider
   validates plumbing, not recognition. Scoring against it would manufacture
   exactly the false number Section 6.5 warns about.
3. **Calorie error is measured against an uncalibrated reference** until the
   Section 14 step 3 calibration session happens, and every result says so. The
   recipe yield factors are a documented prior, not a measurement.

Calorie MAE deliberately isolates *vision* error. Ground-truth calories are
computed from the ground-truth grams through the same deterministic nutrition
path the pipeline uses, so the metric measures how well the model estimated the
portion -- not how well IFCT describes a lentil. Mixing the two would make a
recipe correction look like a model regression.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from app.nutrition import compute, recipes

TARGETS = {
    "recognition_top3": 0.80,
    "portion_mae_g": 25.0,
    "calorie_mape": 0.15,
    "compliance_precision": 0.85,
    "compliance_recall": 0.85,
}

UNVALIDATED = "unvalidated"


@dataclass(frozen=True, slots=True)
class Metric:
    name: str
    value: float | None
    n: int
    target: float
    #: True when higher is better (accuracy); False for error metrics.
    higher_is_better: bool
    unit: str = ""
    caveats: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if self.value is None or self.n == 0:
            return UNVALIDATED
        if self.higher_is_better:
            return "meets target" if self.value >= self.target else "below target"
        return "meets target" if self.value <= self.target else "above target"

    def render(self) -> str:
        if self.value is None or self.n == 0:
            return f"{self.name:34s} {UNVALIDATED:>14s}  (n=0)"
        comparator = ">=" if self.higher_is_better else "<="
        return (
            f"{self.name:34s} {self.value:>10.3f}{self.unit:<4s}  "
            f"(n={self.n}, target {comparator} {self.target}{self.unit}) "
            f"-- {self.status}"
        )


@dataclass
class EvalReport:
    metrics: list[Metric] = field(default_factory=list)
    #: Blocking reasons why no metric may be trusted at all.
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def any_validated(self) -> bool:
        return not self.blockers and any(m.status != UNVALIDATED for m in self.metrics)


def top_k_recognition(
    truth_codes: list[set[str]], predicted_ranked: list[list[str]], k: int = 3
) -> tuple[float | None, int]:
    """Share of true dishes appearing in the model's top-k detections.

    Per-item rather than per-plate: a plate with four dishes contributes four
    observations. A per-plate metric would let a model that finds rice and
    misses everything else score the same as one that finds nothing.
    """
    hits = total = 0
    for truth, ranked in zip(truth_codes, predicted_ranked, strict=True):
        top = ranked[:k]
        for code in truth:
            total += 1
            hits += code in top
    if total == 0:
        return None, 0
    return hits / total, total


def portion_mae(
    pairs: list[tuple[float, float]],
) -> tuple[float | None, int]:
    """Mean absolute error in grams over (true, predicted) item pairs.

    Only items the model actually detected are scored. A missed item is a
    *recognition* failure and is counted there; charging it to portion error as
    well would penalise the same mistake twice and make the two metrics move
    together for no reason.
    """
    if not pairs:
        return None, 0
    return mean(abs(t - p) for t, p in pairs), len(pairs)


def calorie_mape(pairs: list[tuple[float, float]]) -> tuple[float | None, int]:
    """Mean absolute percentage error on plate energy."""
    usable = [(t, p) for t, p in pairs if t > 0]
    if not usable:
        return None, 0
    return mean(abs(t - p) / t for t, p in usable), len(usable)


def precision_recall(
    truth: list[bool], predicted: list[bool]
) -> tuple[float | None, float | None, int]:
    """Precision and recall for the compliance flag.

    Both matter, and differently. A false positive sends a block officer to a
    school that was fine, which wastes scarce time and burns the programme's
    credibility. A false negative lets a genuinely non-compliant kitchen pass,
    which is the failure the system exists to catch. Section 6.5 sets both at
    0.85 rather than optimising one.
    """
    if not truth:
        return None, None, 0
    tp = sum(1 for t, p in zip(truth, predicted, strict=True) if t and p)
    fp = sum(1 for t, p in zip(truth, predicted, strict=True) if not t and p)
    fn = sum(1 for t, p in zip(truth, predicted, strict=True) if t and not p)
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return precision, recall, len(truth)


def truth_energy_kcal(items: list[tuple[str, float]]) -> float:
    """Ground-truth plate energy, via the same deterministic path as the pipeline.

    Uses the labelled grams, so any difference from the predicted figure is
    attributable to the vision model's portion estimate and nothing else.
    """
    plate = [(recipes.get(code), grams) for code, grams in items]
    return compute.for_plate(plate).energy_kcal


def build_report(
    *,
    truth_codes: list[set[str]],
    predicted_ranked: list[list[str]],
    portion_pairs: list[tuple[float, float]],
    calorie_pairs: list[tuple[float, float]],
    compliance_truth: list[bool],
    compliance_pred: list[bool],
    is_mock: bool,
    weighed_only: bool,
    uncalibrated_dishes: set[str],
) -> EvalReport:
    report = EvalReport()

    if is_mock:
        report.blockers.append(
            "Run used AI_PROVIDER=mock. The offline provider validates the "
            "pipeline's plumbing, not recognition -- accuracy metrics from it "
            "would be meaningless. Set AI_PROVIDER=gemini with a free-tier key "
            "to produce real numbers."
        )

    top3, n_reco = top_k_recognition(truth_codes, predicted_ranked)
    mae, n_portion = portion_mae(portion_pairs)
    mape, n_cal = calorie_mape(calorie_pairs)
    precision, recall, n_days = precision_recall(compliance_truth, compliance_pred)

    portion_caveats: tuple[str, ...] = ()
    if n_portion and not weighed_only:
        portion_caveats = (
            "Includes plates whose grams were estimated by eye rather than "
            "weighed. Section 6.5's target assumes dietitian-weighed reference "
            "plates; treat this as indicative until the Section 14 step 3 "
            "calibration session is done.",
        )

    calorie_caveats: tuple[str, ...] = ()
    if uncalibrated_dishes:
        calorie_caveats = (
            "Reference energy uses recipe yield factors that are standard "
            "kitchen values, not measured: "
            + ", ".join(sorted(uncalibrated_dishes))
            + ". A systematic yield error moves truth and prediction together "
            "and would not show up here.",
        )

    report.metrics = [
        Metric("Food recognition (top-3)", top3, n_reco, TARGETS["recognition_top3"], True),
        Metric(
            "Portion estimate MAE",
            mae,
            n_portion,
            TARGETS["portion_mae_g"],
            False,
            unit=" g",
            caveats=portion_caveats,
        ),
        Metric(
            "Calorie estimate MAPE",
            mape,
            n_cal,
            TARGETS["calorie_mape"],
            False,
            caveats=calorie_caveats,
        ),
        Metric(
            "Compliance flag precision", precision, n_days, TARGETS["compliance_precision"], True
        ),
        Metric("Compliance flag recall", recall, n_days, TARGETS["compliance_recall"], True),
    ]
    return report
