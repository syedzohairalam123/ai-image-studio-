import logging
import time
import uuid

from flask import g, request


class RequestFilter(logging.Filter):
    """Inject request context into log records."""

    def filter(self, record):
        record.request_id = getattr(g, "request_id", "no-request")
        record.remote_addr = request.remote_addr if request else "N/A"
        record.method = request.method if request else "N/A"
        record.url = request.url if request else "N/A"
        return True


def setup_logging(the_app):
    """Configure structured application logging."""

    log_level = getattr(logging, the_app.config.get("LOG_LEVEL", "INFO").upper(), logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(request_id)s] %(remote_addr)s %(method)s %(url)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(RequestFilter())

    the_app.logger.handlers.clear()
    the_app.logger.addHandler(console_handler)
    the_app.logger.setLevel(log_level)

    # Suppress noisy third-party loggers
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    def _assign_request_id():
        g.request_id = str(uuid.uuid4())[:8]
        g.start_time = time.time()

    def _log_request(response):
        duration = time.time() - getattr(g, "start_time", time.time())
        user_id = getattr(g, "user_id", "anonymous") if hasattr(g, "user_id") else "anonymous"
        the_app.logger.info(
            "Completed %s %s -> %s (%.3fs, user=%s)",
            request.method,
            request.path,
            response.status_code,
            duration,
            user_id,
        )
        response.headers["X-Request-Id"] = getattr(g, "request_id", "")
        return response

    the_app.before_request(_assign_request_id)
    the_app.after_request(_log_request)
