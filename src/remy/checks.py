"""What looks wrong in a meal log: log issues (the log itself is probably wrong) and anomalies (the day's eating is).

The code detects, the client phrases: every finding has a stable ``code``, the slot and meals involved and the
numbers, plus ready-made French and English messages for clients that just want to show it.

Log issues (is the log right?):

- ``duplicate_meal``: the same dish logged twice within ``DUPLICATE_HOURS`` (3 h), unless the second is an explicit
  repeat. Chat clients re-send messages and LLMs re-log a dish they were only asked about.
- ``two_full_meals``: two meals of at least ``FULL_MEAL_KCAL`` (400 kcal) in the same main slot: eaten twice, or the
  same meal logged under two descriptions.
- ``no_trace``: a main meal whose slot is over and that has no entry, not even "skipped".

Anomalies (is the day's eating right?), only for days with at least one entry (no data, no judgement):

- ``missing_meal`` / ``skipped_meal`` / ``light_meal`` (< 250 kcal) for each main meal;
- ``low_intake`` (< 75 % of needs) / ``high_intake`` (> 140 %), once at least two meals are logged;
- ``low_protein`` (< 1.2 g/kg, the bottom of the endurance range);
- ``low_carbs_workout_day`` (< 4 g/kg on a day with a workout, well under the 5–7 g/kg training range).
"""

import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from remy.energy import Profile, Workout, day_workouts, needs
from remy.foods import Lang, Nutrients
from remy.slots import LABELS, MAIN_MEALS, Slot, slot_of, slot_over

DUPLICATE_HOURS = 3
FULL_MEAL_KCAL = 400
LIGHT_MAIN_MEAL_KCAL = 250
LOW_INTAKE = 0.75
HIGH_INTAKE = 1.40
LOW_PROTEIN_G_PER_KG = 1.2
LOW_CARBS_G_PER_KG_WORKOUT_DAY = 4.0
MIN_MEALS_TO_JUDGE_INTAKE = 2
"""With fewer meals logged, a low total says more about the log than about the eating."""

_DISH_STOP = frozenset(
    "avec pour dans des les une aux sur sans plus boîte boîtes portion portions box boxes with and the".split()
)


class Meal(BaseModel):
    """A logged meal, in the user's local time. ``skipped`` marks an explicit "I skipped breakfast" entry."""

    model_config = ConfigDict(frozen=True)

    id: int | str
    date: datetime.date
    time: datetime.time
    slot: Slot | None = None
    text: str
    nutrients: Nutrients = Field(default_factory=Nutrients)
    repeat: bool = False
    skipped: bool = False

    @property
    def meal_slot(self) -> Slot:
        """The stored slot, else the one of its time."""
        return self.slot or slot_of(self.time)

    @property
    def at(self) -> datetime.datetime:
        return datetime.datetime.combine(self.date, self.time)

    @property
    def kcal(self) -> float:
        return self.nutrients.kcal or 0


def dish_words(text: str) -> set[str]:
    """Words that identify a dish: three letters or more, minus fillers and container words ("boîte", "portion")."""
    return {w for w in re.findall(r"[a-zà-ÿœæ]+", (text or "").casefold()) if len(w) >= 3 and w not in _DISH_STOP}


def same_dish(a: str, b: str) -> bool:
    """Same dish, give or take the wording: "Curry de poulet" ≈ "Curry de poulet + riz (1 boîte)".

    At least 75 % of the shorter description's words appear in the longer one.
    """
    wa, wb = dish_words(a), dish_words(b)
    if not wa or not wb:
        return " ".join(a.casefold().split()) == " ".join(b.casefold().split())
    small, big = sorted((wa, wb), key=len)
    return len(small & big) / len(small) >= 0.75


def find_duplicate(meals: list[Meal], text: str, at: datetime.datetime) -> Meal | None:
    """The latest meal with the same dish within ``DUPLICATE_HOURS`` of ``at`` (local, naive), or None.

    Used when logging: Remy stores the meal anyway and returns this as a hint; the client decides.
    """
    window = datetime.timedelta(hours=DUPLICATE_HOURS)
    for m in sorted(meals, key=lambda m: m.at, reverse=True):
        if not m.skipped and abs(m.at - at) <= window and same_dish(m.text, text):
            return m
    return None


