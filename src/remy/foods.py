"""Food composition table and food search.

The table is ANSES's Ciqual 2020 (Licence Ouverte / Etalab 2.0), embedded as a compact CSV with the energy and six
nutrients per 100 g (``src/remy/data/ciqual_2020.csv``, rebuilt by ``scripts/build_ciqual.py``).

Search is deliberately simple and deterministic: clients (often an LLM) send short generic descriptions such as
"riz blanc cuit" or "oeuf dur" and pick among the candidates returned. Matching ignores case, accents and simple
plurals, drops stopwords, and ranks first the foods whose name *starts* with the main word, because Ciqual names put
the food first and its preparation after ("Riz blanc, cuit, non salé"). A food whose name joins its first word to
another one the query does not use ("Pomme de terre", "Fromage de tête") ranks below the plain food ("Pomme Golden"),
and a few everyday phrases are rewritten to Ciqual's wording ("jambon blanc").
"""

import csv
import functools
import re
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Lang = Literal["fr", "en"]
LANGS: tuple[Lang, ...] = ("fr", "en")
NUTRIENTS = ("kcal", "protein_g", "carbs_g", "fat_g", "sugars_g", "fiber_g", "salt_g")
CIQUAL_CSV = Path(__file__).resolve().parent / "data" / "ciqual_2020.csv"

STOPWORDS: dict[Lang, frozenset[str]] = {
    "fr": frozenset("au aux a la le les de des du et en avec sans d l un une ou sur pour type".split()),
    "en": frozenset("a an the of and with without in on or for to type".split()),
}


# Everyday phrases that Ciqual names differently. Applied to the normalized query, in French only.
QUERY_ALIASES: dict[str, str] = {
    "jambon blanc": "jambon cuit superieur",
    "fromage rape": "emmental rape",
}
AVERAGE_FOOD = "aliment moyen"
LINKERS: dict[Lang, frozenset[str]] = {"fr": frozenset({"de", "du", "des", "d", "au", "aux"}), "en": frozenset({"of"})}


class Nutrients(BaseModel):
    """Energy and nutrients, either per 100 g (a food) or for an amount eaten (an item, a meal, a day).

    ``None`` means unknown (Ciqual has no value), which is different from zero.
    """

    model_config = ConfigDict(frozen=True)

    kcal: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    sugars_g: float | None = None
    fiber_g: float | None = None
    salt_g: float | None = None

    def scaled(self, grams: float) -> "Nutrients":
        """Values for ``grams`` of a food whose values are per 100 g, rounded to 0.1."""
        return Nutrients(**{k: None if v is None else round(v * grams / 100, 1) for k, v in self.values().items()})

    def values(self) -> dict[str, float | None]:
        return {k: getattr(self, k) for k in NUTRIENTS}

    @classmethod
    def total(cls, parts: "list[Nutrients]") -> "Nutrients":
        """Sum, counting unknown values as zero; energy rounded to the kcal, the rest to 0.1 g."""
        sums = {k: round(sum(getattr(p, k) or 0 for p in parts), 1) for k in NUTRIENTS}
        sums["kcal"] = round(sums["kcal"])
        return cls(**sums)


class Food(BaseModel):
    """A food of the composition table, with its values per 100 g."""

    model_config = ConfigDict(frozen=True)

    code: str
    name_fr: str
    name_en: str | None = None
    brand: str | None = None
    source: str = "ciqual"
    per_100g: Nutrients
    portion_g: float | None = Field(default=None, description="Weight of one portion, for foods eaten by portion.")
    attribution: str | None = Field(default=None, description="Credit required by the source's licence, if any.")

    def name(self, lang: Lang = "fr") -> str:
        """Name in ``lang``; English falls back to French where the table has no English name."""
        return (self.name_en or self.name_fr) if lang == "en" else self.name_fr


def normalize(text: str) -> str:
    """Lower case, no accents, "œ" -> "oe", punctuation as spaces: "Bœuf, haché 5%" -> "boeuf hache 5"."""
    text = (text or "").lower().replace("œ", "oe").replace("æ", "ae")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def tokens(text: str, lang: Lang = "fr") -> list[str]:
    """Meaningful words: normalized, without stopwords or one-letter words (elided "d'", "l'")."""
    stop = STOPWORDS[lang]
    return [t for t in normalize(text).split() if t not in stop and len(t) > 1]


def _expand(query: str, lang: Lang) -> str:
    """The query with its everyday phrases replaced by Ciqual's wording (see ``QUERY_ALIASES``)."""
    text = normalize(query)
    if lang == "fr":
        for phrase, wording in QUERY_ALIASES.items():
            text = re.sub(rf"\b{phrase}\b", wording, text)
    return text


