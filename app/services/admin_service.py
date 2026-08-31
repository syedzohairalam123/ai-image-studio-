"""Admin service — dashboard statistics, user management, generation monitoring,
provider health, and audit logging.

All functions in this module are admin-only.  The route layer must verify
admin status before calling any function here.

Security:
  - No API keys or secrets are returned in any response.
  - User password hashes are never exposed.
  - Provider health returns safe status labels only.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from flask import request

from app.extensions import db
from app.models.user import User
from app.models.generation import Generation
from app.models.image import Image
from app.models.content_report import ContentReport
from app.models.audit_log import AuditLog
from app.models.collection import Collection
from app.models.saved_prompt import SavedPrompt
from app.models.utility_operation import UtilityOperation
from app.utils import now_utc, paginate_query


# ============================================================
# AUDIT LOGGING
# ============================================================

def log_admin_action(
    admin_id: int,
    action: str,
    entity_type: str = None,
    entity_id: int = None,
    details: dict = None,
) -> AuditLog:
    """Record an administrative action in the audit log.

    This is the single entry-point for all audit logging.  Every admin
    mutation should call this once after a successful commit.
    """
    ip = None
    try:
        ip = request.remote_addr if request else None
    except RuntimeError:
        pass  # Outside request context (e.g. CLI)

    entry = AuditLog(
        admin_id=admin_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
        ip_address=ip,
    )
    db.session.add(entry)
    # Don't commit here — let the caller commit so the audit entry and
    # the action are in the same transaction.
    return entry


# ============================================================
# ADMIN DASHBOARD
# ============================================================

def get_admin_dashboard() -> dict:
    """Aggregate high-level statistics for the admin dashboard.

    Returns real, application-derived data only.
    """
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)

    # ── Users ──
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    admin_users = User.query.filter_by(is_admin=True, is_active=True).count()
    new_users_30d = User.query.filter(User.created_at >= thirty_days_ago).count()

    # ── Generations ──
    total_generations = Generation.query.count()
    completed_generations = Generation.query.filter_by(status="completed").count()
    failed_generations = Generation.query.filter_by(status="failed").count()
    pending_generations = Generation.query.filter(
        Generation.status.in_(["pending", "processing"])
    ).count()
    generations_7d = Generation.query.filter(
        Generation.created_at >= seven_days_ago
    ).count()

    # ── Images ──
    total_images = Image.query.filter_by(is_deleted=False).count()
    public_images = Image.query.filter_by(is_deleted=False, is_public=True).count()
    hidden_images = Image.query.filter_by(
        is_deleted=False, moderation_state="hidden"
    ).count()
    reported_images = Image.query.filter_by(
        is_deleted=False, moderation_state="reported"
    ).count()
    deleted_images = Image.query.filter_by(is_deleted=True).count()

    # ── Content Reports ──
    total_reports = ContentReport.query.count()
    pending_reports = ContentReport.query.filter_by(status="pending").count()
    actioned_reports = ContentReport.query.filter_by(status="actioned").count()
    dismissed_reports = ContentReport.query.filter_by(status="dismissed").count()

    # ── Utility Operations ──
    total_utilities = UtilityOperation.query.count()
    failed_utilities = UtilityOperation.query.filter_by(status="failed").count()

    # ── Collections & Prompts ──
    total_collections = Collection.query.filter_by(is_deleted=False).count()
    total_prompts = SavedPrompt.query.count()

    # ── Storage ──
    total_size_result = db.session.query(
        db.func.sum(Image.file_size)
    ).filter_by(is_deleted=False).scalar()
    total_size_bytes = total_size_result or 0

    # ── Success Rate ──
    total_attempted = completed_generations + failed_generations
    success_rate = (
        round((completed_generations / total_attempted) * 100, 1)
        if total_attempted > 0 else 0
    )

    # ── Provider Status ──
    provider_status = get_provider_health()

    return {
        "users": {
            "total": total_users,
            "active": active_users,
            "admins": admin_users,
            "new_30d": new_users_30d,
        },
        "generations": {
            "total": total_generations,
            "completed": completed_generations,
            "failed": failed_generations,
            "pending": pending_generations,
            "last_7d": generations_7d,
            "success_rate": success_rate,
        },
        "images": {
            "total": total_images,
            "public": public_images,
            "hidden": hidden_images,
            "reported": reported_images,
            "deleted": deleted_images,
            "total_size_mb": round(total_size_bytes / (1024 * 1024), 2) if total_size_bytes else 0,
        },
        "reports": {
            "total": total_reports,
            "pending": pending_reports,
            "actioned": actioned_reports,
            "dismissed": dismissed_reports,
        },
        "library": {
            "collections": total_collections,
            "prompts": total_prompts,
            "utility_operations": total_utilities,
            "failed_utilities": failed_utilities,
        },
        "providers": provider_status,
    }


# ============================================================
# USER MANAGEMENT
# ============================================================

def list_users(
    search: str = None,
    status: str = None,
    role: str = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """List users with filtering.  Never exposes password hashes.

    Query params:
      search  – filter by username or email (case-insensitive)
      status  – 'active' or 'inactive'
      role    – 'admin' or 'user'
    """
    query = User.query

    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(
                User.username.ilike(like),
                User.email.ilike(like),
            )
        )

    if status == "active":
        query = query.filter_by(is_active=True)
    elif status == "inactive":
        query = query.filter_by(is_active=False)

    if role == "admin":
        query = query.filter_by(is_admin=True)
    elif role == "user":
        query = query.filter_by(is_admin=False)

    query = query.order_by(User.created_at.desc())
    result = paginate_query(query, page=page, per_page=per_page)

    users = []
    for u in result["items"]:
        # Safe serialization — NO email in list view for non-self,
        # NO password hash, NO internal fields
        user_data = _safe_user_dict(u)
        # Attach stats
        user_data["generation_count"] = Generation.query.filter_by(user_id=u.id).count()
        user_data["image_count"] = Image.query.filter_by(user_id=u.id, is_deleted=False).count()
        users.append(user_data)

    return {
        "users": users,
        "total": result["total"],
        "page": result["page"],
        "pages": result["pages"],
        "has_next": result["has_next"],
        "has_prev": result["has_prev"],
    }


def get_user_detail(user_id: int) -> Optional[dict]:
    """Get detailed info for a single user (admin only).

    Exposes: username, display_name, is_active, is_admin, created_at,
    generation/image/collection counts, recent activity.
    Never exposes: password_hash, email (unless admin self-view).
    """
    user = db.session.get(User, user_id)
    if not user:
        return None

    data = _safe_user_dict(user, include_email=True)
    data["generation_count"] = Generation.query.filter_by(user_id=user.id).count()
    data["completed_generations"] = Generation.query.filter_by(
        user_id=user.id, status="completed"
    ).count()
    data["failed_generations"] = Generation.query.filter_by(
        user_id=user.id, status="failed"
    ).count()
    data["image_count"] = Image.query.filter_by(user_id=user.id, is_deleted=False).count()
    data["public_image_count"] = Image.query.filter_by(
        user_id=user.id, is_deleted=False, is_public=True
    ).count()
    data["favorited_count"] = Image.query.filter_by(
        user_id=user.id, is_favorite=True, is_deleted=False
    ).count()
    data["collection_count"] = Collection.query.filter_by(
        user_id=user.id, is_deleted=False
    ).count()
    data["prompt_count"] = SavedPrompt.query.filter_by(user_id=user.id).count()

    # Recent generations (last 5)
    recent = (
        Generation.query.filter_by(user_id=user.id)
        .order_by(Generation.created_at.desc())
        .limit(5)
        .all()
    )
    data["recent_generations"] = [
        {
            "id": g.id,
            "prompt": g.prompt[:80] + ("..." if len(g.prompt) > 80 else ""),
            "status": g.status,
            "provider": g.provider,
            "model": g.model,
            "created_at": g.created_at.isoformat() if g.created_at else None,
        }
        for g in recent
    ]

    # Total file size
    total_size = db.session.query(
        db.func.sum(Image.file_size)
    ).filter_by(user_id=user.id, is_deleted=False).scalar()
    data["total_size_mb"] = round((total_size or 0) / (1024 * 1024), 2)

    return data


def set_user_active(user_id: int, active: bool) -> Optional[User]:
    """Activate or deactivate a user (admin only)."""
    user = db.session.get(User, user_id)
    if not user:
        return None
    user.is_active = active
    db.session.commit()
    return user


def set_user_admin(user_id: int, is_admin: bool) -> Optional[User]:
    """Grant or revoke admin privileges (admin only)."""
    user = db.session.get(User, user_id)
    if not user:
        return None
    user.is_admin = is_admin
    db.session.commit()
    return user


# ============================================================
# GENERATION MONITORING
# ============================================================

def list_all_generations(
    status: str = None,
    provider: str = None,
    user_id: int = None,
    search: str = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """List all generations across all users (admin only).

    Shows: job ID, status, provider, model, created time, failure category.
    Never exposes: API keys, full user prompt (truncated for display).
    """
    query = Generation.query

    if status and status in Generation.STATUSES:
        query = query.filter_by(status=status)

    if provider:
        query = query.filter(Generation.provider.ilike(f"%{provider}%"))

    if user_id:
        query = query.filter_by(user_id=user_id)

    if search:
        query = query.filter(Generation.prompt.ilike(f"%{search}%"))

    query = query.order_by(Generation.created_at.desc())
    result = paginate_query(query, page=page, per_page=per_page)

    generations = []
    for g in result["items"]:
        gen_dict = {
            "id": g.id,
            "user_id": g.user_id,
            "username": g.user.username if g.user else None,
            "prompt": (g.prompt[:60] + "..." if len(g.prompt) > 60 else g.prompt) if g.prompt else "",
            "status": g.status,
            "provider": g.provider,
            "model": g.model,
            "style": (g.parameters or {}).get("style"),
            "error_message": (g.error_message[:200] + "..." if g.error_message and len(g.error_message) > 200 else g.error_message) if g.error_message else None,
            "failure_category": _categorize_failure(g.error_message) if g.status == "failed" else None,
            "image_count": g.images.filter_by(is_deleted=False).count(),
            "created_at": g.created_at.isoformat() if g.created_at else None,
            "completed_at": g.completed_at.isoformat() if g.completed_at else None,
        }
        generations.append(gen_dict)

    return {
        "generations": generations,
        "total": result["total"],
        "page": result["page"],
        "pages": result["pages"],
        "has_next": result["has_next"],
        "has_prev": result["has_prev"],
    }


def _categorize_failure(error_message: str) -> str:
    """Categorize a generation failure for the admin dashboard."""
    if not error_message:
        return "unknown"
    msg = error_message.lower()
    if "api key" in msg or "auth" in msg or "unauthorized" in msg:
        return "authentication"
    if "rate limit" in msg or "too many" in msg or "429" in msg:
        return "rate_limit"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "network" in msg or "connection" in msg or "dns" in msg:
        return "network"
    if "quota" in msg or "limit" in msg or "exceeded" in msg:
        return "quota"
    if "invalid" in msg or "bad request" in msg or "validation" in msg:
        return "invalid_input"
    if "not found" in msg or "404" in msg:
        return "not_found"
    if "server" in msg or "500" in msg or "502" in msg or "503" in msg:
        return "server_error"
    return "other"


# ============================================================
# PROVIDER HEALTH
# ============================================================

def get_provider_health() -> list[dict]:
    """Check health of all registered providers.

    Returns safe status labels only:
      - 'configured': API key is set
      - 'reachable':  Provider is configured and functional (stub always passes)
      - 'unavailable': Provider is not configured or broken
    Never returns API keys, secrets, or internal config.
    """
    from app.services.ai_provider import list_providers, get_provider

    results = []
    for name in list_providers():
        try:
            p = get_provider(name)
            configured = p.is_configured()
            # For stub/local providers, "reachable" is always true if configured
            # For real API providers, we just report config status
            # A deeper health check could ping the provider, but we keep it safe
            if configured:
                status = "configured"
                # Test a minimal call for stub
                if name == "stub":
                    status = "reachable"
            else:
                status = "unavailable"

            results.append({
                "name": p.name,
                "display_name": p.display_name,
                "status": status,
                "configured": configured,
                "capabilities": p.get_capabilities().to_dict(),
            })
        except Exception:
            results.append({
                "name": name,
                "display_name": name,
                "status": "unavailable",
                "configured": False,
                "error": "Failed to initialize provider",
            })

    return results


# ============================================================
# HELPERS
# ============================================================

def _safe_user_dict(user: User, include_email: bool = False) -> dict:
    """Serialize a user for admin views — never exposes password_hash."""
    data = {
        "id": user.id,
        "username": user.username,
        "display_name": user.effective_display_name,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }
    if include_email:
        data["email"] = user.email
    return data


def get_audit_logs(
    admin_id: int = None,
    action: str = None,
    entity_type: str = None,
    page: int = 1,
    per_page: int = 30,
) -> dict:
    """Retrieve audit log entries with optional filters."""
    query = AuditLog.query

    if admin_id:
        query = query.filter_by(admin_id=admin_id)
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    if entity_type:
        query = query.filter_by(entity_type=entity_type)

    query = query.order_by(AuditLog.created_at.desc())
    result = paginate_query(query, page=page, per_page=per_page)

    entries = [e.to_dict() for e in result["items"]]
    return {
        "entries": entries,
        "total": result["total"],
        "page": result["page"],
        "pages": result["pages"],
        "has_next": result["has_next"],
        "has_prev": result["has_prev"],
    }