FindingCode = Literal[
    "duplicate_meal",
    "two_full_meals",
    "no_trace",
    "missing_meal",
    "skipped_meal",
    "light_meal",
    "low_intake",
    "high_intake",
    "low_protein",
    "low_carbs_workout_day",
]


class Finding(BaseModel):
    """One thing that looks wrong. ``values`` carries the numbers behind it (kcal, g/kg, times…)."""

    model_config = ConfigDict(frozen=True)

    code: FindingCode
    date: datetime.date
    slot: Slot | None = None
    meal_ids: list[int | str] = Field(default_factory=list)
    values: dict[str, float | int | str] = Field(default_factory=dict)

    def message(self, lang: Lang = "fr") -> str:
        return _message(self, lang)


def _of_day(meals: list[Meal], day: datetime.date) -> list[Meal]:
    return sorted((m for m in meals if m.date == day), key=lambda m: m.time)


def eaten(meals: list[Meal]) -> list[Meal]:
    """Meals actually eaten (not "skipped" entries)."""
    return [m for m in meals if not m.skipped]


def log_issues(meals: list[Meal], day: datetime.date, now: datetime.datetime | None = None) -> list[Finding]:
    """Inconsistencies in the log of ``day``. ``now`` (user's local time) decides which slots are over; ``None``
    means the day is over."""
    of_day = _of_day(meals, day)
    out: list[Finding] = []
    flagged: set[int | str] = set()
    window = datetime.timedelta(hours=DUPLICATE_HOURS)
    for i, a in enumerate(of_day):
        for b in of_day[i + 1 :]:
            if b.repeat or a.skipped or b.skipped or not same_dish(a.text, b.text):
                continue
            if b.at - a.at <= window:
                out.append(
                    Finding(
                        code="duplicate_meal",
                        date=day,
                        slot=b.meal_slot,
                        meal_ids=[a.id, b.id],
                        values={"text": b.text, "first_time": f"{a.time:%H:%M}", "second_time": f"{b.time:%H:%M}"},
                    )
                )
                flagged |= {a.id, b.id}
    for slot in MAIN_MEALS:
        mine = [m for m in of_day if m.meal_slot == slot]
        full = [m for m in eaten(mine) if m.kcal >= FULL_MEAL_KCAL and not m.repeat]
        if len(full) >= 2 and not {m.id for m in full} <= flagged:
            out.append(
                Finding(
                    code="two_full_meals",
                    date=day,
                    slot=slot,
                    meal_ids=[m.id for m in full],
                    values={"count": len(full), "kcal": round(sum(m.kcal for m in full))},
                )
            )
        if not mine and slot_over(slot, day, now):
            out.append(Finding(code="no_trace", date=day, slot=slot))
    return out


def totals(meals: list[Meal]) -> Nutrients:
    return Nutrients.total([m.nutrients for m in eaten(meals)])


def anomalies(meals: list[Meal], workouts: list[Workout], profile: Profile, day: datetime.date) -> list[Finding]:
    """What is off in the day's eating. Nothing for a day with no entry at all."""
    of_day = _of_day(meals, day)
    if not of_day:
        return []
    out: list[Finding] = []
    for slot in MAIN_MEALS:
        mine = [m for m in of_day if m.meal_slot == slot]
        kcal = sum(m.kcal for m in mine)
        if not mine:
            out.append(Finding(code="missing_meal", date=day, slot=slot))
        elif all(m.skipped for m in mine):
            out.append(Finding(code="skipped_meal", date=day, slot=slot, meal_ids=[m.id for m in mine]))
        elif kcal and kcal < LIGHT_MAIN_MEAL_KCAL:  # 0 = unknown energy, not a light meal
            out.append(
                Finding(
                    code="light_meal", date=day, slot=slot, meal_ids=[m.id for m in mine], values={"kcal": round(kcal)}
                )
            )
    count = len(eaten(of_day))
    if count < MIN_MEALS_TO_JUDGE_INTAKE:
        return out
    t = totals(of_day)
    intake = t.kcal or 0
    need = needs(profile, workouts, day)
    if need:
        ratio = intake / need.total_kcal
        values = {"intake_kcal": round(intake), "needs_kcal": round(need.total_kcal), "ratio": round(ratio, 2)}
        if ratio < LOW_INTAKE:
            out.append(Finding(code="low_intake", date=day, values=values))
        elif ratio > HIGH_INTAKE:
            out.append(Finding(code="high_intake", date=day, values=values))
    if profile.weight_kg:
        w = profile.weight_kg
        protein, carbs = t.protein_g or 0, t.carbs_g or 0
        if protein / w < LOW_PROTEIN_G_PER_KG:
            out.append(
                Finding(
                    code="low_protein", date=day, values={"grams": round(protein), "g_per_kg": round(protein / w, 1)}
                )
            )
        if day_workouts(workouts, day) and carbs / w < LOW_CARBS_G_PER_KG_WORKOUT_DAY:
            out.append(
                Finding(
                    code="low_carbs_workout_day",
                    date=day,
                    values={"grams": round(carbs), "g_per_kg": round(carbs / w, 1)},
                )
            )
    return out


