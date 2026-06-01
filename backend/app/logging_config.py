"""
Logging configuration for OctoFinance
Logs to both console and rotating files
"""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime

from .config import config


def setup_logging():
    """Setup logging with console and file handlers."""

    # Create logs directory
    log_dir = config.data_dir / "logs"
    log_dir.mkdir(exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler (INFO level)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler - General application log (rotating)
    app_log_file = log_dir / "octofinance.log"
    app_file_handler = RotatingFileHandler(
        app_log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    app_file_handler.setLevel(logging.INFO)
    app_file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    app_file_handler.setFormatter(app_file_formatter)
    root_logger.addHandler(app_file_handler)

    # File handler - API requests log (rotating, DEBUG level)
    api_log_file = log_dir / "api_requests.log"
    api_file_handler = RotatingFileHandler(
        api_log_file,
        maxBytes=50 * 1024 * 1024,  # 50MB
        backupCount=10,
        encoding='utf-8'
    )
    api_file_handler.setLevel(logging.DEBUG)
    api_file_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    api_file_handler.setFormatter(api_file_formatter)

    # Add API handler to github_api logger
    api_logger = logging.getLogger('app.services.github_api')
    api_logger.addHandler(api_file_handler)
    api_logger.setLevel(logging.DEBUG)

    # Also add to budget_tools logger
    budget_logger = logging.getLogger('app.tools.budget_tools')
    budget_logger.addHandler(api_file_handler)
    budget_logger.setLevel(logging.DEBUG)

    logging.info(f"Logging initialized. Logs directory: {log_dir}")
    logging.info(f"Application log: {app_log_file}")
    logging.info(f"API requests log: {api_log_file}")


def get_api_logger():
    """Get the API logger for detailed API request logging."""
    return logging.getLogger('app.services.github_api')
