import base64
from cryptography.fernet import Fernet

from kiwi.core.config import settings


# 数据加密与解密

def generate_key():
    """生成加密密钥"""
    return Fernet.generate_key()


def get_cipher_suite():
    """获取加密套件"""
    # 从配置获取密钥，如果没有则生成
    if not hasattr(settings, 'SECRET_KEY') or not settings.SECRET_KEY:
        key = generate_key()
        settings.SECRET_KEY = key.decode()
    else:
        key = settings.SECRET_KEY.encode()
    return Fernet(key)


def encrypt_data(data: str) -> str:
    """加密数据"""
    if not data:
        return data

    cipher_suite = get_cipher_suite()
    encrypted = cipher_suite.encrypt(data.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_data(encrypted_data: str) -> str:
    """解密数据"""
    if not encrypted_data:
        return encrypted_data

    cipher_suite = get_cipher_suite()
    decoded = base64.urlsafe_b64decode(encrypted_data.encode())
    return cipher_suite.decrypt(decoded).decode()
