import pytest
from kiwi.crud.project import ProjectCRUD
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_create_project(db: AsyncSession):
    crud = ProjectCRUD()
    project_data = {"name": "Test Project", "description": "For testing"}
    project = await crud.create_with_owner(db, project_data, owner_id="test-user-id")
    assert project.name == "Test Project"
    assert project.owner_id == "test-user-id"

    members = await crud.get_project_members(db, project.id)
    assert len(members) == 1
    assert members[0].user_id == "test-user-id"