"""Import of data from other tools into the user's own account."""

from fastapi import APIRouter

from remy.schemas import BobImportReport, BobStateIn
from remy.service.deps import CurrentUser, Db
from remy.service.importing import import_bob

router = APIRouter(prefix="/v1/me/import", tags=["import"])


@router.post("/bob")
def post_bob(db: Db, user: CurrentUser, body: BobStateIn, dry_run: bool = False) -> BobImportReport:
    """Import the meal log, profile and meal checks of Bob's state file (send the file's JSON as the body).

    Safe to repeat: meals already imported are skipped, existing slot checks are kept and profile fields already
    set are not overwritten. ``dry_run=true`` reports what would happen without writing anything.
    """
    return import_bob(db, user, body.model_dump(), dry_run)
