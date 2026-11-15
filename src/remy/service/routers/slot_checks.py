"""Slot checks: what a client already asked the user about, so it does not nag twice.

Remy only stores the status; when to ask ("what did you eat for lunch?") stays the client's decision. ``day`` is the
slot of the whole-day check (Bob's evening recap).
"""

from fastapi import APIRouter, Request

from remy.schemas import CheckSlot, SlotCheckIn, SlotCheckOut
from remy.service.db import SlotCheckRow, utcnow
from remy.service.deps import CurrentUser, Db, local_now, parse_day

router = APIRouter(prefix="/v1/me/slot-checks", tags=["slot checks"])


@router.get("/{date}/{slot}")
def get_slot_check(request: Request, db: Db, user: CurrentUser, date: str, slot: CheckSlot) -> SlotCheckOut:
    day = parse_day(date, local_now(request, user).date())
    row = db.get(SlotCheckRow, (user.id, day, slot))
    return SlotCheckOut(
        date=day, slot=slot, status=row.status if row else None, updated_at=row.updated_at if row else None
    )


@router.put("/{date}/{slot}")
def put_slot_check(
    request: Request, db: Db, user: CurrentUser, date: str, slot: CheckSlot, body: SlotCheckIn
) -> SlotCheckOut:
    """Record that the slot was ``asked`` about, ``answered``, ``skipped`` or ``checked``."""
    day = parse_day(date, local_now(request, user).date())
    row = db.get(SlotCheckRow, (user.id, day, slot))
    if row is None:
        row = SlotCheckRow(user_id=user.id, date=day, slot=slot)
        db.add(row)
    row.status, row.updated_at = body.status, utcnow()
    db.commit()
    return SlotCheckOut(date=day, slot=slot, status=row.status, updated_at=row.updated_at)
