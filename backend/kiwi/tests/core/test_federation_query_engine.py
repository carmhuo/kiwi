import json

import pytest
import asyncio
from kiwi.core.engine.federation_query_engine import FederationQueryEngine, DuckDBExtensionsType
from fastapi import HTTPException
import duckdb

from kiwi.schemas import QueryResult

# 测试配置 - 替换为您的实际测试数据库连接信息
TEST_CONFIGS = {
    "postgres": {
        "host": "localhost",
        "port": 5432,
        "database": "kiwi",
        "username": "postgres",
        "password": "Pass1234",
        "database_schema": "public"
    },
    "mysql": {
        "host": "localhost",
        "port": 3306,
        "database": "test_db",
        "username": "test_user",
        "password": "test_password"
    },
    "sqlite": {
        "path": ":memory:"  # 使用内存数据库进行测试
    },
    "s3": {
        "endpoint": "http://localhost:9000",
        "access_key": "minioadmin",
        "secret_key": "minioadmin",
        "region": "us-east-1",
        "url_style": "path"
    }
}


@pytest.fixture(scope="module", autouse=True)
async def setup_teardown():
    """在所有测试开始前初始化和结束后清理连接池"""
    await FederationQueryEngine.initialize()
    print("Connection pool initialized")
    yield
    await FederationQueryEngine.shutdown()


@pytest.mark.asyncio
async def test_connection_pool_initialization():
    """测试连接池初始化"""
    # 确保先初始化
    if not FederationQueryEngine.is_initialized():
        await FederationQueryEngine.initialize()
    assert FederationQueryEngine.is_initialized() is True


@pytest.mark.asyncio
async def test_get_duckdb_connection():
    """测试获取DuckDB连接"""
    async with FederationQueryEngine.get_duckdb_connection() as conn:
        assert conn is not None
        result = conn.execute("SELECT 1").fetchone()
        assert result[0] == 1

@pytest.mark.asyncio
async def test_postgres_connection():
    """测试PostgreSQL连接"""
    config = TEST_CONFIGS["postgres"]
    alias = "test_pg"
    # 确保先初始化
    if not FederationQueryEngine.is_initialized():
        await FederationQueryEngine.initialize()
    async with FederationQueryEngine.get_duckdb_connection() as conn:
        try:
            # 生成并执行ATTACH语句
            stmt = FederationQueryEngine.generate_attach_statement(
                DuckDBExtensionsType.POSTGRES, config, alias
            )
            assert "READ_ONLY" in stmt
            assert "SCHEMA" in stmt  # PostgreSQL需要指定schema
            conn.execute(stmt)

            # 验证数据库是否已附加
            result = conn.execute(
                "SELECT * FROM duckdb_databases() WHERE database_name = ?",
                [alias]
            ).fetchone()

            assert result is not None
            assert result[0] == alias

            # 测试各种查询操作
            test_queries = [
                f"SELECT * FROM information_schema.tables where table_catalog = ?  LIMIT 1",  # PostgreSQL系统表
                f"SELECT * FROM information_schema.columns where table_catalog = ?  LIMIT 1",  # PostgreSQL系统表
                f"SELECT * FROM information_schema.table_constraints where table_catalog = ? LIMIT 1"
            ]

            for query in test_queries:
                result = conn.execute(query, [alias])
                assert result is not None  # 只要不报错即可

            # 测试各种写操作
            write_operations = [
                f"CREATE TABLE {alias}.test_table (id INT)",
            ]

            for operation in write_operations:
                with pytest.raises(Exception) as exc_info:
                    conn.execute(operation)

                assert "permission" in str(exc_info.value).lower() or \
                       "read-only" in str(exc_info.value).lower(), \
                    f"写操作 '{operation}' 未被正确拒绝"

        finally:
            conn.execute(f"DETACH {alias}")


