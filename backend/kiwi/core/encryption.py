import base64
from typing import Optional

from cryptography.fernet import Fernet
from fastapi.concurrency import run_in_threadpool

from kiwi.core.config import settings
from kiwi.core.config import logger


# 数据加密与解密

def generate_key():
    """生成加密密钥"""
    return Fernet.generate_key()


_cipher_suite = None


def get_cipher_suite():
    """获取加密套件"""
    global _cipher_suite
    if _cipher_suite is None:
        # 从配置获取密钥，如果没有则生成
        if not hasattr(settings, 'SECRET_KEY') or not settings.SECRET_KEY:
            key = generate_key()
            settings.SECRET_KEY = key.decode()
        else:
            key = settings.SECRET_KEY.encode()
        _cipher_suite = Fernet(key)
    return _cipher_suite


def encrypt_data(data: str) -> str:
    """加密数据"""
    if not data:
        return data

    cipher_suite = get_cipher_suite()
    encrypted = cipher_suite.encrypt(data.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_data(encrypted_data: Optional[str]) -> str:
    """解密数据"""
    if not encrypted_data:
        return encrypted_data

    cipher_suite = get_cipher_suite()
    decoded = base64.urlsafe_b64decode(encrypted_data.encode())
    return cipher_suite.decrypt(decoded).decode()


async def aencrypt_data(data: str) -> str:
    return await run_in_threadpool(encrypt_data, data)


async def adecrypt_data(encrypted_data: Optional[str]) -> str:
    return await run_in_threadpool(decrypt_data, encrypted_data)


# 异步接口
async def safe_encrypt(data: str) -> str:
    """异步安全加密数据"""
    try:
        return await run_in_threadpool(encrypt_data, data)
    except Exception as e:
        await logger.aerror(f"Encryption failed", extra={"error": str(e)})
        raise ValueError("Data encryption error") from e


async def safe_decrypt(encrypted_data: Optional[str]) -> str:
    """异步安全解密数据"""
    try:
        return await run_in_threadpool(decrypt_data, encrypted_data)
    except Exception as e:
        await logger.aerror(f"Decryption failed", extra={"error": str(e)})
        raise ValueError("Data decryption error") from e
