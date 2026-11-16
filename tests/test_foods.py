"""Ciqual table and search: the ranking cases Bob relies on, and tricky French spellings."""

import pytest

from remy import foods
from remy.foods import Food, FoodTable, Nutrients, normalize, tokens


def test_table_is_loaded():
    table = foods.ciqual()
    assert len(table) > 2000
    rice = table.get("9104")
    assert rice.name_fr == "Riz blanc, cuit, non salé" and rice.per_100g.kcal is not None
    assert table.get("nope") is None and table.get(None) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Bœuf, haché 5%", "boeuf hache 5"),
        ("ŒUF", "oeuf"),
        ("Pâtes", "pates"),
        ("crème brûlée", "creme brulee"),
        ("  l'huile d'olive ", "l huile d olive"),
        ("", ""),
    ],
)
def test_normalize(text, expected):
    assert normalize(text) == expected


def test_tokens_drop_stopwords_and_elisions():
    assert tokens("flocons d'avoine avec du lait") == ["flocons", "avoine", "lait"]
    assert tokens("the eggs with bacon", "en") == ["eggs", "bacon"]


@pytest.mark.parametrize(
    ("query", "code"),
    [
        # Bob's cases
        ("pâtes cuites", "9811"),  # Pâtes sèches standard, cuites, non salées
        ("riz blanc cuit", "9104"),  # Riz blanc, cuit, non salé
        ("thon au naturel", "26039"),  # Thon, au naturel, appertisé, égoutté
        # accents, case and the œ ligature
        ("oeuf dur", "22010"),  # Oeuf, dur
        ("œuf dur", "22010"),
        ("OEUF DUR", "22010"),
        ("bœuf haché", "6250"),  # Boeuf, steak haché 5% MG, cru
        # plurals
        ("œufs durs", "22010"),
        ("compote de pommes", "13038"),  # Compote de pomme
        ("bananes", "13005"),  # Banane, pulpe, crue
        # ambiguous queries (#29)
        ("pommes", "13086"),  # an apple, not "Pomme de terre"
        ("pomme", "13086"),
        ("fromage râpé", "12118"),  # Emmental râpé, not "Fromage de tête"
        ("jambon blanc", "28900"),  # Jambon cuit, supérieur
        ("yaourt nature", "19600"),  # the "aliment moyen" entry
        ("fromage", "12999"),  # Fromage (aliment moyen)
        ("pomme de terre", "4008"),  # a compound the query asks for stays reachable
        # word starts
        ("emmen", "12115"),  # Emmental ou emmenthal
        # elision
        ("huile d'olive", "17270"),  # Huile d'olive vierge extra
    ],
)
def test_search_ranking(query, code):
    assert foods.search(query, limit=1)[0].code == code


def test_search_lentils_start_with_the_main_word():
    assert foods.search("lentilles cuites", limit=1)[0].name_fr.startswith("Lentille")


@pytest.mark.parametrize("query", ["", "xyzzy", "de la", "   "])
def test_search_without_match(query):
    assert foods.search(query) == []


def test_search_limit():
    assert len(foods.search("pâtes", limit=3)) == 3
    assert foods.search("pâtes", limit=0) == []


def test_english_falls_back_to_french_names():
    rice = foods.get_food("9104")
    assert rice.name("en") == (rice.name_en or rice.name_fr)


def test_english_search_uses_english_names():
    table = FoodTable(
        [
            Food(code="1", name_fr="Oeuf, dur", name_en="Egg, hard-boiled", per_100g=Nutrients(kcal=134)),
            Food(code="2", name_fr="Riz blanc, cuit", name_en="Rice, white, cooked", per_100g=Nutrients(kcal=146)),
        ]
    )
    assert [f.code for f in table.search("boiled eggs", "en")] == ["1"]
    assert [f.code for f in table.search("cooked white rice", "en")] == ["2"]
    assert table.search("riz", "en") == []
    assert table.get("2").name("en") == "Rice, white, cooked"
