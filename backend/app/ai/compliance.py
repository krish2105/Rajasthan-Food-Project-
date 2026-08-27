"""Menu compliance: prescribed menu versus the plate actually served.

This is the Gadchiroli-precedent feature from Section 1, and it is the part of
the system that does something a paper register cannot. It answers two specific,
auditable questions:

  (a) the menu prescribed five items -- were five served?
  (b) was the dal watery, the fruit unripe, the portion short?

Note what it does *not* do. Section 15 is explicit that this system flags and
documents; it does not fix anything. A flagged day is the start of a human
administrative response, not a verdict, so every flag carries a reason a block
officer can act on and the raw counts behind it.

Aggregation is per centre per day, over every plate captured that day, because a
single child's plate is not evidence of a kitchen-level failure -- one missing
banana is a child who did not want a banana. A prescribed item absent from
*most* plates is a menu that was not served.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.nutrition.recipes import DISHES_BY_CODE

#: An item counts as served when it appears on at least this share of the day's
#: plates. Below it, the kitchen did not serve it. Deliberately not 100%: some
#: children refuse an item, and a threshold of 1.0 would flag every normal day
#: while a threshold near 0 would let a token single serving mask a shortfall.
SERVED_THRESHOLD = 0.60

#: Below this share of prescribed items, the day is flagged.
COMPLIANCE_FLAG_THRESHOLD = 100.0

#: Quality flags that indicate a food problem rather than a photography problem.
#: Image flags say the camera failed, not the kitchen, and must never be
#: reported to an officer as a compliance failure.
QUALITY_FLAGS = {
    "watery_appearance": ("Dal or curry appears watery", "दाल या सब्ज़ी पतली दिखी"),
    "portion_below_prescribed": ("Portions below prescribed quantity", "मात्रा निर्धारित से कम"),
    "item_appears_undercooked": ("Food appears undercooked", "खाना अधपका दिखा"),
    "fruit_unripe_or_overripe": ("Fruit unripe or overripe", "फल कच्चा या अधिक पका"),
    "plate_mostly_empty": ("Plates largely empty", "थालियाँ अधिकतर खाली"),
}
IMAGE_FLAGS = {"image_too_dark", "image_blurred", "plate_not_visible"}

#: A quality flag must appear on at least this share of a day's plates before it
#: becomes a centre-level finding. One watery bowl is not a kitchen problem.
QUALITY_FLAG_THRESHOLD = 0.34


@dataclass(frozen=True, slots=True)
class PlateObservation:
    """One captured plate, reduced to what compliance needs."""

    detected_codes: tuple[str, ...]
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ComplianceResult:
    prescribed_items: tuple[str, ...]
    detected_items: tuple[str, ...]
    missing_items: tuple[str, ...]
    unexpected_items: tuple[str, ...]
    compliance_pct: float
    flagged: bool
    flag_reason_en: str | None
    flag_reason_hi: str | None
    plates_analysed: int
    #: Per-item share of plates it appeared on, so an officer can see how close
    #: a borderline call was rather than trusting a bare boolean.
    item_presence: dict[str, float]
    quality_findings: tuple[str, ...]

    @property
    def flag_reason(self) -> str | None:
        if not self.flagged:
            return None
        return f"{self.flag_reason_en} | {self.flag_reason_hi}"


def evaluate(
    *,
    prescribed: list[str],
    plates: list[PlateObservation],
    served_threshold: float = SERVED_THRESHOLD,
) -> ComplianceResult:
    """Compare a day's plates against the prescribed menu."""
    prescribed_known = tuple(dict.fromkeys(c for c in prescribed if c in DISHES_BY_CODE))
    total = len(plates)

    if total == 0:
        # No captures is not compliance and it is not non-compliance. Saying so
        # is more useful than a 0% that reads as a kitchen failure.
        return ComplianceResult(
            prescribed_items=prescribed_known,
            detected_items=(),
            missing_items=prescribed_known,
            unexpected_items=(),
            compliance_pct=0.0,
            flagged=False,
            flag_reason_en=None,
            flag_reason_hi=None,
            plates_analysed=0,
            item_presence={},
            quality_findings=(),
        )

    counts = Counter(code for plate in plates for code in set(plate.detected_codes))
    presence = {code: counts.get(code, 0) / total for code in set(counts) | set(prescribed_known)}
    detected = tuple(sorted(c for c, share in presence.items() if share >= served_threshold))

    missing = tuple(c for c in prescribed_known if c not in detected)
    unexpected = tuple(sorted(c for c in detected if c not in prescribed_known))

    compliance_pct = (
        round(100.0 * (len(prescribed_known) - len(missing)) / len(prescribed_known), 2)
        if prescribed_known
        else 0.0
    )

    flag_counts = Counter(
        flag for plate in plates for flag in set(plate.quality_flags) if flag in QUALITY_FLAGS
    )
    quality_findings = tuple(
        sorted(f for f, n in flag_counts.items() if n / total >= QUALITY_FLAG_THRESHOLD)
    )

    reason_en = reason_hi = None
    flagged = False
    if missing:
        flagged = True
        names_en = ", ".join(DISHES_BY_CODE[c].name_en for c in missing)
        names_hi = ", ".join(DISHES_BY_CODE[c].name_hi for c in missing)
        reason_en = (
            f"Prescribed {len(prescribed_known)} items, {len(detected)} served "
            f"across {total} plates. Missing: {names_en}"
        )
        reason_hi = (
            f"निर्धारित {len(prescribed_known)} में से {len(detected)} वस्तुएँ परोसी गईं "
            f"({total} थालियों में)। अनुपस्थित: {names_hi}"
        )
    elif quality_findings:
        flagged = True
        reason_en = "; ".join(QUALITY_FLAGS[f][0] for f in quality_findings)
        reason_hi = "; ".join(QUALITY_FLAGS[f][1] for f in quality_findings)

    return ComplianceResult(
        prescribed_items=prescribed_known,
        detected_items=detected,
        missing_items=missing,
        unexpected_items=unexpected,
        compliance_pct=compliance_pct,
        flagged=flagged,
        flag_reason_en=reason_en,
        flag_reason_hi=reason_hi,
        plates_analysed=total,
        item_presence={k: round(v, 3) for k, v in sorted(presence.items())},
        quality_findings=quality_findings,
    )
