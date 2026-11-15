"""Workouts pushed by clients. Remy talks to no tracker itself (Strava, Dreeve…): clients do."""

import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from remy.schemas import WorkoutIn, WorkoutOut
from remy.service.convert import workout_out
from remy.service.db import User, WorkoutRow
from remy.service.deps import CurrentUser, Db, local_now

router = APIRouter(prefix="/v1/me/workouts", tags=["workouts"])


def workouts_between(db: Db, user: User, start: datetime.date, end: datetime.date) -> list[WorkoutRow]:
    query = (
        select(WorkoutRow)
        .where(WorkoutRow.user_id == user.id, WorkoutRow.date >= start, WorkoutRow.date <= end)
        .order_by(WorkoutRow.date, WorkoutRow.id)
    )
    return list(db.scalars(query))


@router.post("", status_code=status.HTTP_201_CREATED)
def post_workout(response: Response, db: Db, user: CurrentUser, body: WorkoutIn) -> WorkoutOut:
    """Record a workout. With an ``external_id`` (e.g. the tracker's activity id), posting it again updates the
    stored workout instead of adding a second one, so a client can re-push its recent activities safely."""
    row = None
    if body.external_id:
        row = db.scalar(
            select(WorkoutRow).where(WorkoutRow.user_id == user.id, WorkoutRow.external_id == body.external_id)
        )
    if row is None:
        row = WorkoutRow(user_id=user.id, external_id=body.external_id)
        db.add(row)
    else:
        response.status_code = status.HTTP_200_OK
    row.date, row.kind, row.kcal, row.km, row.minutes = body.date, body.kind, body.kcal, body.km, body.minutes
    db.commit()
    return workout_out(row, user.weight_kg)


@router.get("")
def list_workouts(
    request: Request,
    db: Db,
    user: CurrentUser,
    start: Annotated[datetime.date | None, Query(alias="from", description="First day; default: today.")] = None,
    end: Annotated[datetime.date | None, Query(alias="to", description="Last day; default: same as from.")] = None,
) -> list[WorkoutOut]:
    start = start or local_now(request, user).date()
    end = end or start
    return [workout_out(w, user.weight_kg) for w in workouts_between(db, user, start, end)]


@router.delete("/{workout_id}")
def delete_workout(db: Db, user: CurrentUser, workout_id: int) -> WorkoutOut:
    row = db.get(WorkoutRow, workout_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no workout {workout_id}")
    removed = workout_out(row, user.weight_kg)
    db.delete(row)
    db.commit()
    return removed
