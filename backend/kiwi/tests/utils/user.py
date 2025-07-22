from fastapi.testclient import TestClient
from pydantic import EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.crud.user import UserCRUD
from kiwi.core.config import settings
from kiwi.schemas import UserCreate, UserUpdate
from kiwi.models import User
from kiwi.tests.utils.utils import random_email, random_lower_string


def user_authentication_headers(
        *, client: TestClient, username: str, email: str, password: str
) -> dict[str, str]:
    data = {"username": username, "email": email, "password": password}

    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=data)
    response = r.json()
    auth_token = response["access_token"]
    headers = {"Authorization": f"Bearer {auth_token}"}
    return headers


async def create_random_user(db: AsyncSession) -> User:
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password)
    user = await UserCRUD().create_user(db, user_in.model_dump())
    return user


async def authentication_token_from_email(
        *, client: TestClient, username: str, email: EmailStr, db: AsyncSession
) -> dict[str, str]:
    """
    Return a valid token for the user with given email.

    If the user doesn't exist it is created first.
    """
    password = random_lower_string()
    user = await UserCRUD().get_by_username(db, username)
    if not user:
        user_in_create = UserCreate(username=username, email=email, password=password)
        user = await UserCRUD().create_user(db, user_in_create.model_dump())
    else:
        user_in_update = UserUpdate(username=username, password=password)
        if not user.id:
            raise Exception("User id not set")
        user = await UserCRUD().update(db, user, user_in_update.model_dump())

    return user_authentication_headers(client=client, username=username, email=str(email), password=password)
