import asyncio
import functools
import logging
import os
from logging.handlers import RotatingFileHandler


LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_FILE = os.path.join(LOG_DIR, "log.log")
LOG_FORMAT = "%(asctime)s %(levelname)s [%(filename)s:%(lineno)d]: %(message)s"
DATE_FORMAT = "%d-%m-%y %H:%M:%S"


def _ensure_log_dir():
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception:
        # Stream logging still works even if the file directory cannot be made.
        pass


def _has_handler(logger_obj, handler_type, filename=None):
    for handler in logger_obj.handlers:
        if not isinstance(handler, handler_type):
            continue

        if filename is None:
            return True

        handler_filename = getattr(handler, "baseFilename", None)
        if handler_filename and os.path.abspath(handler_filename) == os.path.abspath(filename):
            return True

    return False


def _build_logger():
    _ensure_log_dir()

    logger_obj = logging.getLogger("logger")
    logger_obj.setLevel(logging.INFO)
    logger_obj.propagate = False

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    if not _has_handler(logger_obj, logging.StreamHandler):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        logger_obj.addHandler(console_handler)

    if not _has_handler(logger_obj, RotatingFileHandler, LOG_FILE):
        try:
            file_handler = RotatingFileHandler(
                LOG_FILE,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            logger_obj.addHandler(file_handler)
        except Exception as exc:
            logger_obj.warning(f"Не удалось подключить файловый лог: {exc}")

    return logger_obj


logger = _build_logger()


class AsyncLogger:
    """Асинхронная обёртка над обычным logger."""

    @staticmethod
    async def info(message: str):
        logger.info(message)
        await asyncio.sleep(0)

    @staticmethod
    async def debug(message: str):
        logger.debug(message)
        await asyncio.sleep(0)

    @staticmethod
    async def warning(message: str):
        logger.warning(message)
        await asyncio.sleep(0)

    @staticmethod
    async def error(message: str):
        logger.error(message)
        await asyncio.sleep(0)

    @staticmethod
    async def critical(message: str):
        logger.critical(message)
        await asyncio.sleep(0)

    @staticmethod
    async def exception(message: str):
        logger.exception(message)
        await asyncio.sleep(0)

    @staticmethod
    async def log(level: int, message: str):
        logger.log(level, message)
        await asyncio.sleep(0)


class LoggerContext:
    """Асинхронный контекстный менеджер для логирования блока кода."""

    def __init__(self, name: str):
        self.name = name

    async def __aenter__(self):
        await AsyncLogger.debug(f"Вход в контекст: {self.name}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await AsyncLogger.error(f"Ошибка в контексте {self.name}: {exc_val}")
        else:
            await AsyncLogger.debug(f"Выход из контекста: {self.name}")
        return False


def log_async(log_level=logging.INFO):
    """Декоратор для логирования асинхронных функций."""

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            func_name = func.__name__
            try:
                logger.log(log_level, f"Запуск: {func_name}")
                result = await func(*args, **kwargs)
                logger.log(log_level, f"Завершено: {func_name}")
                return result
            except Exception as exc:
                logger.exception(f"Ошибка в {func_name}: {exc}")
                raise

        return wrapper

    return decorator


async def setup(bot):
    logger.info("Logger загружен")
