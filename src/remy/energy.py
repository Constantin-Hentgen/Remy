"""Energy needs: basal metabolism × daily activity, plus the day's workouts; reference ranges for macros.

- **BMR** uses Mifflin–St Jeor (Mifflin et al., Am J Clin Nutr 1990), the most accurate of the classic predictive
  equations for non-obese adults: ``10 × kg + 6.25 × cm − 5 × age + 5`` (men) or ``− 161`` (women).
- **Daily life** multiplies the BMR by an activity factor, 1.4 by default: an office job with some walking,
  *excluding* training, which is counted separately so that rest days and long-run days differ.
- **Workouts** use the device's calories when the client has them. Otherwise running costs about 1 kcal per kg of
  body weight per km, nearly independent of pace (Margaria 1963; ACSM). A workout with only a duration adds nothing:
  without a device figure or a distance there is no sound way to compute it, and Remy does not guess.
- **Reference ranges** for endurance athletes (ACSM/AND/DC joint position, 2016): protein 1.4–1.8 g/kg/day (within
  the 1.2–2.0 statement range); carbohydrates 5–7 g/kg on moderate training days.
"""

import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

ACTIVITY_FACTOR = 1.4
KCAL_PER_KG_KM = 1.0
DEFAULT_WEIGHT_KG = 70.0
"""Weight used for distance-based workout calories when the profile has none."""

PROTEIN_G_PER_KG = (1.4, 1.8)
CARBS_G_PER_KG_TRAINING = (5.0, 7.0)

PROFILE_FIELDS = ("weight_kg", "height_cm", "birth_year", "sex")
"""The profile fields BMR needs."""


class Sex(StrEnum):
    """Sex as used by Mifflin–St Jeor (the equation only knows these two)."""

    MALE = "male"
    FEMALE = "female"


_SEX_ALIASES = {"m": Sex.MALE, "male": Sex.MALE, "man": Sex.MALE, "h": Sex.MALE, "homme": Sex.MALE,
                "f": Sex.FEMALE, "female": Sex.FEMALE, "woman": Sex.FEMALE, "femme": Sex.FEMALE}  # fmt: skip


class Profile(BaseModel):
    """What energy needs depend on. Every field is optional: an incomplete profile gives no needs, not a guess.

    The bounds reject typos and hallucinations (a 7 kg adult), as Bob's ``set_profile`` did.
    """

    weight_kg: float | None = Field(default=None, ge=30, le=250)
    height_cm: float | None = Field(default=None, ge=120, le=230)
    birth_year: int | None = Field(default=None, ge=1920)
    sex: Sex | None = None
    activity_factor: float | None = Field(
        default=None, ge=1.0, le=2.5, description=f"Daily-life multiplier of the BMR; default {ACTIVITY_FACTOR}."
    )

    @field_validator("sex", mode="before")
    @classmethod
    def _sex_aliases(cls, v: object) -> object:
        if isinstance(v, str) and v.strip():
            return _SEX_ALIASES.get(v.strip().lower(), v)
        return v or None

    @field_validator("birth_year")
    @classmethod
    def _adult_enough(cls, v: int | None) -> int | None:
        if v is not None and v > datetime.date.today().year - 10:
            raise ValueError("birth_year must be at least 10 years ago")
        return v

    def missing(self) -> list[str]:
        """The fields BMR still needs."""
        return [f for f in PROFILE_FIELDS if getattr(self, f) is None]


class Workout(BaseModel):
    """A training session pushed by a client (Remy talks to no tracker itself)."""

    model_config = ConfigDict(frozen=True)

    date: datetime.date
    kind: str = "run"
    kcal: float | None = Field(default=None, ge=0, le=10000, description="Device calories; preferred when given.")
    km: float | None = Field(default=None, ge=0, le=500)
    minutes: float | None = Field(default=None, ge=0, le=2000)


def bmr(profile: Profile, day: datetime.date) -> float | None:
    """Basal metabolic rate in kcal/day (Mifflin–St Jeor), or None if the profile is incomplete.

    Age is ``day.year − birth_year``: within a year of the truth, i.e. ±5 kcal.
    """
    if profile.missing():
        return None
    assert profile.weight_kg and profile.height_cm and profile.birth_year and profile.sex
    age = day.year - profile.birth_year
    base = 10 * profile.weight_kg + 6.25 * profile.height_cm - 5 * age
    return base + (5 if profile.sex == Sex.MALE else -161)


def workout_kcal(workout: Workout, weight_kg: float | None) -> float:
    """Energy of one workout: the device's figure, else 1 kcal/kg/km, else 0 (duration alone is not enough)."""
    if workout.kcal:
        return workout.kcal
    if workout.km:
        return workout.km * (weight_kg or DEFAULT_WEIGHT_KG) * KCAL_PER_KG_KM
    return 0.0


class Needs(BaseModel):
    """Energy needs of one day, in kcal."""

    model_config = ConfigDict(frozen=True)

    bmr: float
    activity_factor: float
    daily_life_kcal: float = Field(description="BMR × activity factor.")
    workouts_kcal: float
    total_kcal: float


def day_workouts(workouts: list[Workout], day: datetime.date) -> list[Workout]:
    return [w for w in workouts if w.date == day]


def workouts_kcal(profile: Profile, workouts: list[Workout], day: datetime.date) -> float:
    """Total energy of the day's workouts."""
    return round(sum(workout_kcal(w, profile.weight_kg) for w in day_workouts(workouts, day)), 1)


def needs(profile: Profile, workouts: list[Workout], day: datetime.date) -> Needs | None:
    """The day's energy needs, or None if the profile is incomplete."""
    base = bmr(profile, day)
    if base is None:
        return None
    factor = profile.activity_factor or ACTIVITY_FACTOR
    training = workouts_kcal(profile, workouts, day)
    daily = base * factor
    return Needs(
        bmr=round(base, 1),
        activity_factor=factor,
        daily_life_kcal=round(daily, 1),
        workouts_kcal=training,
        total_kcal=round(daily + training, 1),
    )
