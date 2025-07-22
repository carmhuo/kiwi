import json

from kiwi.core.database import BaseCRUD
from kiwi.core.config import logger
from kiwi.models import Dataset, DatasetProjectSource, ProjectDataSource, User
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.schemas import DatasetCreate, DatasetResponse


class DatasetCRUD(BaseCRUD):
    def __init__(self):
        super().__init__(Dataset)

    async def get_dataset_by_name(self, db, project_id, name):
        return await self.get_by_multi_field(db, project_id=project_id, name=name)

    async def get_datasets_by_project(
            self,
            db: AsyncSession,
            project_id: str,
            skip: int = 0,
            limit: int = 100
    ) -> list[DatasetResponse]:
        """
           查出项目下所有数据集，并包含：
           - 创建者 name
           - 关联的数据源别名列表
           """
        try:
            if db.bind.dialect.name == "postgresql":
                query = (
                    select(
                        Dataset.id,
                        Dataset.name,
                        Dataset.configuration,
                        Dataset.created_by,
                        Dataset.created_at,
                        Dataset.updated_at,
                        User.username.label("creator_name"),
                        func.coalesce(
                            func.array_agg(DatasetProjectSource.data_source_alias),
                            []
                        ).label("data_source_aliases")
                    )
                    .outerjoin(User, User.id == Dataset.created_by)
                    .outerjoin(
                        DatasetProjectSource, DatasetProjectSource.dataset_id == Dataset.id)
                    .where(Dataset.project_id == project_id)
                    .group_by(
                        Dataset.id,
                        Dataset.name,
                        Dataset.created_by,
                        Dataset.created_at,
                        Dataset.updated_at,
                        User.username
                    )
                    .order_by(Dataset.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
                result = await db.execute(query)
                return result.scalars().all()
            else:
                stmt = (
                    select(
                        Dataset.id,
                        Dataset.name,
                        Dataset.description,
                        Dataset.configuration,
                        Dataset.created_by,
                        Dataset.created_at,
                        Dataset.updated_at,
                        User.username.label("creator_name"),
                        func.coalesce(
                            func.aggregate_strings(DatasetProjectSource.data_source_alias, ','),
                            None
                        ).label("data_source_aliases")
                    )
                    .outerjoin(User, User.id == Dataset.created_by)
                    .outerjoin(
                        DatasetProjectSource, DatasetProjectSource.dataset_id == Dataset.id)
                    .where(Dataset.project_id == project_id)
                    .group_by(
                        Dataset.id,
                        Dataset.name,
                        Dataset.created_by,
                        Dataset.created_at,
                        Dataset.updated_at,
                        User.username
                    )
                    .order_by(Dataset.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
                result = await db.execute(stmt)
                # rows = result.all()
                return [
                    DatasetResponse(
                        id=row.id,
                        name=row.name,
                        description=row.description,
                        data_source_aliases=row.data_source_aliases.split(",") if row.data_source_aliases else [],
                        configuration=row.configuration,
                        created_by=row.created_by,
                        creator_name=row.creator_name,
                        created_at=row.created_at,
                        updated_at=row.updated_at
                    )
                    for row in result.all()
                ]
        except Exception as e:
            logger.error("Error fetching datasets by project", extra={'project_id': project_id})
            raise e

    async def create_with_data_sources(
            self,
            db: AsyncSession,
            dataset_data: DatasetCreate,
            user_id: str
    ) -> Dataset:
        """创建数据集并关联数据源"""
        if not dataset_data.project_id:
            raise ValueError("project_id 不能为空")

        dataset_dict = dataset_data.model_dump()
        data_source_aliases = dataset_dict.pop("data_source_aliases", None)
        if not data_source_aliases:
            raise ValueError("至少需要一个数据源")

        dataset_dict['configuration'] = json.dumps(dataset_data.configuration)
        dataset_dict['created_by'] = user_id
        # 创建数据集
        dataset = await self.create(db, dataset_dict)

        data_source_aliases = list(set(dataset_data.data_source_aliases))
        # 添加数据源关联
        links = []
        for ds_alias in data_source_aliases:
            ds_link = await self.create_data_source_link(
                db=db,
                dataset_id=dataset.id,
                data_source_alias=ds_alias,
                project_id=dataset_data.project_id
            )
            links.append(ds_link)
        db.add_all(links)
        await db.flush()
        return dataset

    async def create_data_source_link(
            self,
            db: AsyncSession,
            dataset_id: int,
            data_source_alias: str,
            project_id: str,
    ) -> DatasetProjectSource:
        """添加数据集与数据源的关联"""
        # 查询数据源是否存在
        stmt = select(ProjectDataSource).where(
            ProjectDataSource.project_id == project_id,
            ProjectDataSource.alias == data_source_alias
        )
        result = await db.execute(stmt)
        if not result.scalar_one_or_none():
            raise ValueError(f"数据源别名 '{data_source_alias}' 不存在")

        # 创建关联
        ds_link = DatasetProjectSource(
            dataset_id=dataset_id,
            data_source_alias=data_source_alias
        )

        return ds_link

    async def remove_data_source(
            self,
            db: AsyncSession,
            dataset_id: str,
            alias: str
    ):
        """移除数据集与数据源的关联"""

        raise NotImplementedError("该方法尚未实现")

    async def get_data_sources(
            self,
            db: AsyncSession,
            dataset_id: int
    ):
        """获取数据集关联的所有数据源"""
        raise NotImplementedError("该方法尚未实现")
