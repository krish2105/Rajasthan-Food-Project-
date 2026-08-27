"""Vendor the IFCT 2017 nutrition table into the repo as CSV.

Run once (or when the upstream package is updated):
    python scripts/fetch_ifct_table.py

Why IFCT and not USDA
---------------------
Section 4 of the master prompt is explicit: the Indian Food Composition Tables
(ICMR-NIN, 2017) are the correct authoritative source for this system, and using
India's own official nutrition dataset is itself a credibility signal. USDA
values for "lentils" describe a different cultivar grown in different soil.

Provenance
----------
The published artefact is a PDF (nin.res.in/ebooks/IFCT2017.pdf). The
machine-readable form used here is `@ifct2017/compositions` on npm (MIT), which
transcribes the same 528 key foods. The generated CSV records the package
version and the tarball's SHA-256, so any number in this system can be traced
back to a specific published transcription -- and from there to ICMR-NIN's own
tables.

**Attribution obligation.** The npm package is MIT-licensed, but the underlying
data is ICMR-NIN's publication. Any pitch deck, report or UI that surfaces these
numbers must credit "Indian Food Composition Tables 2017, ICMR-National
Institute of Nutrition". That is both correct practice and, in front of a
government reviewer, the point.

Units, kept as published
------------------------
Energy is stored in **kilojoules**, as IFCT publishes it. Conversion to
kilocalories happens in `app/nutrition/ifct.py` and is unit-tested, rather than
being silently baked into the vendored file -- same discipline as the WHO
tables.

The `_e` columns are IFCT's own national variability: each food was composited
from six regions, and `_e` is the spread across them. We keep them because they
let the pipeline report a range instead of false precision (Section 15).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import tarfile
from datetime import date
from pathlib import Path

import httpx

REGISTRY = "https://registry.npmjs.org/@ifct2017/compositions"
OUT = Path(__file__).resolve().parent.parent / "app" / "nutrition" / "ifct" / "ifct2017.csv"

#: Source column -> output column. Restricted to what the pipeline actually
#: uses; IFCT's full 423 columns (amino acid profiles, phytosterols, ...) are
#: real data but nothing here consumes them, and vendoring unused columns just
#: makes the file harder to review.
KEEP = {
    "code": "code",
    "name": "name",
    "scie": "scientific_name",
    "lang": "local_names",
    "grup": "food_group",
    "tags": "tags",
    "enerc": "energy_kj",
    "enerc_e": "energy_kj_e",
    "protcnt": "protein_g",
    "protcnt_e": "protein_g_e",
    "choavldf": "carbohydrate_g",
    "choavldf_e": "carbohydrate_g_e",
    "fatce": "fat_g",
    "fatce_e": "fat_g_e",
    "fibtg": "fibre_g",
    "water": "water_g",
}


def hindi_name(local_names: str) -> str:
    """Pull the Hindi name out of IFCT's multilingual `lang` field.

    Format is `A. Moricha guti; H. Ramdana; Kan. Danthu beeja; ...` -- a
    semicolon-separated list of `<language abbreviation>. <name>`. 300 of 542
    foods carry an `H.` entry. These feed both the bilingual UI and the fuzzy
    matcher, since a vision model shown an Indian plate may well answer "dal" or
    "chawal" rather than "Bengal gram, dal".
    """
    match = re.search(r"(?:^|;\s*)H\.\s*([^;]+)", local_names)
    return match.group(1).strip() if match else ""


def main() -> None:
    meta = httpx.get(REGISTRY, timeout=60).json()
    version = meta["dist-tags"]["latest"]
    tarball = meta["versions"][version]["dist"]["tarball"]
    licence = meta["versions"][version].get("license", "unknown")

    blob = httpx.get(tarball, timeout=120, follow_redirects=True).content
    digest = hashlib.sha256(blob).hexdigest()

    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        member = tar.extractfile("package/index.csv")
        assert member is not None
        rows = list(csv.DictReader(io.TextIOWrapper(member, encoding="utf-8")))

    # Source headers look like "Food Code; code" -- key them by the short suffix.
    columns = {c.split("; ")[-1]: c for c in rows[0]}
    missing = [k for k in KEEP if k not in columns]
    if missing:
        raise SystemExit(f"upstream schema changed; missing columns: {missing}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        fh.write("# Indian Food Composition Tables 2017 (ICMR-National Institute of Nutrition).\n")
        fh.write("# Vendored for PoshanNetra AI (master prompt, Section 4).\n")
        fh.write(f"# source_package: @ifct2017/compositions@{version} (npm, {licence})\n")
        fh.write(f"# source_tarball: {tarball}\n")
        fh.write(f"# sha256(tarball): {digest}\n")
        fh.write(f"# retrieved: {date.today().isoformat()}\n")
        fh.write("# upstream_publication: https://www.nin.res.in/ebooks/IFCT2017.pdf\n")
        fh.write("# ATTRIBUTION REQUIRED: any surface that shows these numbers must credit\n")
        fh.write(
            "#   'Indian Food Composition Tables 2017, ICMR-National Institute of Nutrition'.\n"
        )
        fh.write("# Energy is in KILOJOULES, as IFCT publishes it. kcal conversion happens in\n")
        fh.write("#   app/nutrition/ifct.py and is unit-tested. Edible oils and fats are\n")
        fh.write("#   published with energy_kj = 0; energy for those is derived from macros.\n")
        fh.write("# *_e columns are IFCT's own national variability across six sampled regions.\n")
        fh.write("# Values are per 100 g of RAW edible portion -- not cooked. See\n")
        fh.write("#   app/nutrition/recipes.py for how cooked dishes are converted.\n")

        writer = csv.writer(fh)
        writer.writerow([*KEEP.values(), "hindi_name"])
        for row in rows:
            out = [row[columns[src]] for src in KEEP]
            writer.writerow([*out, hindi_name(row[columns["lang"]])])

    print(f"  {len(rows)} foods -> {OUT}")
    print(f"  package @ifct2017/compositions@{version} ({licence})")
    print(f"  sha256 {digest[:32]}...")
    zero = sum(1 for r in rows if float(r[columns["enerc"]] or 0) == 0)
    print(f"  {zero} foods publish energy_kj = 0 (edible oils/fats) -> derived at runtime")
    hi = sum(1 for r in rows if hindi_name(r[columns["lang"]]))
    print(f"  {hi} foods carry a Hindi local name")


if __name__ == "__main__":
    main()
