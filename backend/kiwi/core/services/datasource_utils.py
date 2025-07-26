from enum import Enum
from typing import Dict, Any

from kiwi.core.encryption import safe_decrypt, safe_encrypt


class DataSourceType(str, Enum):
    MYSQL = "mysql"
    POSTGRES = "postgres"
    S3 = "s3"
    SQLITE = "sqlite"
    LOCAL_FILE = "local_file"
    DUCK_DB = "duckdb"
    OTHERS = "others"


REQUIRED_FIELD_MAP = {
    DataSourceType.MYSQL: 'password',
    DataSourceType.POSTGRES: 'password',
    DataSourceType.S3: 'secret_key',
}

ENCRYPTED_FILED_MAP = {
    DataSourceType.MYSQL: 'encrypted_password',
    DataSourceType.POSTGRES: 'encrypted_password',
    DataSourceType.S3: 'encrypted_secret_key',
}


async def encrypt_connection_config(source_type: DataSourceType, config: Dict[str, Any]) -> Dict[str, Any]:
    """
        加密连接配置
        支持的数据源类型: mysql, postgres, s3, sqlite 等
        """
    config = config.copy()  # 避免修改原始配置

    if source_type in REQUIRED_FIELD_MAP:
        field_name = REQUIRED_FIELD_MAP[source_type]
        encrypted_name = ENCRYPTED_FILED_MAP[source_type]

        # 如果提供了字段，则加密
        if field_name in config:
            value = config.pop(field_name)
            if value:
                config[encrypted_name] = await safe_encrypt(value)

        # 如果既没有明文字段也没有加密字段，则报错
        if encrypted_name not in config:
            raise ValueError(f"缺少必要的连接字段: {encrypted_name}")

    # 特殊处理不同数据源的配置
    if source_type == DataSourceType.SQLITE:
        if 'path' not in config:
            raise ValueError("SQLite 数据源需要 'path' 配置")

    elif source_type == DataSourceType.S3:
        if 'secret_key' not in config:
            raise ValueError("S3 数据源需要 'secret_key' 配置")

    return config


async def decrypt_connection_config(source_type: DataSourceType, config: Dict[str, Any]) -> Dict[str, Any]:
    """
        解析并解密连接配置
        支持的数据源类型: mysql, postgres, s3, sqlite 等
        """
    config = config.copy()  # 避免修改原始配置

    if source_type in REQUIRED_FIELD_MAP:
        field_name = REQUIRED_FIELD_MAP[source_type]
        encrypted_name = ENCRYPTED_FILED_MAP[source_type]

        # 如果提供了加密字段，则解密
        if encrypted_name in config:
            encrypted_value = config.pop(encrypted_name)
            if encrypted_value:
                config[field_name] = await safe_decrypt(encrypted_value)

        # 如果既没有加密字段也没有明文字段，则报错
        if field_name not in config:
            raise ValueError(f"缺少必要的连接字段: {field_name}")

    # 特殊处理不同数据源的配置
    if source_type == DataSourceType.SQLITE:
        if 'path' not in config:
            raise ValueError("SQLite 数据源需要 'path' 配置")

    elif source_type == DataSourceType.S3:
        if 'secret_key' not in config:
            raise ValueError("S3 数据源需要 'secret_key' 配置")

    return config
