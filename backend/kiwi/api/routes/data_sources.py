from typing import Any

from fastapi import APIRouter, HTTPException, status, Depends

from kiwi.crud.data_source import DataSourceCRUD, DataSourceType
from kiwi.crud.roles import UserRoles
from kiwi.schemas import (
    DataSourceResponse,
    DataSourcesResponse,
    DataSourceCreate,
    DataSourceUpdate,
)
from kiwi.api.deps import (
    CurrentUser,
    SessionDep,
)

router = APIRouter(prefix="/data-sources", tags=["data_sources"])


@router.get("/", response_model=DataSourcesResponse)
async def read_data_sources(
        session: SessionDep,
        current_user: CurrentUser,
        skip: int = 0,
        limit: int = 100
) -> Any:
    """
    Get all data sources
    """
    crud = DataSourceCRUD()
    count = await crud.count(session)
    data_sources = await crud.get_multi(session, skip, limit)
    return DataSourcesResponse(data=data_sources, count=count)


@router.get("/", response_model=DataSourcesResponse)
async def read_data_sources_me(
        session: SessionDep,
        current_user: CurrentUser,
        skip: int = 0,
        limit: int = 100
) -> Any:
    """
    Get all data sources in a project.
    """
    crud = DataSourceCRUD()
    count = await crud.count(session)
    data_sources = await crud.list_data_sources_by_user(session, current_user.id, skip, limit)
    return DataSourcesResponse(data=data_sources, count=count)


@router.get("/project/{project_id}", response_model=DataSourceResponse)
async def read_data_sources_by_project(
        session: SessionDep,
        current_user: CurrentUser,
        project_id: str,
        skip: int = 0,
        limit: int = 100
) -> Any:
    """
    Get all data sources in a project.
    """
    return await DataSourceCRUD.list_data_sources_by_project(session, project_id, skip, limit)


@router.get("/{data_source_id}", response_model=DataSourceResponse)
async def read_data_source_detail(
        session: SessionDep,
        current_user: CurrentUser,
        data_source_id: str
) -> Any:
    """
    Retrieve the detailed information of a specific data source.

    Args:
        session (SessionDep): Database session dependency.
        current_user (CurrentUser): Current authenticated user dependency.
        data_source_id (str): Unique identifier of the data source to retrieve.

    Returns:
        Any: Detailed information of the specified data source.
    """
    if not UserRoles.has_data_source_read(session, current_us):
        return HTTPException(status_code=400, detail="Not enough permissions")

    return await DataSourceCRUD().get_data_source(session, data_source_id, current_user.id)


@router.post("/", response_model=DataSourceResponse)
async def create_data_source(
        session: SessionDep,
        current_user: CurrentUser,
        data_source: DataSourceCreate
) -> Any:
    """
    Create a new data source.
    """
    try:
        source_type = DataSourceType(data_source.type.strip().lower())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid data source type")

    # TODO 参数校验：补充其他字段的校验逻辑

    return await DataSourceCRUD().create_data_source(session, data_source, current_user.id, source_type)



@router.post("/{data_source_id}", response_model=DataSourceResponse)
async def update_data_source(
        session: SessionDep,
        current_user: CurrentUser,
        data_source_id: str,
        data_source_in: DataSourceUpdate
) -> Any:
    """
    Update a data source.
    """
    pass


@router.post("/test", response_model=DataSourceResponse)
async def connection_test(
        session: SessionDep,
        current_user: CurrentUser,
        data_source_id: str,
        data_source: DataSourceCreate
) -> Any:
    pass
