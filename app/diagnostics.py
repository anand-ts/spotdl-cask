"""Runtime diagnostics, logging, and exception handling helpers."""

from __future__ import annotations

import faulthandler
import logging
import sys
import threading

LOGGER = logging.getLogger(__name__)


class _SpotipyRateLimitFilter(logging.Filter):
    """Drop expected spotipy 429 noise that we already handle gracefully."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "spotipy.client":
            return True

        message = record.getMessage().lower()
        if "returned 429" in message or "too many requests" in message:
            return False
        if "max retries reached" in message:
            return False

        return True


def _configure_logging() -> None:
    """Send application logs and tracebacks straight to the terminal."""
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(stdout_reconfigure):
        stdout_reconfigure(line_buffering=True)

    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if callable(stderr_reconfigure):
        stderr_reconfigure(line_buffering=True)

    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.setLevel(logging.INFO)
        for handler in root_logger.handlers:
            handler.setLevel(logging.INFO)
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )

    rate_limit_filter = _SpotipyRateLimitFilter()
    for handler in root_logger.handlers:
        handler.addFilter(rate_limit_filter)

    logging.captureWarnings(True)


def _install_exception_logging() -> None:
    """Log uncaught exceptions from the main thread and worker threads."""

    def _log_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        LOGGER.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    def _log_thread_exception(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, KeyboardInterrupt):
            return

        thread_name = args.thread.name if args.thread else "unknown"
        exc_info = None
        if args.exc_value is not None:
            exc_info = (args.exc_type, args.exc_value, args.exc_traceback)
        LOGGER.critical(
            "Unhandled exception in thread %s",
            thread_name,
            exc_info=exc_info,
        )

    sys.excepthook = _log_uncaught_exception
    threading.excepthook = _log_thread_exception


def _enable_terminal_diagnostics() -> None:
    """Enable line-buffered logging and Python fault dumps."""
    _configure_logging()
    _install_exception_logging()
    try:
        faulthandler.enable(all_threads=True)
    except (AttributeError, RuntimeError):
        LOGGER.debug("faulthandler could not be enabled", exc_info=True)
