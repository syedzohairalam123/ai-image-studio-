import os
import time
import secrets
from collections import defaultdict
from pathlib import Path

from flask import Flask, g, request, jsonify, current_app

from app.config import get_config
from app.extensions import db, login_manager, migrate
from app.errors import register_error_handlers
from app.logging import setup_logging


# ============================================================
# SIMPLE IN-MEMORY RATE LIMITER
# ============================================================

class _RateLimiter:
    """Simple sliding-window rate limiter.  Good enough for single-worker
    dev / small deployments.  For multi-worker production, swap with
    Redis-backed limiter."""

    def __init__(self):
        self._windows: dict[str, list[float]] = defaultdict(list)

    def is_limited(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """Return True if the key has exceeded the limit."""
        now = time.time()
        cutoff = now - window_seconds
        # Prune old entries
        self._windows[key] = [t for t in self._windows[key] if t > cutoff]
        if len(self._windows[key]) >= max_requests:
            return True
        self._windows[key].append(now)
        return False


_limiter = _RateLimiter()

# Endpoint-specific limits: (max_requests, window_seconds)
RATE_LIMITS = {
    "/api/v1/generate":        (10, 60),    # 10 generations / minute
    "/api/v1/images":          (60, 60),    # image reads are lighter
    "/api/v1/prompts/enhance": (15, 60),    # prompt enhancement
    "/api/v1/utilities/upscale":     (5, 60),
    "/api/v1/utilities/remove-background": (5, 60),
    "/api/v1/utilities/describe":    (10, 60),
    "/api/v1/images/*/variations":   (5, 60),
    "/api/v1/explore/*/like":       (20, 60),
    "/api/v1/explore/*/report":     (5, 300),  # 5 reports / 5 min
}


def _check_rate_limit():
    """before_request hook — enforce rate limits on write-heavy endpoints."""
    if current_app.config.get("TESTING"):
        # Rate limiting is real production behavior, but the in-memory
        # limiter is a process-wide singleton — without this bypass a large
        # test session shares one rolling window across hundreds of tests
        # and starts returning genuine 429s partway through, which then
        # cascades into unrelated failures in any test whose fixtures rely
        # on an earlier call (e.g. generate) having actually succeeded.
        return

    path = request.path
    # Match exact path or prefix patterns with wildcard segments
    for pattern, (max_req, window) in RATE_LIMITS.items():
        # Convert wildcard patterns for matching
        if "*" in pattern:
            # Check if the path matches the pattern structure
            pattern_parts = pattern.split("/")
            path_parts = path.split("/")
            if len(pattern_parts) == len(path_parts):
                match = True
                for pp, rp in zip(path_parts, pattern_parts):
                    if rp != "*" and pp != rp:
                        match = False
                        break
                if match:
                    break
        elif path == pattern or path.startswith(pattern + "/"):
            break
    else:
        return  # No matching rate limit

    client_ip = request.remote_addr or "unknown"
    user_id = getattr(g, "_user_id_for_rl", None)
    key = f"rl:{path}:{user_id or client_ip}"

    if _limiter.is_limited(key, max_req, window):
        retry_after = window - int(time.time() - _limiter._windows[key][0]) if _limiter._windows[key] else window
        resp = jsonify({
            "error": "Rate limit exceeded. Please try again later.",
            "status_code": 429,
            "retry_after": max(1, retry_after),
        })
        resp.status_code = 429
        resp.headers["Retry-After"] = str(max(1, retry_after))
        return resp


def create_app(config_class=None):
    """Create and configure the Flask application."""

    flask_app = Flask(__name__)

    # Load configuration
    if config_class:
        flask_app.config.from_object(config_class)
    else:
        flask_app.config.from_object(get_config())

    # Ensure upload directory exists
    upload_dir = Path(flask_app.config.get("UPLOAD_FOLDER", "uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Initialize extensions
    db.init_app(flask_app)
    migrate.init_app(flask_app, db)
    login_manager.init_app(flask_app)
    login_manager.login_view = "main.login"
    login_manager.login_message_category = "error"
    flask_app.config["SESSION_COOKIE_HTTPONLY"] = True
    flask_app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Import models so they are known to SQLAlchemy
    with flask_app.app_context():
        import app.models  # noqa: F401
        # On Vercel (serverless), migrations can't run — auto-create all
        # tables so the app boots cleanly on every cold start.
        if os.environ.get("VERCEL"):
            db.create_all()

    # Register error handlers
    register_error_handlers(flask_app)

    # Setup logging
    setup_logging(flask_app)

    # Register routes
    from app.routes import register_routes
    register_routes(flask_app)

    # ── SECURITY: Rate limiting ──
    flask_app.before_request(_check_rate_limit)

    # ── SECURITY: Track user for rate limiter ──
    @flask_app.before_request
    def _set_user_for_rl():
        try:
            from flask_login import current_user
            if current_user.is_authenticated:
                g._user_id_for_rl = str(current_user.id)
        except Exception:
            pass

    # ── SECURITY: HTTP security headers ──
    @flask_app.after_request
    def _add_security_headers(response):
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        # XSS protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Referrer policy — don't leak paths to third parties
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Permissions policy — disable camera, microphone, geolocation
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # Content Security Policy — restrictive default
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        # HSTS — only over HTTPS (enable in production)
        if not flask_app.debug:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Remove server header
        response.headers.pop("Server", None)
        # Remove X-Powered-By
        response.headers.pop("X-Powered-By", None)
        return response

    return flask_app
