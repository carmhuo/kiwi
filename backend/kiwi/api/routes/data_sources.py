import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status, UploadFile, File

from kiwi.core.config import settings
from kiwi.core.services.file_storage import FileStorage
from kiwi.crud.data_source import DataSourceCRUD, DataSourceType
from kiwi.crud.roles import UserRoles
from kiwi.schemas import (
    DataSourceResponse,
    DataSourcesResponse,
    DataSourceCreate,
    DataSourceUpdate,
    DataSourceConnection,
    Message,
)
from kiwi.api.deps import (
    CurrentUser,
    SessionDep,
)
from kiwi.utils import generate_hashed_id

router = APIRouter(prefix="/data-sources", tags=["data_sources"])

upload_path = settings.STORAGE_PATH


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


@router.get("/project/{project_id}", response_model=DataSourcesResponse)
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
    crud = DataSourceCRUD()
    count = await crud.count(session)
    sources = await crud.list_data_sources_by_project(session, project_id, skip, limit)
    return DataSourcesResponse(data=sources, count=count)


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
    if not UserRoles.has_data_source_read(session, current_user):
        return HTTPException(status_code=400, detail="Not enough permissions")

    data_source = await DataSourceCRUD().get_data_source(session, data_source_id)
    if not data_source:
        raise HTTPException(status_code=404, detail="Data source not found")

    return data_source


@router.post("/", response_model=DataSourceResponse)
async def create_data_source(
        session: SessionDep,
        current_user: CurrentUser,
        data_source_in: DataSourceCreate
) -> Any:
    """
    Create a new data source.
    """
    try:
        source_type = DataSourceType(data_source_in.type.strip().lower())
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid data source type")

    # TODO 参数校验：补充其他字段的校验逻辑
    existing_source_name = await DataSourceCRUD().get_data_source_by_name(session, data_source_in.name)
    if existing_source_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DataSource name already registered"
        )
    return await DataSourceCRUD().create_data_source(session, data_source_in, current_user.id, source_type)


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
    data_source = await DataSourceCRUD().get_data_source(session, data_source_id)
    if not data_source:
        raise HTTPException(status_code=404, detail="DataSource not found")
    update_dict = data_source_in.model_dump(exclude_unset=True)
    return await DataSourceCRUD().update(session, data_source, update_dict)


@router.delete("/{data_source_id}", response_model=Message)
async def delete_data_source(
        session: SessionDep,
        current_user: CurrentUser,
        data_source_id: str
) -> Any:
    """
    Delete a data source.
    """
    # TODO 判断是否有删除权限
    db_data_source = await DataSourceCRUD().get_data_source(session, data_source_id)
    if not db_data_source:
        raise HTTPException(status_code=404, detail="Data source not found")
    await DataSourceCRUD().delete(session, data_source_id)
    return Message(message="DataSource deleted successfully")


@router.get("/{data_source_id}/activity", response_model=Message)
async def data_source_activity(
        session: SessionDep,
        current_user: CurrentUser,
        data_source_id: str
):
    activity = await DataSourceCRUD().test_connection(session, data_source_id=data_source_id)
    return activity


@router.post("/connection/activity")
async def data_source_connection_test(
        session: SessionDep,
        current_user: CurrentUser,
        connection: DataSourceConnection
) -> Any:
    """
    Create a new data source.
    """
    activity = await DataSourceCRUD().test_connection(session, connection=connection)
    return activity


@router.post("/data/preview/{data_source_id}")
async def preview_data(session: SessionDep, current_user: CurrentUser, data_source_id: int, full_table_name: str):
    raise NotImplementedError("table data preview not support")


@router.post("/file")
async def upload_data_file(
        session: SessionDep,
        current_user: CurrentUser,
        project_id: str,
        file_source: DataSourceCreate,
        file: UploadFile = File(...),
):
    """处理Excel/CSV文件上传

       Raises:
           HTTPException: 400 - 文件类型不支持或路径无效
           HTTPException: 500 - 文件上传失败
       """
    ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv"}

    if not file.filename.lower().endswith(tuple(ALLOWED_EXTENSIONS)):
        raise HTTPException(400, f"Only support {', '.join(ALLOWED_EXTENSIONS)} files")

    secure_filename = os.path.basename(file.filename)
    name_part, ext_part = os.path.splitext(secure_filename)
    file_ext = ext_part.lstrip('.')

    os.makedirs(f"{upload_path}/{project_id}", exist_ok=True)

    # 保存文件到存储
    storage = FileStorage()
    # 生成唯一文件名
    # generate_hashed_id = int(time.time() * 1000)  # 使用时间戳比哈希更高效
    filename = f"{name_part}_{generate_hashed_id}"
    save_path: str = os.path.join(upload_path, filename)
    file_path = f"data_sources/{project_id}/{filename}.{file_ext}"

    # 防止路径遍历攻击，确保路径在指定目录内
    if not os.path.abspath(save_path).startswith(os.path.abspath(upload_path)):
        raise HTTPException(400, "Invalid file path")

    try:
        # 使用流式处理大文件，避免全部加载到内存
        # with open(save_path, "wb") as f:
        #     while True:
        #         chunk = await file.read(64 * 1024)  # 64KB chunks
        #         if not chunk:
        #             break
        #         f.write(chunk)
        await storage.upload_file(file_path, await file.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")

    try:
        file_source.connection_config["file_path"] = file_path

        data_source = await DataSourceCRUD().create_data_source(
            session,
            file_source,
            user_id=current_user.id,
            type=file_source.type
        )
        # 测试连接
        test_result  = await DataSourceCRUD().test_connection(session, data_source_id=data_source.id)
        if not test_result["status"]:
            await DataSourceCRUD().delete_data_source(data_source.id)
            await storage.delete_file(file_path)
            raise HTTPException(
                status_code=400,
                detail=f"Failed to verify data source: {test_result['message']}"
            )
        return data_source

    except Exception as e:
        # 清理已创建的文件
        await storage.delete_file(file_path)
        raise HTTPException(500, f"File upload failed: {str(e)}")
