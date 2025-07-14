from kiwi_backend.database import BaseCRUD
from kiwi_backend.models import DataSource
from kiwi_backend.utils.encryption import encrypt_data, decrypt_data
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class DataSourceCRUD(BaseCRUD):
    def __init__(self):
        super().__init__(DataSource)

    async def create_encrypted(
            self,
            db: AsyncSession,
            data_source_data: dict
    ):
        """创建加密的数据源配置"""
        # 加密敏感字段
        encrypted_config = encrypt_data(data_source_data["connection_config"])
        data_source_data["connection_config"] = encrypted_config
        return await self.create(db, data_source_data)

    async def update_encrypted(
            self,
            db: AsyncSession,
            db_obj,
            update_data: dict
    ):
        """更新加密的数据源配置"""
        if "connection_config" in update_data:
            update_data["connection_config"] = encrypt_data(
                update_data["connection_config"]
            )
        return await self.update(db, db_obj, update_data)

    async def get_decrypted(
            self,
            db: AsyncSession,
            id: int
    ):
        """获取解密后的数据源配置"""
        data_source = await self.get(db, id)
        if not data_source:
            return None

        # 解密连接配置
        decrypted_config = decrypt_data(data_source.connection_config)
        data_source.connection_config = decrypted_config
        return data_source

    async def test_connection(
            self,
            db: AsyncSession,
            data_source_id: int
    ):
        """测试数据源连接"""
        data_source = await self.get_decrypted(db, data_source_id)
        if not data_source:
            return False

        # 根据类型创建连接
        db_type = data_source.type.lower()
        try:
            if db_type == "mysql":
                import mysql.connector
                conn = mysql.connector.connect(
                    **data_source.connection_config
                )
                conn.close()
                return True

            elif db_type == "postgresql":
                import psycopg2
                conn = psycopg2.connect(
                    **data_source.connection_config
                )
                conn.close()
                return True

            # 其他数据库类型...

        except Exception as e:
            print(f"连接测试失败: {str(e)}")
            return False