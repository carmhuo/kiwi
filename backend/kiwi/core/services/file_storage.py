import os
import aiofiles
from typing import Union
from fastapi import UploadFile
import uuid
from kiwi.core.config import settings


class FileStorage:
    """
    文件存储服务，处理文件上传和下载
    """

    def __init__(self):
        self.storage_path = settings.STORAGE_PATH

    async def upload_file(self, file_path: str, file_data: Union[bytes, UploadFile]):
        """
        上传文件到存储
        """
        full_path = os.path.join(self.storage_path, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        if isinstance(file_data, UploadFile):
            async with aiofiles.open(full_path, 'wb') as f:
                await f.write(await file_data.read())
        else:
            async with aiofiles.open(full_path, 'wb') as f:
                await f.write(file_data)

    async def download_file(self, file_path: str) -> bytes:
        """
        下载文件
        """
        full_path = os.path.join(self.storage_path, file_path)
        async with aiofiles.open(full_path, 'rb') as f:
            return await f.read()

    async def delete_file(self, file_path: str):
        """
        删除文件
        """
        full_path = os.path.join(self.storage_path, file_path)
        try:
            os.remove(full_path)
        except FileNotFoundError:
            pass

    def get_file_url(self, file_path: str) -> str:
        """
        获取文件访问URL
        """
        return f"{settings.FILE_SERVER_URL}/{file_path}"