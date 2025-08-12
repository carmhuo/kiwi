from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.crud.project import ProjectCRUD
from kiwi.models import Project
from kiwi.schemas import ProjectCreate
from kiwi.tests.utils.user import create_random_user
from kiwi.tests.utils.utils import random_lower_string


def create_random_project(db: AsyncSession) -> Project:
    user = create_random_user(db)
    owner_id = user.id
    assert owner_id is not None
    title = random_lower_string()
    description = random_lower_string()
    item_in = ProjectCreate(title=title, description=description)
    return ProjectCRUD.create_project(session=db, item_in=item_in, owner_id=owner_id)
