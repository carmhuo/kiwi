from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import select, delete, func

from kiwi.core.config import settings

engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    echo=settings.DEBUG,  # 开发时开启，生产环境关闭
    future=True
)
# 异步会话工厂
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def get_db_session():
    """获取异步数据库会话的上下文管理器"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


Base = declarative_base()


class BaseCRUD:
    """基础CRUD操作类"""

    def __init__(self, model):
        self.model = model

    async def create(self, db: AsyncSession, obj_in: dict):
        """创建新记录"""
        db_obj = self.model(**obj_in)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    async def get(self, db: AsyncSession, id: int):
        """根据ID获取记录"""
        return await db.get(self.model, id)

    async def get_by_field(self, db: AsyncSession, field: str, value):
        """根据字段值获取记录"""
        stmt = select(self.model).where(getattr(self.model, field) == value)
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_multi(
            self,
            db: AsyncSession,
            skip: int = 0,
            limit: int = 100,
            **filters
    ):
        """获取多条记录（带过滤）"""
        stmt = select(self.model)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        stmt = stmt.offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def update(self, db: AsyncSession, db_obj, obj_in: dict):
        """更新记录"""
        for field, value in obj_in.items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        await db.flush() # 发送更新到数据库，当前事务可见
        await db.refresh(db_obj) # 刷新收发器
        return db_obj

    async def delete(self, db: AsyncSession, id: str):
        """删除记录"""
        stmt = delete(self.model).where(self.model.id == id)
        await db.execute(stmt)
        return True

    async def count(self, db: AsyncSession, **filters) -> int:
        """获取表记录总数（可带过滤条件）"""
        stmt = select(func.count()).select_from(self.model)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        result = await db.execute(stmt)
        return result.scalar() or 0
