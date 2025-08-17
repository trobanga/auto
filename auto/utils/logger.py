"""Logging utilities for the auto tool."""

import logging
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler


class AutoLogger:
    """Custom logger with rich formatting."""
    
    _handlers_setup = False  # Class variable to track if handlers are set up
    
    def __init__(self, name: str = "auto", level: str = "INFO"):
        """Initialize logger with rich formatting.
        
        Args:
            name: Logger name
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.upper()))
        
        # Only set up handlers on the root "auto" logger once
        if not AutoLogger._handlers_setup:
            root_logger = logging.getLogger("auto")
            if not root_logger.handlers:
                self._setup_handlers(root_logger)
                AutoLogger._handlers_setup = True
        
        # For child loggers, prevent propagation duplication by not adding handlers
        if name != "auto" and not self.logger.handlers:
            # Child loggers will propagate to the root "auto" logger
            self.logger.propagate = True
    
    def _setup_handlers(self, logger: logging.Logger) -> None:
        """Setup console and file handlers."""
        console = Console()
        
        # Rich console handler
        console_handler = RichHandler(
            console=console,
            show_time=True,
            show_path=False,
            rich_tracebacks=True,
            tracebacks_show_locals=True,
        )
        console_handler.setLevel(logging.INFO)
        
        # File handler for debug logs
        log_dir = Path.home() / ".auto" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_dir / "auto.log")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
    
    def debug(self, message: str, **kwargs) -> None:
        """Log debug message."""
        self.logger.debug(message, **kwargs)
    
    def info(self, message: str, **kwargs) -> None:
        """Log info message."""
        self.logger.info(message, **kwargs)
    
    def warning(self, message: str, **kwargs) -> None:
        """Log warning message."""
        self.logger.warning(message, **kwargs)
    
    def error(self, message: str, **kwargs) -> None:
        """Log error message."""
        self.logger.error(message, **kwargs)
    
    def critical(self, message: str, **kwargs) -> None:
        """Log critical message."""
        self.logger.critical(message, **kwargs)
    
    def exception(self, message: str, **kwargs) -> None:
        """Log exception with traceback."""
        self.logger.exception(message, **kwargs)


# Global logger instance
logger = AutoLogger()


def get_logger(name: Optional[str] = None, level: str = "INFO") -> AutoLogger:
    """Get logger instance.
    
    Args:
        name: Logger name (defaults to 'auto')
        level: Log level
        
    Returns:
        Logger instance
    """
    if name is None:
        return logger
    return AutoLogger(name, level)