@pytest.mark.asyncio
async def test_mysql_connection():
    """测试MySQL连接"""
    config = TEST_CONFIGS["mysql"]
    alias = "test_mysql"

    async with FederationQueryEngine.get_duckdb_connection() as conn:
        try:
            # 生成并执行ATTACH语句
            stmt = FederationQueryEngine.generate_attach_statement(
                DuckDBExtensionsType.MYSQL, config, alias
            )
            assert "READ_ONLY" in stmt
            conn.execute(stmt)

            # 验证数据库是否已附加
            result = conn.execute(
                "SELECT * FROM duckdb_databases() WHERE database_name = ?",
                [alias]
            ).fetchone()

            assert result is not None
            assert result[0] == alias

            # 执行简单查询测试
            test_table = f"{alias}.mysql_test_table"
            conn.execute(f"CREATE TABLE {test_table} (id INTEGER, name VARCHAR(255))")
            conn.execute(f"INSERT INTO {test_table} VALUES (1, 'test')")
            query_result = conn.execute(f"SELECT * FROM {test_table}").fetchall()

            assert len(query_result) == 1
            assert query_result[0][0] == 1
            assert query_result[0][1] == "test"

        finally:
            # 清理
            conn.execute(f"DROP TABLE IF EXISTS {test_table}")
            conn.execute(f"DETACH {alias}")


@pytest.mark.asyncio
async def test_sqlite_connection():
    """测试SQLite连接"""
    config = TEST_CONFIGS["sqlite"]
    alias = "test_sqlite"

    async with FederationQueryEngine.get_duckdb_connection() as conn:
        try:
            # 生成并执行ATTACH语句
            stmt = FederationQueryEngine.generate_attach_statement(
                DuckDBExtensionsType.SQLITE, config, alias
            )
            conn.execute(stmt)

            # 验证数据库是否已附加
            result = conn.execute(
                "SELECT * FROM duckdb_databases() WHERE database_name = ?",
                [alias]
            ).fetchone()

            assert result is not None
            assert result[0] == alias

            # 执行简单查询测试
            test_table = f"{alias}.sqlite_test_table"
            conn.execute(f"CREATE TABLE {test_table} (id INTEGER, name TEXT)")
            conn.execute(f"INSERT INTO {test_table} VALUES (1, 'test')")
            query_result = conn.execute(f"SELECT * FROM {test_table}").fetchall()

            assert len(query_result) == 1
            assert query_result[0][0] == 1
            assert query_result[0][1] == "test"

        finally:
            # 清理
            conn.execute(f"DROP TABLE IF EXISTS {test_table}")
            conn.execute(f"DETACH {alias}")


@pytest.mark.asyncio
async def test_s3_connection():
    """测试S3连接"""
    if not TEST_CONFIGS["s3"]["endpoint"]:
        pytest.skip("S3测试配置未提供，跳过测试")

    config = TEST_CONFIGS["s3"]
    alias = "test_s3"

    async with FederationQueryEngine.get_duckdb_connection() as conn:
        try:
            # 生成并执行S3配置语句
            stmt = FederationQueryEngine.generate_attach_statement(
                DuckDBExtensionsType.S3, config, alias
            )
            conn.execute(stmt)

            # 验证S3配置是否生效
            conn.execute("SET s3_endpoint='localhost:9000'")
            conn.execute("SET s3_use_ssl=false")
            conn.execute("SET s3_url_style='path'")

            # 尝试列出bucket (需要实际有bucket)
            try:
                result = conn.execute("SELECT * FROM glob('s3://*/*')").fetchall()
                assert isinstance(result, list)
            except duckdb.Error as e:
                # 如果没有bucket，可能会报错，但至少连接配置是正确的
                assert "No files found" in str(e) or "Bucket does not exist" in str(e)

        finally:
            # 清理S3 secret
            conn.execute(f"DROP SECRET IF EXISTS secret_{alias}")


