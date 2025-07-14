import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status, Depends

from kiwi.api.schemas import (
    UserCreate,
    UserResponse,
    Message,
    UsersResponse,
    UserUpdate,
    UserUpdateMe,
    UpdatePassword,
    UserRegister)
from kiwi.core.security import verify_password, get_password_hash
from kiwi.crud.user import UserCRUD
from kiwi.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)

router = APIRouter(
    prefix="/users",
    tags=["users"]
)


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UsersResponse,
)
async def read_users(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    """
    Retrieve users.
    """
    count = await UserCRUD().count(session)
    users = await UserCRUD().get_multi(session, skip, limit)
    return UsersResponse(data=users, count=count)


@router.post("/", dependencies=[Depends(get_current_active_superuser)], response_model=UserResponse)
async def create_user(
        user: UserCreate,
        db: SessionDep
):
    crud = UserCRUD()
    existing_user = await crud.get_by_username(db, user.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    return await crud.create_user(db, user.model_dump())


@router.patch("/me", response_model=UserResponse)
async def update_user_me(
        *, session: SessionDep, user_in: UserUpdateMe, current_user: CurrentUser
) -> Any:
    """
    Update own user.
    """

    if user_in.username:
        existing_user = await UserCRUD().get_by_username(session, str(user_in.username))
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    user_data = user_in.model_dump(exclude_unset=True)
    user_data["updated_at"] = datetime.now()
    return await UserCRUD().update(session, db_obj=current_user, obj_in=user_data)


@router.patch("/me/password", response_model=Message)
async def update_password_me(
        *, session: SessionDep, body: UpdatePassword, current_user: CurrentUser
) -> Any:
    """
    Update own password.
    """
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect password")
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=400, detail="New password cannot be the same as the current one"
        )
    hashed_password = get_password_hash(body.new_password)
    current_user.hashed_password = hashed_password
    session.add(current_user)
    session.commit()
    return Message(message="Password updated successfully")


@router.get("/me", response_model=UserResponse)
async def read_user_me(current_user: CurrentUser) -> Any:
    """
    Get current user.
    """
    return current_user


@router.post("/signup", response_model=UserResponse)
async def register_user(session: SessionDep, user_in: UserRegister) -> Any:
    """
    Create new user without the need to be logged in.
    """
    user = await UserCRUD().get_by_username(session, str(user_in.username))
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this name already exists in the system",
        )
    user = await UserCRUD().get_user_by_email(session, str(user_in.email))
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system",
        )
    user_create = UserCreate.model_validate(user_in)
    user = await UserCRUD().create_user(session, user_create.model_dump())
    return user


@router.get("/{user_id}", response_model=UserResponse)
async def read_user_by_id(
        user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """
    Get a specific user by id.
    """
    user = await UserCRUD().get_user_by_id(session, str(user_id))
    if user == current_user:
        return user
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges",
        )
    return user


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserResponse,
)
async def update_user(
        *,
        session: SessionDep,
        user_id: uuid.UUID,
        user_in: UserUpdate,
) -> Any:
    """
    Update a user.
    """

    db_user = await UserCRUD().get_user_by_id(session, str(user_id))
    if not db_user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )
    if user_in.email:
        existing_user = await UserCRUD().get_user_by_email(session, str(user_in.email))
        if existing_user and existing_user.id != user_id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )

    db_user = await UserCRUD().update(session, db_user, user_in.model_dump(exclude_unset=True))
    return db_user


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
async def delete_user(
        session: SessionDep, current_user: CurrentUser, user_id: uuid.UUID
) -> Message:
    """
    Delete a user.
    """
    db_user = await UserCRUD().get_user_by_id(session, str(user_id))
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    if db_user == current_user:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    await UserCRUD().delete_user(session, str(user_id))
    return Message(message="User deleted successfully")
