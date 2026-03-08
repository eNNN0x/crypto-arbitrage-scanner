"""
Logging Setup
=============
Configures structured logging to both console (colored) and file.
"""

import logging
import sys
from pathlib import Path


# ANSI colour codes for terminal
COLOURS = {
    "DEBUG":    "\033[36m",   # Cyan
    "INFO":     "\033[32m",   # Green
    "WARNING":  "\033[33m",   # Yellow
    "ERROR":    "\033[31m",   # Red
    "CRITICAL": "\033[35m",   # Magenta
    "RESET":    "\033[0m",
}


class ColouredFormatter(logging.Formatter):
    """Log formatter that adds colour to terminal output."""

    FMT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
    DATEFMT = "%Y-%m-%d %H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        colour = COLOURS.get(record.levelname, COLOURS["RESET"])
        reset = COLOURS["RESET"]
        record.levelname = f"{colour}{record.levelname}{reset}"
        formatter = logging.Formatter(self.FMT, datefmt=self.DATEFMT)
        return formatter.format(record)


class PlainFormatter(logging.Formatter):
    FMT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
    DATEFMT = "%Y-%m-%d %H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        formatter = logging.Formatter(self.FMT, datefmt=self.DATEFMT)
        return formatter.format(record)


def setup_logger(
    name: str = "scanner",
    level: int = logging.INFO,
    log_file: str = "logs/scanner.log",
) -> logging.Logger:
    """
    Create and return a configured logger.
    
    Args:
        name:     Logger name
        level:    Logging level (default INFO)
        log_file: Path to log file (rotated daily)
    
    Returns:
        Configured Logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger  # Already configured

    # Console handler with colour
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(ColouredFormatter())
    console.setLevel(level)
    logger.addHandler(console)

    # File handler
    if log_file:
        from logging.handlers import RotatingFileHandler
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=7,
            encoding="utf-8",
        )
        file_handler.setFormatter(PlainFormatter())
        file_handler.setLevel(level)
        logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    return logger
