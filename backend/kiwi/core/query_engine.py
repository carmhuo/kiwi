import os
import json
import traceback
import uuid
from enum import Enum

from typing import Dict, Any

import duckdb
import pandas as pd
from sqlalchemy import create_engine

from kiwi.core.config import logger

DUCKDB_EXTENSIONS = ['httpfs', 'sqlite', 'postgres', 'parquet', 'mysql', 'excel']


class DuckDBExtensionsType(str, Enum):
    HTTPFS = "httpfs"
    S3 = "S3"
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    POSTGRESQL = "postgresql"
    PARQUET = "parquet"
    MYSQL = "mysql"
    EXCEL = "excel"

@DeprecationWarning
class FederatedQueryEngine:
    """
    联邦查询引擎，资源隔离，一个项目拥有一个引擎实例，根据项目关联的数据源初始化引擎实例
    1.创建与一个实例，加载扩展项目数据源
    2. 注册数据源，确保注册到引擎中的有唯一的数据库名称
    3. 针对数据集中的表，创建全局唯一的表视图名称，如: vw_{db}_{table}
    """
    def __init__(
            self,
            ext_types: List[str],
            database: str = ":memory:",
            read_only=False,
            config: dict = None
    ):
        self.conn = duckdb.connect(database=database, read_only=read_only, config=config)
        self.ext_types = ext_types
        # 加载默认扩展
        self.load_extensions()

        self.temp_tables = set()
        self._initialized = True  # 添加初始化标志

        # 加载默认的AWS凭证（如果存在）
        self.secrets = {}
        self.load_default_aws_credentials()

    @classmethod
    def from_datasources(
            cls,
            ext_types: List[str],
            **kwargs: Any,
    ) -> FederatedQueryEngine:
        """Construct a federated query engine from heterogeneous data sources"""

        return cls(ext_types, **kwargs)

    def load_extensions(self):
        # 加载必要扩展
        for ext in self.ext_types:
            try:
                ext_type = DuckDBExtensionsType(ext)
            except  Exception as e:
                logger.warning(f"不支持的DuckDB扩展类型{ext}: {e}")
            try:
                self.conn.execute(f"INSTALL {ext}; LOAD {ext};")
                logger.info(f"DuckDB扩展已加载:{ext}")
            except duckdb.Error as e:
                self.logger.warning(f"无法加载扩展 {ext}: {e}")

    def load_default_aws_credentials(self):
        """尝试从环境变量加载默认AWS凭证"""
        access_key = os.getenv('S3_ACCESS_KEY')
        secret_key = os.getenv('S3_SECRET_KEY')
        region = os.getenv('S3_REGION', 'us-east-1')
        endpoint = os.getenv('S3_ENDPOINT', 's3.amazonaws.com')

        if access_key and secret_key:
            self.add_s3_secret("default_s3_secret", access_key, secret_key, region=region, endpoint=endpoint)
            self.logger.info("已从环境变量加载默认AWS凭证")

    def add_s3_secret(self, secret_name, access_key, secret_key, region='us-east-1', endpoint='s3.amazonaws.com',
                      url_style='path'):
        """
        使用CREATE SECRET添加S3认证凭证
        :param secret_name: 密钥名称
        :param endpoint: S3 endpoint
        :param access_key: S3访问密钥
        :param secret_key: S3秘密密钥
        :param region: S3区域
        :param url_style: Either vhost or path
        """
        # 删除同名密钥（如果存在）
        self.conn.execute(f"DROP SECRET IF EXISTS {secret_name};")

        # 创建S3类型密钥
        self.conn.execute(f"""
            CREATE OR REPLACE SECRET {secret_name} (
                TYPE s3,
                PROVIDER config,
                ENDPOINT '{endpoint}',
                KEY_ID '{access_key}',
                SECRET '{secret_key}',
                REGION '{region}',
                URL_STYLE '{url_style}'
            );
        """)
        self.secrets[secret_name] = {'region': region}
        self.logger(f"S3密钥 '{secret_name}' 已创建")

    def register_excel(self, file_path, table_name, sheet_name=0, header=True):
        """注册Excel文件为虚拟表"""
        # todo use read_xlsx() method to import excel data.
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        self.conn.register(table_name, df)
        self.temp_tables.add(table_name)
        print(f"Excel表 '{table_name}' 已注册")
        return df.shape

    def register_json(self, file_path, table_name):
        try:
            self.conn.execute(f"""
            CREATE TABLE {table_name} AS
            SELECT *
            FROM read_json_auto('{file_path}');
            """)
            self.temp_tables.add(table_name)
            self.logger.info(f"JSON '{table_name}' 已注册")
        except Exception as e:
            self.logger.error(f"注册JSON文件失败: {str(e)}")
            raise

    def register_csv(self, file_path, table_name, delimiter=',', header=True):
        """注册本地CSV文件为虚拟表"""
        try:
            self.conn.execute(f"""
            CREATE TABLE {table_name} AS 
            SELECT * FROM read_csv_auto('{file_path}', 
                delim='{delimiter}', 
                header={header})
            """)
            self.temp_tables.add(table_name)
            self.logger.info(f"CSV表 '{table_name}' 已注册")
            return self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        except Exception as e:
            self.logger.error(f"注册CSV文件失败: {str(e)}")
            raise

    def register_parquet(self, file_path, table_name):
        """注册本地Parquet文件为虚拟表"""
        try:
            self.conn.execute(f"""
                CREATE TABLE {table_name} AS 
                SELECT * FROM read_parquet('{file_path}')
            """)
            self.temp_tables.add(table_name)
            print(f"Parquet表 '{table_name}' 已注册")

            # 返回行数
            count = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            return count
        except Exception as e:
            self.logger.error(f"注册Parquet文件失败: {str(e)}")
            raise

    def register_s3_parquet(self, s3_path, table_name, secret_name='default_s3_secret', use_globbing=False):
        """
        注册S3上的Parquet文件或目录为虚拟表
        :param s3_path: S3路径 (s3://bucket/path/to/file.parquet)
        :param table_name: 要创建的虚拟表名
        :param secret_name: 使用的密钥名称
        :param use_globbing: 是否使用通配符匹配多个文件
        """
        if not s3_path.startswith('s3://'):
            raise ValueError("S3路径必须以's3://'开头")

        # 验证密钥是否存在
        if secret_name not in self.secrets:
            raise ValueError(f"未找到S3密钥 '{secret_name}'")
        try:
            # 使用带密钥的DuckDB读取S3上的Parquet
            if use_globbing:
                sql = f"""
                    CREATE TABLE {table_name} AS 
                    SELECT * FROM read_parquet('{s3_path}', secret='{secret_name}')
                """
            else:
                sql = f"""
                    CREATE TABLE {table_name} AS 
                    SELECT * FROM read_parquet('{s3_path}', secret='{secret_name}')
                """

            self.conn.execute(sql)
            self.temp_tables.add(table_name)
            self.logger.info(f"S3 Parquet表 '{table_name}' 已注册 (使用密钥 '{secret_name}')")
            return self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        except Exception as e:
            self.logger.error(f"注册S3 Parquet文件失败: {str(e)}")
            raise

    def register_s3_csv(self, s3_path, table_name, secret_name='default_s3_secret', delimiter=',', header=True):
        """注册S3上的CSV文件为虚拟表"""
        if not s3_path.startswith('s3://'):
            raise ValueError("S3路径必须以's3://'开头")

        if secret_name not in self.secrets:
            raise ValueError(f"未找到S3密钥 '{secret_name}'")
        try:
            sql = f"""
                CREATE TABLE {table_name} AS 
                SELECT * FROM read_csv_auto('{s3_path}', 
                    delim='{delimiter}', 
                    header={header},
                    secret='{secret_name}')
            """

            self.conn.execute(sql)
            self.temp_tables.add(table_name)
            self.logger.info(f"S3 CSV表 '{table_name}' 已注册 (使用密钥 '{secret_name}')")
        except Exception as e:
            self.logger.error(f"注册S3 CSV文件失败: {str(e)}")
            raise

    def register_s3_directory(self, s3_uri, table_name, file_format='parquet',
                              secret_name='default_s3_secret', pattern='*'):
        """
        注册S3目录下的所有文件
        :param s3_uri: S3目录路径 (s3://bucket/path/)
        :param table_name: 要创建的虚拟表名
        :param file_format: 文件格式 ('parquet' 或 'csv')
        :param secret_name: 使用的密钥名称
        :param pattern: 文件匹配模式 (例如 '*.parquet')
        """
        if not s3_uri.startswith('s3://'):
            raise ValueError("S3路径必须以's3://'开头")

        # 确保路径以斜杠结尾
        if not s3_uri.endswith('/'):
            s3_uri += '/'

        # 构造通配符路径
        s3_path = f"{s3_uri}{pattern}"

        if file_format == 'parquet':
            return self.register_s3_parquet(s3_path, table_name, secret_name, use_globbing=True)
        elif file_format == 'csv':
            return self.register_s3_csv(s3_path, table_name, secret_name)
        else:
            raise ValueError(f"不支持的文件格式: {file_format}")

    def list_s3_buckets(self, secret_name='default_s3_secret'):
        """列出可用的S3存储桶"""
        if secret_name not in self.secrets:
            raise ValueError(f"未找到S3密钥 '{secret_name}'")

        try:
            # 使用DuckDB的S3元数据函数
            result = self.conn.execute(f"""
                SELECT name, region, create_date 
                FROM duckdb_s3_metadata('s3://', secret='{secret_name}')
                WHERE type = 'bucket'
            """).fetchdf()
            return result
        except duckdb.Error as e:
            print(f"列出存储桶出错: {str(e)}")
            return pd.DataFrame()

    def list_s3_objects(self, bucket_name, prefix='', secret_name='default_s3_secret'):
        """列出S3存储桶中的对象"""
        if secret_name not in self.secrets:
            raise ValueError(f"未找到S3密钥 '{secret_name}'")

        s3_path = f"s3://{bucket_name}/{prefix}" if prefix else f"s3://{bucket_name}/"

        try:
            # 使用DuckDB的S3元数据函数
            return self.conn.execute(f"""
                SELECT 
                    name AS key,
                    size,
                    last_modified,
                    etag
                FROM duckdb_s3_metadata('{s3_path}', secret='{secret_name}')
                WHERE type = 'object'
            """).fetchdf()
        except duckdb.Error as e:
            print(f"列出对象出错: {str(e)}")
            return pd.DataFrame()

    def sample_parquet_data(self, s3_path, num_rows=5, secret_name='default_s3_secret'):
        """
        从S3 Parquet文件中采样数据
        :param s3_path: S3路径
        :param num_rows: 要采样的行数
        :param secret_name: 使用的密钥名称
        """
        if secret_name not in self.secrets:
            raise ValueError(f"未找到S3密钥 '{secret_name}'")

        # 使用DuckDB的LIMIT子句高效采样
        try:
            temp_table = f"__temp_sample_{hash(s3_path)}"
            self.conn.execute(f"""
                CREATE TEMP TABLE {temp_table} AS 
                SELECT * FROM read_parquet('{s3_path}', secret='{secret_name}')
                LIMIT {num_rows}
            """)

            result = self.conn.execute(f"SELECT * FROM {temp_table}").fetchdf()
            self.conn.execute(f"DROP TABLE IF EXISTS {temp_table}")
            return result
        except duckdb.Error as e:
            print(f"采样数据出错: {str(e)}")
            return pd.DataFrame()

    def get_parquet_metadata(self, s3_path, secret_name='default_s3_secret'):
        """
        获取Parquet文件的元数据
        :param s3_path: S3路径
        :param secret_name: 使用的密钥名称
        """
        if secret_name not in self.secrets:
            raise ValueError(f"未找到S3密钥 '{secret_name}'")

        # 使用DuckDB的parquet_metadata函数
        try:
            metadata = self.conn.execute(f"""
                SELECT * 
                FROM parquet_metadata('{s3_path}', secret='{secret_name}')
            """).fetchdf()

            # 提取有用的元数据
            if not metadata.empty:
                row_groups = metadata['row_group_id'].nunique()
                total_rows = metadata['num_rows'].sum()
                columns = metadata['column_name'].unique().tolist()

                return {
                    'total_rows': total_rows,
                    'row_groups': row_groups,
                    'columns': columns,
                    'file_size': metadata['total_compressed_size'].sum(),
                    'raw_metadata': metadata
                }
            return {}
        except duckdb.Error as e:
            print(f"获取元数据出错: {str(e)}")
            return {}

    def register_postgresql(self, database_path, schema, database_alias):
        attach_statement = f"""
                     ATTACH '{database_path}' AS {database_alias} (TYPE postgres, SCHEMA '{schema}', READ_ONLY)
                 """
        self.conn.execute(attach_statement)

    def register_mysql(self, database_path, database_alias):
        attach_statement = f"""
                     ATTACH '{database_path}' AS {database_alias} (TYPE mysql, READ_ONLY)
                 """
        self.conn.execute(attach_statement)

    def register_sqlite(self, database_path, database_alias):
        attach_statement = f"""
                             ATTACH '{database_path}' AS {database_alias} (TYPE sqlite, READ_ONLY)
                         """
        self.conn.execute(attach_statement)

    def register_sql(self, db_type, conn_str, table_name, remote_table=None):
        """注册SQL数据库表"""
        remote_table = remote_table or table_name

        if db_type == 'postgres':
            self.conn.execute(f"""
                CREATE TABLE {table_name} AS 
                SELECT * FROM postgres_scan('{conn_str}', 'public', '{remote_table}')
            """)
        elif db_type == 'sqlite':
            self.conn.execute(f"""
                CREATE TABLE {table_name} AS 
                SELECT * FROM sqlite_scan('{conn_str}', '{remote_table}')
            """)
        elif db_type == 'mysql':
            # 使用MySQL连接器
            engine = create_engine(conn_str)
            df = pd.read_sql(f"SELECT * FROM {remote_table}", engine)
            self.conn.register(table_name, df)
        else:
            raise ValueError(f"不支持的数据库类型: {db_type}")

        self.temp_tables.add(table_name)
        print(f"SQL表 '{table_name}' 已注册")

    def register_mongodb(self, conn_str, db_name, collection, table_name):
        """注册MongoDB集合"""
        from pymongo import MongoClient
        client = MongoClient(conn_str)
        db = client[db_name]
        cursor = db[collection].find()
        df = pd.DataFrame(list(cursor))

        # 清理MongoDB特有的_id字段
        if '_id' in df.columns:
            df.drop('_id', axis=1, inplace=True)

        self.conn.register(table_name, df)
        self.temp_tables.add(table_name)
        print(f"MongoDB集合 '{collection}' 已注册为表 '{table_name}'")

    def execute_query(self, query):
        """执行联邦查询"""
        try:
            result = self.conn.execute(query).fetchdf()
            return result
        except duckdb.Error as e:
            print(f"查询执行错误: {str(e)}")
            return None

    def explain_query(self, query):
        """解释查询执行计划"""
        try:
            return self.conn.execute(f"EXPLAIN {query}").fetchdf()
        except duckdb.Error as e:
            print(f"解释查询出错: {str(e)}")
            return None

    def connection_test(self, connection_config, source_type) -> Dict[str, Any]:
        """
            测试与DuckDB扩展的连接。

            参数:
            - connection_config: 连接配置信息。
            - source_type: 数据源类型。

            返回:
            - bool: 如果连接测试成功，则返回True；否则返回False。
            """
        try:
            ext_type = DuckDBExtensionsType(source_type)
        except  Exception as e:
            self.logger.error(f"不支持的DuckDB扩展类型: {e}")
            return {
                'status': False,
                'message': "不支持的DuckDB扩展类型"
            }

        database_alias = f"__{source_type}_db_test__"

        # test_result = self._register_and_test(connection_config, ext_type, database_alias)

        # return test_result
        try:
            return self._test_connection(connection_config, ext_type, database_alias)
        except Exception as e:
            self.logger.error(f"连接测试失败: {e}", exc_info=True)
            return {'status': False, 'message': str(e)}

    def _test_connection(self, config: dict, ext_type: DuckDBExtensionsType, database_alias: str) -> Dict[str, Any]:
        handlers = {
            DuckDBExtensionsType.S3: self._test_s3_connection,
            DuckDBExtensionsType.HTTPFS: self._test_httpfs_connection,
            DuckDBExtensionsType.SQLITE: self._test_sqlite_connection,
            DuckDBExtensionsType.MYSQL: self._test_mysql_connection,
            DuckDBExtensionsType.POSTGRES: self._test_postgres_connection,
            DuckDBExtensionsType.POSTGRESQL: self._test_postgres_connection,
            DuckDBExtensionsType.EXCEL: self._test_excel_connection,
        }

        handler = handlers.get(ext_type)
        if not handler:
            message = f"不支持的数据源类型: {ext_type}"
            self.logger.warning(message)
            return {'status': False, 'message': message}

        return handler(config, database_alias)

    def _test_httpfs_connection(self, config: dict, database_alias: str):
        pass

    def _test_s3_connection(self, config: dict, database_alias: str) -> Dict[str, Any]:
        secret_name = f"s3_{database_alias}_secret_{uuid.uuid4().hex}"
        self.add_s3_secret(
            secret_name=secret_name,
            access_key=config["access_key"],
            secret_key=config["secret_key"],
            region=config.get("region", "us-east-1"),
            endpoint=config.get("endpoint", "s3.amazonaws.com"),
            url_style=config.get("url_style", "path")
        )
        return {'status': True, 'message': 'S3连接测试成功'}

    def _test_sqlite_connection(self, config: dict, database_alias: str) -> Dict[str, Any]:
        db_path = config.get("database_path")
        if not db_path or not os.path.exists(db_path):
            return {'status': False, 'message': 'SQLite数据库路径无效或文件不存在'}

        try:
            self.register_sqlite(db_path, database_alias)
            self.conn.execute(
                "PREPARE check_sqlite_activate AS select * from duckdb_databases() where database_name=?")
            exist = self.conn.execute(f"EXECUTE check_sqlite_activate({database_alias})").fetchone()
            return {'status': True if exist else False, 'message': 'SQLite连接测试成功' if exist else '注册失败'}
        except Exception as e:
            return {'status': False, 'message': f'SQLite连接失败: {str(e)}'}

    def _test_mysql_connection(self, config: dict, database_alias) -> dict:
        database_path = f"host={config['host']} user={config['username']} port={config['port']} password={config['password']} database={config['database']}"
        self.register_mysql(database_path, database_alias)
        self.conn.execute(
            "PREPARE check_mysql_activate AS select * from duckdb_databases() where database_name=?")
        exist = self.conn.execute(f"EXECUTE check_mysql_activate('{database_alias}')").fetchone()
        if not exist:
            return {'status': False, 'message': "Failed connect mysql"}
        return {'status': True, 'message': "Successfully connected to mysql"}

    def _test_postgres_connection(self, config: dict, database_alias) -> dict:
        database_path = f"host={config['host']} user={config['username']} port={config['port']} password={config['password']} dbname={config['database']}"
        self.register_postgresql(database_path, config['database_schema'], database_alias)
        self.conn.execute("PREPARE check_pg_activate AS select * from duckdb_databases() where database_name=?")
        exist = self.conn.execute(f"EXECUTE check_pg_activate('{database_alias}')").fetchone()
        if not exist:
            return {'status': False, 'message': f"Failed connect postgres"}
        return {'status': True, 'message': f"Successfully connected postgres"}

    def _test_excel_connection(self, config: dict, database_alias: str) -> dict:
        db_path = config.get("database_path")
        has_header = config.get("has_header", True)
        ignore_errors = config.get("ignore_errors", False)
        if ".xlsx" not in db_path:
            raise ValueError(f"Only supporting extension name of Excel file is `.xlsx`")
        exist = self.conn.execute(
            f"SELECT * FROM read_xlsx('{db_path}', header={has_header}, ignore_errors={ignore_errors})").fetchone()

        if not exist:
            return {'status': False, 'message': f"Failed read excel"}
        return {'status': True, 'message': f"Successfully read excel"}

    def drop_object_safely(self, object_name):
        """安全删除数据库对象（表或视图）"""
        # 检查对象是否存在
        result = self.conn.execute(f"""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_name = '{object_name}'
        """).fetchone()

        if result and result[0] > 0:
            # 获取对象类型
            obj_type_result = self.conn.execute(f"""
                SELECT table_type
                FROM information_schema.tables
                WHERE table_name = '{object_name}'
            """).fetchone()

            if obj_type_result:
                obj_type = obj_type_result[0].lower()
                # 根据类型使用正确的DROP语句
                if obj_type == 'view':
                    self.conn.execute(f"DROP VIEW IF EXISTS {object_name}")
                    print(f"成功删除视图: {object_name}")
                elif obj_type == 'base table':
                    self.conn.execute(f"DROP TABLE IF EXISTS {object_name}")
                    print(f"成功删除表: {object_name}")
                else:
                    print(f"未知对象类型 '{obj_type}' 对于 {object_name}")
            else:
                print(f"无法确定 {object_name} 的类型")
        else:
            print(f"对象 {object_name} 不存在，无需删除")

    def cleanup(self):
        """清理临时表"""
        # 检查对象是否有效
        if not hasattr(self, '_initialized') or not self._initialized:
            return
        # 确保连接仍然存在
        if not hasattr(self, 'conn') or self.conn is None:
            return
        # 安全地清理临时表
        try:
            for table in list(self.temp_tables):
                try:
                    # self.conn.execute(f"DROP TABLE IF EXISTS {table}")
                    self.drop_object_safely(table)
                    self.temp_tables.remove(table)
                except Exception as e:
                    print(f"清理表 {table} 时出错: {str(e)}")
            print("所有临时表已清理")
        except Exception as e:
            print(f"清理过程中出错: {str(e)}")

    def __del__(self):
        # 设置标志防止重复清理
        if not hasattr(self, '_initialized') or not self._initialized:
            return
        try:
            # 标记对象为已销毁
            self._initialized = False

            # 尝试清理资源
            self.cleanup()

            # 安全地关闭连接
            if hasattr(self, 'conn') and self.conn is not None:
                try:
                    self.conn.close()
                except:
                    pass
                finally:
                    self.conn = None
        except Exception as e:
            # 忽略析构过程中的所有错误
            pass
