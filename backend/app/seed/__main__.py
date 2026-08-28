"""Seed the database with pitch-grade synthetic pilot data.

    python -m app.seed            # seed (idempotent: clears seeded tables first)
    python -m app.seed --dry-run  # generate and report, write nothing

Section 14 step 1: the demo build is seeded with synthetic data, and no real
child's data goes near this system before consent and legal sign-off. Every row
this script writes is generated; none of it describes a real person.

Runs under `admin_session` -- the owner connection that bypasses RLS -- because
seeding necessarily writes across every AWC. That is the only legitimate use of
that connection besides migrations, and the script refuses to run at all when
APP_ENV=production.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import uuid
from collections import Counter
from datetime import date

from sqlalchemy import delete, insert, select

from app.config import get_settings
from app.db.models import (
    AWC,
    Beneficiary,
    FieldWorker,
    GrowthEntry,
    MenuCompliance,
    MenuItem,
    PlateCapture,
)
from app.db.session import admin_session, dispose_engine
from app.db.url import DatabaseUrlError, normalise_database_url
from app.seed import generate, photos, reference
from app.storage import supabase_storage as storage

#: Share of children present on any given serving day.
ATTENDANCE = 0.70
PHOTO_VARIANTS = 12


def _report(title: str, counter: Counter, total: int) -> None:
    print(f"\n  {title}")
    for label, n in counter.most_common():
        print(f"    {label:28s} {n:5d}  ({100 * n / total:5.1f}%)")


async def _clear(session) -> None:
    """Delete in FK-safe order. Not TRUNCATE: this must work on Supabase where
    the connection may not own every dependent object."""
    for model in (
        MenuCompliance,
        PlateCapture,
        GrowthEntry,
        Beneficiary,
        FieldWorker,
        MenuItem,
        AWC,
    ):
        await session.execute(delete(model))


async def _upload_seed_photos(rng: random.Random) -> dict[str, list[str]]:
    """Upload the placeholder images once per AWC and return their paths.

    One set per AWC rather than one per capture: 3,700 uploads would take an
    hour and buy nothing. The first path segment is still the AWC code, which is
    what the Storage RLS policy matches on, so scoping behaves exactly as it
    will with real photos.
    """
    settings = get_settings()
    paths: dict[str, list[str]] = {a["awc_code"]: [] for a in reference.AWCS}
    if not (settings.seed_upload_photos and settings.storage_configured):
        # Fall back to plausible paths so the rows are still well-formed and
        # Phase 4/5 can be developed offline; signed URLs will simply 404.
        for awc in reference.AWCS:
            paths[awc["awc_code"]] = [
                f"{awc['awc_code']}/_seed/plate-{i:02d}.jpg" for i in range(PHOTO_VARIANTS)
            ]
        print("  photos: skipped upload (storage not configured or disabled)")
        return paths

    await storage.ensure_bucket()
    images = photos.variants(PHOTO_VARIANTS)
    for awc in reference.AWCS:
        for i, blob in enumerate(images):
            path = f"{awc['awc_code']}/_seed/plate-{i:02d}.jpg"
            await storage.upload_photo(path=path, data=blob, content_type="image/jpeg")
            paths[awc["awc_code"]].append(path)
    print(f"  photos: uploaded {PHOTO_VARIANTS} images x {len(reference.AWCS)} centres")
    return paths


async def seed(dry_run: bool = False) -> None:
    settings = get_settings()
    if not settings.seeding_allowed:
        # A deployed *demo* is meant to carry synthetic data (Section 14 step 1);
        # a real production database is not.
        sys.exit(
            "refusing to seed: APP_ENV=production. Use APP_ENV=demo for a seeded demo deployment."
        )

    rng = random.Random(settings.seed_random_seed)
    today = date.today()
    print(f"Seeding PoshanNetra (seed={settings.seed_random_seed}, today={today})")

    children = generate.make_children(rng, today)
    visits = generate.growth_visits(today)
    days = generate.serving_days(today)

    # --- growth entries -----------------------------------------------------
    growth_rows: list[dict] = []
    per_index: dict[str, Counter] = {
        k: Counter() for k in ("wasting", "thinness", "stunting", "underweight")
    }
    standards = Counter()
    latest_classification = Counter()
    latest_seen: set[int] = set()

    for visit_no, when in enumerate(reversed(visits), start=1):
        for child in children:
            m = generate.measurement_for(child, when, rng, visit_no)
            if m is None:
                continue
            height, weight = m
            a = generate.assess_measurement(child, when, height, weight)
            if a is None:
                continue
            growth_rows.append(
                {
                    "beneficiary_id": child.index,  # placeholder, remapped below
                    "awc_code": child.awc_code,
                    "district": child.district,
                    "recorded_at": when,
                    "height_cm": height,
                    "weight_kg": weight,
                    "age_months": a.age_months,
                    "standard_used": a.standard_used,
                    "waz_score": a.waz,
                    "haz_score": a.haz,
                    "whz_score": a.whz,
                    "baz_score": a.baz,
                    "bmi": a.bmi,
                    "classification": a.classification,
                    "classification_detail": a.classification_detail,
                }
            )
            standards[a.standard_used] += 1
            if child.index not in latest_seen and when == visits[-1]:
                latest_seen.add(child.index)
                latest_classification[a.classification] += 1
                for key, label in a.classification_detail.items():
                    if label is not None:
                        per_index[key][label] += 1

    # --- captures and compliance -------------------------------------------
    photo_paths = {} if dry_run else await _upload_seed_photos(rng)
    if dry_run:
        photo_paths = {
            a["awc_code"]: [
                f"{a['awc_code']}/_seed/plate-{i:02d}.jpg" for i in range(PHOTO_VARIANTS)
            ]
            for a in reference.AWCS
        }

    by_awc = {a["awc_code"]: a for a in reference.AWCS}
    capture_rows: list[dict] = []
    for day in days:
        for child in children:
            if rng.random() > ATTENDANCE:
                continue
            centre = by_awc[child.awc_code]
            meals = generate.MEAL_BY_CENTRE[centre["centre_type"]]
            for meal in meals:
                # Not every meal of every attended day is photographed -- a
                # worker with 45 children does not capture 135 plates a day.
                if rng.random() > 0.45:
                    continue
                variants = photo_paths[child.awc_code]
                capture_rows.append(
                    {
                        "beneficiary_id": child.index,  # remapped below
                        "awc_code": child.awc_code,
                        "district": child.district,
                        "photo_url": variants[rng.randrange(len(variants))],
                        "meal_type": meal,
                        "captured_at": generate.capture_times(day, meal, rng),
                        # Phase 1 has no AI pipeline, so every row is 'pending'
                        # and every ai_* column is NULL. Phase 2 fills them in.
                        "sync_status": "pending",
                    }
                )

    compliance_rows = [
        generate.compliance_for_day(by_awc[awc_code], day, rng)
        for awc_code in by_awc
        for day in days
    ]

    print(
        f"  generated: {len(children)} children, {len(growth_rows)} growth entries, "
        f"{len(capture_rows)} captures, {len(compliance_rows)} compliance rows"
    )

    if dry_run:
        _summarise(children, latest_classification, per_index, standards, compliance_rows)
        print("\n  --dry-run: nothing written")
        return

    async with admin_session() as session:
        async with session.begin():
            await _clear(session)

            await session.execute(
                insert(AWC),
                [
                    {k: v for k, v in a.items() if k not in ("child_count", "age_band_months")}
                    for a in reference.AWCS
                ],
            )
            await session.execute(insert(MenuItem), reference.MENU_ITEMS)
            await session.execute(insert(FieldWorker), reference.FIELD_WORKERS)

            beneficiary_rows = [
                {
                    "id": uuid.uuid4(),
                    "poshan_tracker_id": c.poshan_tracker_id,
                    "awc_code": c.awc_code,
                    "district": c.district,
                    "block": c.block,
                    "name": c.name,
                    "dob": c.dob,
                    "gender": c.gender,
                }
                for c in children
            ]
            await session.execute(insert(Beneficiary), beneficiary_rows)
            id_by_index = {c.index: beneficiary_rows[i]["id"] for i, c in enumerate(children)}

            worker_ids = dict(
                (r.awc_code, r.id)
                for r in (
                    await session.execute(
                        select(FieldWorker).where(FieldWorker.role == "field_worker")
                    )
                ).scalars()
            )

            for row in growth_rows:
                row["beneficiary_id"] = id_by_index[row["beneficiary_id"]]
                row["recorded_by"] = worker_ids.get(row["awc_code"])
            for row in capture_rows:
                row["beneficiary_id"] = id_by_index[row["beneficiary_id"]]
                row["field_worker_id"] = worker_ids.get(row["awc_code"])

            # Chunked: a single 3,700-row INSERT over a pooled Supabase
            # connection is a needlessly large statement to push over the wire.
            for chunk in _chunks(growth_rows, 500):
                await session.execute(insert(GrowthEntry), chunk)
            for chunk in _chunks(capture_rows, 500):
                await session.execute(insert(PlateCapture), chunk)
            await session.execute(insert(MenuCompliance), compliance_rows)

    _summarise(children, latest_classification, per_index, standards, compliance_rows)
    print("\n  seed complete.")


def _chunks(rows: list, size: int):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _summarise(children, latest, per_index, standards, compliance_rows) -> None:
    total = len(children)
    print("\n  Achieved prevalence at the most recent visit")
    print("  (measured from the seeded rows, not asserted -- these are the")
    print("   numbers that would be quoted, so they are computed, not claimed)")
    _report("primary classification (Poshan Tracker vocabulary)", latest, total)
    for key in ("stunting", "underweight", "wasting", "thinness"):
        if per_index[key]:
            _report(f"{key} (WHO detail)", per_index[key], total)
    print("\n  WHO reference used (deviation D1)")
    for std, n in standards.most_common():
        print(f"    {std:28s} {n:5d} entries")
    flagged = sum(1 for r in compliance_rows if r["flagged"])
    print(
        f"\n  menu compliance: {flagged}/{len(compliance_rows)} days flagged "
        f"({100 * flagged / len(compliance_rows):.1f}%)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed PoshanNetra sample data")
    parser.add_argument("--dry-run", action="store_true", help="generate and report only")
    args = parser.parse_args()
    try:
        asyncio.run(_run(args.dry_run))
    except DatabaseUrlError as exc:
        # Configuration mistake rather than a failure of the seed itself; the
        # message names what to fix, so a traceback adds nothing.
        print(f"\n{exc}\n", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)


async def _run(dry_run: bool) -> None:
    if not dry_run:
        # Validate before generating: building ~5,000 rows and only then
        # discovering the connection string is wrong wastes half a minute and
        # buries the real message under a page of progress output.
        normalise_database_url(get_settings().database_url)
    try:
        await seed(dry_run=dry_run)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    main()