def _singular(t: str) -> str:
    """Crude singular for French and English plurals ("pâtes", "noix", "eggs"); short words are left alone."""
    return t[:-1] if len(t) > 3 and t[-1] in "sx" else t


def _score(word: str, name_tokens: list[str]) -> float:
    """How well one query word matches a food name.

    1 = the same word, 0.8 = singular/plural of it, 0.5 = one is the start of the other, from 4 letters on
    ("emmen" -> "emmental"), 0 otherwise.
    """
    best = 0.0
    for t in name_tokens:
        if t == word:
            return 1.0
        if _singular(t) == _singular(word):
            best = max(best, 0.8)
        elif len(word) >= 4 and len(t) >= 4 and (t.startswith(word) or word.startswith(t)):
            best = max(best, 0.5)
    return best


class FoodTable:
    """An in-memory food table with a token index per language."""

    def __init__(self, foods: list[Food]) -> None:
        self._foods = {f.code: f for f in foods}
        # Words of the head of each name (up to the first comma), and the "average food" entries.
        self._heads: dict[Lang, dict[str, list[str]]] = {
            lang: {f.code: normalize(f.name(lang).split(",")[0]).split() for f in foods} for lang in LANGS
        }
        self._average = {f.code for f in foods if AVERAGE_FOOD in normalize(f.name_fr)}
        self._tokens: dict[Lang, dict[str, list[str]]] = {
            lang: {f.code: tokens(f.name(lang) + " " + (f.brand or ""), lang) for f in foods} for lang in LANGS
        }

    @classmethod
    def from_csv(cls, path: Path) -> "FoodTable":
        with path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        foods = [
            Food(
                code=row["code"],
                name_fr=row["name_fr"],
                name_en=row.get("name_en") or None,
                per_100g=Nutrients(**{k: float(row[k]) if row[k] else None for k in NUTRIENTS}),
            )
            for row in rows
        ]
        return cls(foods)

    def __len__(self) -> int:
        return len(self._foods)

    def get(self, code: str | None) -> Food | None:
        """The food with this code, or None."""
        return self._foods.get(str(code or "").strip())

    def search(self, query: str, lang: Lang = "fr", limit: int = 5) -> list[Food]:
        """Foods closest to a short description, best first.

        Sorted by: name starts with the first query word, then average word score, then not being a compound
        ("Pomme de terre" for "pomme"), then how well the first word matches, then shorter names (the generic food
        before its variants), then "average food" entries, then table order.
        """
        return [food for _, food in self.search_scored(query, lang, limit)]

    def _is_compound(self, code: str, lang: Lang, words: list[str]) -> bool:
        """Whether the name's head joins its first word to another one the query does not use: "Pomme de terre",
        "Fromage de tête". Such a food is a different food from the first word alone."""
        head = self._heads[lang][code]
        for i, word in enumerate(head[:-1]):
            if word in LINKERS[lang] and _score(head[i + 1], words) < 0.8 and i > 0:
                return True
        return False

    def search_scored(self, query: str, lang: Lang = "fr", limit: int = 5) -> list[tuple[tuple, Food]]:
        """Like :meth:`search`, with each food's sort key (comparable across tables, higher is better)."""
        words = tokens(_expand(query, lang), lang)
        if not words or limit <= 0:
            return []
        scored = []
        for code, name_tokens in self._tokens[lang].items():
            score = sum(_score(w, name_tokens) for w in words)
            if not score:
                continue
            first = _score(words[0], name_tokens[:1])
            key = (
                first > 0,
                round(score / len(words), 3),
                not self._is_compound(code, lang, words),
                first,
                -len(name_tokens),
                code in self._average,
            )
            scored.append((key, code))
        scored.sort(key=lambda s: s[0], reverse=True)  # stable: ties keep table order
        return [(key, self._foods[code]) for key, code in scored[:limit]]


@functools.cache
def ciqual() -> FoodTable:
    """The embedded Ciqual 2020 table, loaded on first use."""
    return FoodTable.from_csv(CIQUAL_CSV)


def search(query: str, lang: Lang = "fr", limit: int = 5) -> list[Food]:
    """Search the Ciqual table (see :meth:`FoodTable.search`)."""
    return ciqual().search(query, lang, limit)


def get_food(code: str | None) -> Food | None:
    """The Ciqual food with this code, or None."""
    return ciqual().get(code)
