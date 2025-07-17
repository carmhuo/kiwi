from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from kiwi.api.deps import SessionDep
from kiwi.schemas import UserResponse
from kiwi.crud.user import UserCRUD

router = APIRouter(tags=["private"], prefix="/private")


class PrivateUserCreate(BaseModel):
    username: str
    email: str
    password: str
    is_verified: bool = False


@router.post("/users/", response_model=UserResponse)
async def create_user( session: SessionDep, user_in: PrivateUserCreate) -> Any:
    """
    Create a new user.
    """

    user = await UserCRUD().create_user(session, user_in.model_dump())

    return user

@router.post("/users-with-role/{role_code}", response_model=UserResponse)
async def create_user_with_role(session: SessionDep, user_in: PrivateUserCreate, role_code: int) -> Any:
    """
    Create a new user with role.
    """

    user = await UserCRUD().create_with_role(session, user_in.model_dump(), role_code)

    return user
