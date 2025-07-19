import logging
import sys
import os
import json
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Any, Dict, Optional, Union
from datetime import datetime
from fastapi.concurrency import run_in_threadpool


class Logger:
    """
    通用日志记录器类，支持同步和异步日志记录

    特性：
    - 多日志级别支持（DEBUG, INFO, WARNING, ERROR, CRITICAL）
    - 多输出目标（控制台、文件、HTTP 端点等）
    - 结构化日志（JSON 格式）
    - 异步安全记录
    - 日志轮转和归档
    - 自定义日志字段
    """

    def __init__(
            self,
            name: str = "app",
            level: Union[str, int] = "INFO",
            log_to_console: bool = True,
            log_to_file: bool = False,
            log_file_path: str = "logs/app.log",
            max_file_size: int = 10 * 1024 * 1024,  # 10MB
            log_rotation: str = None,
            backup_count: int = 7,
            log_format: str = "json",  # 支持 "text" 或 "json"
            enable_async: bool = True,
            extra_fields: Optional[Dict[str, Any]] = None
    ):
        """
        初始化日志记录器

        :param name: 日志记录器名称
        :param level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        :param log_to_console: 是否输出到控制台
        :param log_to_file: 是否输出到文件
        :param log_file_path: 日志文件路径
        :param max_file_size: 日志文件最大大小（字节）
        :param backup_count: 保留的备份文件数量
        :param log_format: 日志格式 ("text" 或 "json")
        :param enable_async: 是否启用异步日志记录
        :param extra_fields: 额外的固定日志字段
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.logger.propagate = False  # 防止日志传播到根记录器

        self.name = name
        self.level = level.upper() if isinstance(level, str) else level
        self.log_format = log_format
        self.enable_async = enable_async
        self.extra_fields = extra_fields or {}

        # 确保日志目录存在
        if log_to_file:
            log_dir = os.path.dirname(log_file_path)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)

        # 创建处理器
        self.handlers = []

        # 控制台处理器
        if log_to_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(self.level)
            console_handler.setFormatter(self._get_formatter())
            self.handlers.append(console_handler)

        # 文件处理器（带轮转）
        if log_to_file:
            if log_rotation:
                # 按时间轮转
                file_handler = TimedRotatingFileHandler(
                    log_file_path,
                    when=log_rotation,
                    backupCount=backup_count,
                    utc=True
                )
            else:
                # 按大小轮转
                file_handler = RotatingFileHandler(
                    log_file_path,
                    maxBytes=max_file_size,
                    backupCount=backup_count
                )
            file_handler.setLevel(self.level)
            file_handler.setFormatter(self._get_formatter())
            self.handlers.append(file_handler)

        # 添加处理器到记录器
        for handler in self.handlers:
            self.logger.addHandler(handler)

    def _get_formatter(self) -> logging.Formatter:
        """获取日志格式化器"""
        if self.log_format == "json":
            return logging.Formatter('%(message)s')
        else:
            return logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )

    def _build_log_record(
            self,
            level: str,
            message: str,
            extra: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """构建日志记录字典"""
        log_record = {
            "_timestamp": datetime.now().isoformat() + "Z",
            "_level": level.upper(),
            "_logger": self.name,
            "_message": message,
            **self.extra_fields
        }

        if extra:
            # 确保 extra 中的键不会覆盖基本字段
            for key, value in extra.items():
                if key not in log_record:
                    log_record[key] = value

        return log_record

    def _log_sync(self, level: str, message: str, extra: Optional[Dict[str, Any]] = None):
        """同步日志记录方法"""
        log_record = self._build_log_record(level, message, extra)

        if self.log_format == "json":
            log_message = json.dumps(log_record)
        else:
            log_message = f"{log_record['_timestamp']} [{log_record['_level']}] {message}"
            if extra:
                log_message += f" | {json.dumps(extra)}"

        # 使用标准 logging 方法记录
        log_level = getattr(logging, level.upper())
        self.logger.log(log_level, log_message, extra=log_record)

    async def _log_async(self, level: str, message: str, extra: Optional[Dict[str, Any]] = None):
        """异步日志记录方法"""
        await run_in_threadpool(self._log_sync, level, message, extra)

    def log(self, level: str, message: str, extra: Optional[Dict[str, Any]] = None):
        """通用日志记录方法（自动选择同步/异步）"""
        if self.enable_async:
            return self._log_async(level, message, extra)
        else:
            return self._log_sync(level, message, extra)

    # 便捷方法
    def debug(self, message: str, extra: Optional[Dict[str, Any]] = None):
        self.log("DEBUG", message, extra)

    def info(self, message: str, extra: Optional[Dict[str, Any]] = None):
        self.log("INFO", message, extra)

    def warning(self, message: str, extra: Optional[Dict[str, Any]] = None):
        self.log("WARNING", message, extra)

    def error(self, message: str, extra: Optional[Dict[str, Any]] = None):
        self.log("ERROR", message, extra)

    def critical(self, message: str, extra: Optional[Dict[str, Any]] = None):
        self.log("CRITICAL", message, extra)

    # 异步便捷方法
    async def adebug(self, message: str, extra: Optional[Dict[str, Any]] = None):
        await self._log_async("DEBUG", message, extra)

    async def ainfo(self, message: str, extra: Optional[Dict[str, Any]] = None):
        await self._log_async("INFO", message, extra)

    async def awarning(self, message: str, extra: Optional[Dict[str, Any]] = None):
        await self._log_async("WARNING", message, extra)

    async def aerror(self, message: str, extra: Optional[Dict[str, Any]] = None):
        await self._log_async("ERROR", message, extra)

    async def acritical(self, message: str, extra: Optional[Dict[str, Any]] = None):
        await self._log_async("CRITICAL", message, extra)

    def add_handler(self, handler: logging.Handler):
        """添加自定义日志处理器"""
        handler.setFormatter(self._get_formatter())
        self.logger.addHandler(handler)
        self.handlers.append(handler)

    def remove_handler(self, handler: logging.Handler):
        """移除日志处理器"""
        if handler in self.handlers:
            self.logger.removeHandler(handler)
            self.handlers.remove(handler)

    def update_extra_fields(self, new_fields: Dict[str, Any]):
        """更新额外的固定日志字段"""
        self.extra_fields.update(new_fields)

    def set_level(self, level: Union[str, int]):
        """设置日志级别"""
        self.logger.setLevel(level)
        for handler in self.handlers:
            handler.setLevel(level)