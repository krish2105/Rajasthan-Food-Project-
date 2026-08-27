"""IFCT 2017 vendoring, units, and the free-text matching trap.

Section 4 picks IFCT as the authoritative source. This file pins the two things
most likely to be quietly wrong about using it: the unit conversion, and the
belief that you can look a food up by name.
"""

from __future__ import annotations

import pytest

from app.nutrition import ifct


def test_table_loads_with_the_expected_size() -> None:
    foods = ifct.load_foods()
    assert len(foods) == 542
    assert all(f.code and f.name for f in foods.values())


def test_provenance_header_is_present_and_specific() -> None:
    """A vendored dataset without traceable provenance is an assertion, not a
    source. A reviewer must be able to get from any number here to ICMR-NIN."""
    header = "".join(
        line
        for line in ifct.IFCT_PATH.read_text(encoding="utf-8").splitlines(True)
        if line.startswith("#")
    )
    assert "ICMR-National Institute of Nutrition" in header
    assert "sha256(tarball)" in header
    assert "nin.res.in" in header
    assert "ATTRIBUTION REQUIRED" in header
    assert "KILOJOULES" in header, "the unit must be stated in the file itself"
    assert "RAW" in header, "raw-vs-cooked is the single most misusable fact here"


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------


def test_energy_converts_from_kilojoules_to_kilocalories() -> None:
    """IFCT publishes kJ. Rice at 356 kcal/100 g is the published value; getting
    this wrong by a factor of 4.184 would be a spectacular and silent error."""
    rice = ifct.get("A015")
    assert rice.name == "Rice, raw, milled"
    assert rice.energy_kj.value == pytest.approx(1491.0, abs=1.0)
    assert rice.energy_kcal == pytest.approx(356.4, abs=0.5)


def test_conversion_constant_is_the_thermochemical_one() -> None:
    assert ifct.KJ_PER_KCAL == 4.184


def test_energy_is_derived_for_oils_which_ifct_publishes_as_zero() -> None:
    """The 14 edible oils carry energy_kj = 0 in IFCT -- a gap in the source,
    not a real zero. Left uncorrected, every dish cooked in oil would lose ~9
    kcal per gram of it."""
    oil = ifct.get("T011")
    assert oil.name == "Soyabean oil"
    assert oil.energy_derived is True
    assert oil.fat_g.value == pytest.approx(100.0, abs=0.5)
    assert oil.energy_kcal == pytest.approx(900.0, abs=1.0)


def test_derived_energy_is_flagged_and_real_energy_is_not() -> None:
    assert ifct.get("T011").energy_derived is True
    assert ifct.get("A015").energy_derived is False


def test_only_oils_and_fats_need_derived_energy() -> None:
    derived = [f for f in ifct.load_foods().values() if f.energy_derived]
    assert len(derived) == 14
    assert {f.food_group for f in derived} == {"Edible Oils and Fats"}


def test_scaling_is_linear_and_carries_the_error() -> None:
    rice = ifct.get("A015")
    value, error = rice.protein_g.scaled(50.0)
    assert value == pytest.approx(rice.protein_g.value / 2, abs=1e-9)
    assert error == pytest.approx(rice.protein_g.error / 2, abs=1e-9)


def test_national_variability_is_preserved() -> None:
    """IFCT composited each food from six regions; `_e` is that spread. Keeping
    it is what lets the pipeline report a range instead of false precision."""
    bajra = ifct.get("A003")
    assert bajra.protein_g.error > 0
    assert bajra.energy_kj.error > 0


# --------------------------------------------------------------------------
# Lookup
# --------------------------------------------------------------------------


def test_exact_code_lookup_is_the_supported_path() -> None:
    assert ifct.get("a015").code == "A015"  # case-insensitive
    with pytest.raises(ifct.FoodNotFound):
        ifct.get("ZZZ999")


def test_hindi_names_are_extracted_from_the_multilingual_field() -> None:
    assert ifct.get("A003").hindi_name == "Bajra"
    hindi = sum(1 for f in ifct.load_foods().values() if f.hindi_name)
    assert hindi > 250, "the bilingual UI and the matcher both depend on these"


def test_display_name_falls_back_to_english_when_no_hindi_exists() -> None:
    no_hindi = next(f for f in ifct.load_foods().values() if not f.hindi_name)
    assert no_hindi.display_name("hi") == no_hindi.name


def test_search_returns_candidates_not_an_answer() -> None:
    """The API shape is the safety property. `search` cannot be mistaken for a
    lookup because it never returns a single food."""
    results = ifct.search("masoor dal")
    assert isinstance(results, list)
    assert results[0].food.name == "Lentil dal"


@pytest.mark.parametrize(
    ("query", "wrong_match"),
    [("dal", "Ragi"), ("kela", "Plantain, green"), ("aalu", "Yam, ordinary")],
)
def test_free_text_matching_is_genuinely_unsafe(query: str, wrong_match: str) -> None:
    """The finding that forced the closed-vocabulary design.

    These are not scorer artefacts. IFCT lists "Kela" as a local name for
    plantain and "Alu" for yam, so a top-1 free-text match returns a confident,
    completely wrong food. This test exists so that anyone tempted to add a
    convenient `ifct.find()` back sees exactly why it was removed.
    """
    top = ifct.search(query, limit=1)[0]
    assert top.food.name == wrong_match
    assert top.score >= 85, "and it scores highly, which is what makes it dangerous"


def test_nonsense_queries_are_refused_rather_than_best_guessed() -> None:
    with pytest.raises(ifct.FoodNotFound):
        ifct.search("spaceship")
    assert ifct.search_or_empty("spaceship") == []


def test_empty_query_is_rejected() -> None:
    with pytest.raises(ifct.FoodNotFound):
        ifct.search("   ")


def test_every_food_has_complete_macros() -> None:
    """A missing macro would silently contribute zero to a plate total."""
    for food in ifct.load_foods().values():
        assert food.protein_g.value >= 0
        assert food.carbohydrate_g.value >= 0
        assert food.fat_g.value >= 0
        assert food.energy_kcal > 0, f"{food.code} has no energy even after derivation"
