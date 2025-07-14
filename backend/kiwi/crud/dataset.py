from kiwi_backend.database import BaseCRUD
from kiwi_backend.models import Dataset, DatasetDataSource
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession


class DatasetCRUD(BaseCRUD):
    def __init__(self):
        super().__init__(Dataset)

    async def create_with_data_sources(
            self,
            db: AsyncSession,
            dataset_data: dict,
            data_sources: list[dict]
    ):
        """创建数据集并关联数据源"""
        # 创建数据集
        dataset = await self.create(db, dataset_data)

        # 添加数据源关联
        for ds in data_sources:
            await self.add_data_source(
                db,
                dataset_id=dataset.id,
                data_source_id=ds["id"],
                alias=ds["alias"]
            )
        return dataset

    async def add_data_source(
            self,
            db: AsyncSession,
            dataset_id: int,
            data_source_id: int,
            alias: str
    ):
        """添加数据集与数据源的关联"""
        # 检查别名是否唯一
        stmt = select(DatasetDataSource).where(
            DatasetDataSource.dataset_id == dataset_id,
            DatasetDataSource.alias == alias
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            raise ValueError(f"别名 '{alias}' 已存在")

        # 创建关联
        ds_link = DatasetDataSource(
            dataset_id=dataset_id,
            data_source_id=data_source_id,
            alias=alias
        )
        db.add(ds_link)
        await db.flush()

    async def remove_data_source(
            self,
            db: AsyncSession,
            dataset_id: int,
            alias: str
    ):
        """移除数据集与数据源的关联"""
        stmt = delete(DatasetDataSource).where(
            DatasetDataSource.dataset_id == dataset_id,
            DatasetDataSource.alias == alias
        )
        await db.execute(stmt)
        return True

    async def get_data_sources(
            self,
            db: AsyncSession,
            dataset_id: int
    ):
        """获取数据集关联的所有数据源"""
        stmt = select(DatasetDataSource).where(
            DatasetDataSource.dataset_id == dataset_id
        )
        result = await db.execute(stmt)
        return result.scalars().all()