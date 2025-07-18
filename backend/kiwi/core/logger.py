import logging
import traceback
import os

# 创建日志目录（如果不存在）
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    配置一个日志记录器。

    参数:
        name (str): 日志记录器的名称。
        level (int): 日志级别，默认为 INFO。

    返回:
        logging.Logger: 配置好的日志记录器。
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重复添加 handler
    if not logger.handlers:
        # 文件 handler
        file_handler = logging.FileHandler(os.path.join(LOG_DIR, f"{name}.log"))
        file_handler.setLevel(level)

        # 控制台 handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)

        # 设置日志格式
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s (line: %(lineno)d)"
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # 添加 handler 到 logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


def log_exception(logger: logging.Logger, message: str = "An exception occurred"):
    """
    记录异常的详细堆栈信息。

    参数:
        logger (logging.Logger): 使用的日志记录器。
        message (str): 自定义的错误消息。
    """
    logger.error(f"{message}\n{traceback.format_exc()}")


class LoggerMixin:
    """
    LoggerMixin 提供统一的日志记录功能，可以被其他类继承。
    """

    def __init__(self, logger_name: str = None):
        """
        初始化日志记录器。
        :param logger_name: 日志记录器名称，默认为类名。
        """
        name = logger_name or self.__class__.__name__
        self.logger = setup_logger(name)

    def log_info(self, message: str):
        """
        记录操作关键信息。
        """
        self.logger.info(f"{message}\n{traceback.format_exc()}")

    def log_warning(self, message: str):
        """
        记录异常堆栈信息。
        """
        self.logger.warning(f"{message}\n{traceback.format_exc()}")

    def log_error(self, message: str = "An exception occurred"):
        """
        记录异常堆栈信息。
        """
        self.logger.error(f"{message}\n{traceback.format_exc()}")


