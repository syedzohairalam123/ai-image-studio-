import re
import uuid
import hashlib
from datetime import datetime, timezone

from flask import jsonify, make_response


def generate_filename(original_filename, prefix=""):
    """Generate a safe, unique filename preserving extension."""
    ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "bin"
    uid = uuid.uuid4().hex[:12]
    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]", "", prefix) + "_" if prefix else ""
    return f"{safe_prefix}{uid}.{ext}"


def safe_json_response(data, status_code=200, headers=None):
    """Create a safe JSON response with optional headers."""
    response = make_response(jsonify(data), status_code)
    if headers:
        for key, value in headers.items():
            response.headers[key] = value
    return response


def success_response(data=None, message="Success", status_code=200):
    """Standard success response."""
    payload = {"status": "success", "message": message}
    if data is not None:
        payload["data"] = data
    return safe_json_response(payload, status_code)


def error_response(message, status_code=400, details=None):
    """Standard error response."""
    payload = {"status": "error", "error": message, "status_code": status_code}
    if details:
        payload["details"] = details
    return safe_json_response(payload, status_code)


def paginate_query(query, page=1, per_page=20, max_per_page=100):
    """Paginate a SQLAlchemy query with safe defaults."""
    page = max(1, int(page))
    per_page = min(max(1, int(per_page)), max_per_page)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return {
        "items": pagination.items,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "total": pagination.total,
        "pages": pagination.pages,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev,
    }


def now_utc():
    """Get current UTC time."""
    return datetime.now(timezone.utc)


def hash_string(value):
    """SHA-256 hash a string for safe comparison."""
    return hashlib.sha256(value.encode()).hexdigest()