@pytest.mark.asyncio
async def test_table_view_creation():
    """测试表视图创建功能"""
    config = TEST_CONFIGS["postgres"]
    alias = "test_view_pg"
    source_table = "test_source_table"
    target_view = "test_target_view"

    async with FederationQueryEngine.get_duckdb_connection() as conn:
        try:
            # 附加PostgreSQL数据库
            stmt = FederationQueryEngine.generate_attach_statement(
                DuckDBExtensionsType.POSTGRES, config, alias
            )
            conn.execute(stmt)

            # 创建测试表
            conn.execute(f"CREATE TABLE {alias}.{source_table} (id INTEGER, name VARCHAR, age INTEGER)")
            conn.execute(f"INSERT INTO {alias}.{source_table} VALUES (1, 'Alice', 30), (2, 'Bob', 25)")

            # 创建视图
            view_stmt = FederationQueryEngine.generate_table_view_statement(
                alias, source_table, target_view, ["id", "name"]
            )
            conn.execute(view_stmt)

            # 查询视图
            result = conn.execute(f"SELECT * FROM {target_view} ORDER BY id").fetchall()

            assert len(result) == 2
            assert result[0][0] == 1
            assert result[0][1] == "Alice"
            assert len(result[0]) == 2  # 只选择了2列

        finally:
            # 清理
            conn.execute(f"DROP VIEW IF EXISTS {target_view}")
            conn.execute(f"DROP TABLE IF EXISTS {alias}.{source_table}")
            conn.execute(f"DETACH {alias}")


@pytest.mark.asyncio
async def test_execute_query_with_dataset(mocker):
    """测试使用数据集执行查询"""
    # 模拟数据库会话
    mock_db = mocker.MagicMock()

    # 模拟数据集配置
    dataset_config = {
        "tables": [
            {
                "source_alias": "test_pg",
                "table_name": "test_table",
                "columns": ["id", "name"]
            }
        ],
        "table_mappings": [
            {
                "source_table": "test_table",
                "target_name": "mapped_table"
            }
        ],
        "relationships": [
            {
                "left_table": "mapped_table",
                "left_column": "id",
                "right_table": "other_table",
                "right_column": "id",
                "type": "one-to-many"
            }
        ]
    }

    # 模拟数据集对象
    mock_dataset = mocker.MagicMock()
    mock_dataset.id = "test_dataset"
    mock_dataset.project_id = "test_project"
    mock_dataset.configuration = json.dumps(dataset_config)

    # 模拟数据源关系
    mock_data_source = mocker.MagicMock()
    mock_data_source.alias = "test_pg"
    mock_data_source.type = "postgres"
    mock_data_source.connection_config = TEST_CONFIGS["postgres"]

    mock_ds_rel = mocker.MagicMock()
    mock_ds_rel.data_source = mock_data_source
    mock_dataset.data_sources = [mock_ds_rel]

    # 设置mock返回值
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_dataset

    # 测试SQL
    test_sql = "SELECT * FROM mapped_table LIMIT 10"

    # 执行测试
    result = await FederationQueryEngine.execute_query(
        db=mock_db,
        project_id="test_project",
        sql=test_sql,
        dataset_id="test_dataset",
        preview=True
    )

    # 验证结果
    assert isinstance(result, QueryResult)
    assert result.loaded_sources == ["test_pg"]
    assert "mapped_table" in result.loaded_tables


@pytest.mark.asyncio
async def test_connection_activity_test():
    """测试连接活动测试功能"""
    # 测试PostgreSQL连接
    config = TEST_CONFIGS["postgres"]
    result = await FederationQueryEngine.connection_activity_test(
        connection_config=config,
        source_type="postgres"
    )

    assert isinstance(result, dict)
    assert "status" in result
    assert "message" in result
    assert "error_type" in result

    # 测试无效类型
    invalid_result = await FederationQueryEngine.connection_activity_test(
        connection_config=config,
        source_type="invalid_type"
    )

    assert invalid_result["status"] is False
    assert invalid_result["error_type"] == "INVALID_TYPE"


@pytest.mark.asyncio
async def test_query_timeout():
    """测试查询超时处理"""
    async with FederationQueryEngine.get_duckdb_connection() as conn:
        # 创建一个长时间运行的查询
        with pytest.raises(HTTPException) as exc_info:
            await asyncio.wait_for(
                asyncio.to_thread(conn.execute, "SELECT * FROM range(100000000)"),
                timeout=0.1  # 设置很短的超时时间
            )

        assert exc_info.value.status_code == 504
        assert "timeout" in exc_info.value.detail.lower()


if __name__ == "__main__":
    # 直接运行所有测试
    pytest.main(["-v", "-s", __file__])
