"""
Logging utility with rich console output and file logging
"""

from loguru import logger
import sys
from pathlib import Path
from config.settings import settings


# Remove default logger
logger.remove()

# Create logs directory
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# Console logging with rich formatting
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> | <level>{message}</level>",
    level=settings.log_level,
    colorize=True
)

# File logging (rotating)
logger.add(
    log_dir / "ai_job_agent_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    compression="zip"
)

# Error logging (separate file)
logger.add(
    log_dir / "errors_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="90 days",
    level="ERROR",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}\n{exception}",
    backtrace=True,
    diagnose=True
)

# Export logger
__all__ = ['logger']
