"""Meal nutrient computation (ported from Bob's compute)."""

import pytest

from remy.foods import Nutrients
from remy.nutrients import MAX_GRAMS, compute


def test_compute_meal_from_ciqual():
    out = compute(
        [
            {"food_query": "pâtes cuites", "grams": 250},
            {"food_query": "thon au naturel", "grams": 100},
            {"food_query": "xyzzy", "grams": 20},
        ]
    )
    pasta, tuna = out.items
    assert pasta.food_name.startswith("Pâtes sèches") and pasta.nutrients.kcal == 315.0  # 126 kcal / 100 g
    assert pasta.label == "pâtes cuites" and pasta.index == 0
    assert tuna.nutrients.protein_g == 26.8
    assert out.totals.kcal == 426
    assert [(w.index, w.code, w.label) for w in out.warnings] == [(2, "no_match", "xyzzy")]


def test_code_wins_over_query():
    out = compute([{"food_query": "n'importe", "food_code": "9104", "grams": 100}])
    assert out.items[0].food_name == "Riz blanc, cuit, non salé" and out.warnings == []


def test_code_only_uses_food_name_as_label():
    out = compute([{"food_code": "9104", "grams": 200}])
    assert out.items[0].label == "Riz blanc, cuit, non salé"


def test_unknown_code_falls_back_to_query_with_warning():
    out = compute([{"food_code": "000", "food_query": "riz blanc cuit", "grams": 100}])
    assert out.items[0].food_code == "9104"
    assert [w.code for w in out.warnings] == ["unknown_food_code"]


def test_unknown_code_without_query():
    out = compute([{"food_code": "000", "grams": 100}])
    assert out.items == [] and [w.code for w in out.warnings] == ["unknown_food_code"]


def test_no_food_given():
    out = compute([{"grams": 100}, {"food_query": "  ", "grams": 10}])
    assert [w.code for w in out.warnings] == ["no_match", "no_match"]


@pytest.mark.parametrize(
    ("grams", "kept"),
    [(None, False), (0, False), (-5, False), (0.1, True), (MAX_GRAMS, True), (MAX_GRAMS + 0.1, False), (5000, False)],
)
def test_grams_bounds(grams, kept):
    out = compute([{"food_query": "pâtes cuites", "grams": grams}])
    assert bool(out.items) is kept
    assert [w.code for w in out.warnings] == ([] if kept else ["invalid_grams"])


def test_empty_meal():
    out = compute([])
    assert out.items == [] and out.warnings == [] and out.totals.kcal == 0


def test_unknown_values_stay_unknown_per_item_and_count_as_zero_in_totals():
    part = Nutrients(kcal=100, protein_g=None).scaled(50)
    assert part.kcal == 50 and part.protein_g is None
    total = Nutrients.total([part, Nutrients(kcal=10.4, protein_g=2.25)])
    assert total.kcal == 60 and total.protein_g == 2.2
