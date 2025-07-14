from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from kiwi.api.deps import SessionDep
from kiwi.api.schemas import UserResponse
from kiwi.crud.user import UserCRUD

router = APIRouter(tags=["private"], prefix="/private")


class PrivateUserCreate(BaseModel):
    username: str
    email: str
    password: str
    is_verified: bool = False


@router.post("/users/", response_model=UserResponse)
async def create_user(user_in: PrivateUserCreate, session: SessionDep) -> Any:
    """
    Create a new user.
    """

    user = await UserCRUD().create_user(session, user_in.model_dump())

    return user