# --- messages ---------------------------------------------------------------------------------------------------

_FR_ARTICLE = {Slot.BREAKFAST: "du", Slot.LUNCH: "du", Slot.SNACK: "de la", Slot.DINNER: "du"}


def _num(x: float | int | str, lang: Lang) -> str:
    if isinstance(x, str):
        return x
    text = f"{x:,.0f}" if float(x).is_integer() or abs(x) >= 100 else f"{x:.1f}"
    return text.replace(",", " ").replace(".", ",") if lang == "fr" else text


def _message(f: Finding, lang: Lang) -> str:
    v = {k: _num(x, lang) for k, x in f.values.items()}
    slot = LABELS[lang][f.slot] if f.slot else ""
    ids = " ".join(f"#{i}" for i in f.meal_ids)
    if lang == "fr":
        of_slot = f"{_FR_ARTICLE[f.slot]} {slot}" if f.slot else ""
        return {
            "duplicate_meal": f"{ids} : « {v.get('text')} » noté deux fois ({v.get('first_time')} et "
            f"{v.get('second_time')}), doublon probable",
            "two_full_meals": f"{v.get('count')} repas complets au {slot} ({ids}) : mangé deux fois, ou doublon ?",
            "no_trace": f"aucune trace {of_slot}",
            "missing_meal": f"aucune trace {of_slot}",
            "skipped_meal": f"{slot} sauté",
            "light_meal": f"{slot} très léger (~{v.get('kcal')} kcal)",
            "low_intake": f"apports bas : ~{v.get('intake_kcal')} kcal pour ~{v.get('needs_kcal')} kcal de besoins",
            "high_intake": f"apports inhabituellement hauts : ~{v.get('intake_kcal')} kcal pour "
            f"~{v.get('needs_kcal')} kcal de besoins",
            "low_protein": f"protéines basses : {v.get('grams')} g ({v.get('g_per_kg')} g/kg)",
            "low_carbs_workout_day": f"jour d'entraînement avec peu de glucides : {v.get('grams')} g "
            f"({v.get('g_per_kg')} g/kg)",
        }[f.code]
    return {
        "duplicate_meal": f"{ids}: “{v.get('text')}” logged twice ({v.get('first_time')} and "
        f"{v.get('second_time')}), probably a duplicate",
        "two_full_meals": f"{v.get('count')} full meals at {slot} ({ids}): eaten twice, or a duplicate?",
        "no_trace": f"no {slot} logged",
        "missing_meal": f"no {slot} logged",
        "skipped_meal": f"{slot} skipped",
        "light_meal": f"very light {slot} (~{v.get('kcal')} kcal)",
        "low_intake": f"low intake: ~{v.get('intake_kcal')} kcal for ~{v.get('needs_kcal')} kcal of needs",
        "high_intake": f"unusually high intake: ~{v.get('intake_kcal')} kcal for ~{v.get('needs_kcal')} kcal of needs",
        "low_protein": f"low protein: {v.get('grams')} g ({v.get('g_per_kg')} g/kg)",
        "low_carbs_workout_day": f"training day with few carbs: {v.get('grams')} g ({v.get('g_per_kg')} g/kg)",
    }[f.code]
