from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.core.config import logger as app_logger
from kiwi.crud.dataset import DatasetCRUD
from kiwi.schemas import Message, DatasetResponse, DatasetCreate, DatasetsResponse

router = APIRouter(prefix="/datasets", tags=["datasets"])

from kiwi.api.deps import (
    CurrentUser,
    SessionDep,
)


@router.get("/{dataset_id}")
async def read_dataset(session: SessionDep,
                       current_user: CurrentUser,
                       dataset_id: str):
    try:
        # 记录信息日志（异步）
        await app_logger.ainfo(
            "Reading a dataset",
            extra={"dataset_id": dataset_id, "user_name": current_user.username}
        )
        return await DatasetCRUD().get(session, dataset_id)
    except Exception as e:
        # 记录错误日志（同步）
        app_logger.error(
            "Dataset reading failed",
            extra={
                "error": str(e),
                "dataset_id": dataset_id,
                "user_name": current_user.username
            }
        )
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/project/{project_id}")
async def list_project_datasets(session: SessionDep,
                                current_user: CurrentUser,
                                project_id,
                                skip: int = 0,
                                limit: int = 100
                                ):
    try:
        count = await DatasetCRUD().count(session, project_id=project_id)
        datasets = await DatasetCRUD().get_datasets_by_project(session, project_id, skip, limit)
        return DatasetsResponse(data=datasets, count=count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=DatasetResponse)
async def create_new_dataset(
        session: SessionDep,
        current_user: CurrentUser,
        dataset: DatasetCreate
):
    try:
        existing_dataset = await DatasetCRUD().get_dataset_by_name(
            session,
            dataset.project_id,
            dataset.name
        )
        if existing_dataset:
            raise HTTPException(status_code=409, detail="数据集名称已存在")

        new_dataset = await DatasetCRUD().create_with_data_sources(
            db=session,
            dataset_data=dataset,
            user_id=current_user.id
        )

        # 构造响应（包含数据源别名）
        return DatasetResponse(
            id=new_dataset.id,
            name=new_dataset.name,
            description=new_dataset.description,
            configuration=new_dataset.configuration,
            data_source_aliases=dataset.data_source_aliases,
            created_by=new_dataset.created_by,
            creator_name=current_user.username,
            created_at=new_dataset.created_at,
            updated_at=new_dataset.updated_at,
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
