"""Admin API routes — secure administrative and monitoring layer.

All endpoints require admin authentication.  The admin guard is applied
both at the route level (login_required + is_admin check) and in the
service layer for defense in depth.

Security notes:
  - API keys are never returned.
  - Password hashes are never exposed.
  - Provider health returns safe status labels only.
  - All admin actions are audit-logged.
"""

from flask import jsonify, request
from flask_login import current_user, login_required

from app.extensions import db
from app.routes import api_bp
from app.services.admin_service import (
    get_admin_dashboard,
    list_users,
    get_user_detail,
    set_user_active,
    set_user_admin,
    list_all_generations,
    get_provider_health,
    get_audit_logs,
    log_admin_action,
)


# ============================================================
# ADMIN GUARD
# ============================================================

def _require_admin():
    """Verify the current user is an authenticated admin. Returns error tuple or None."""
    if not current_user.is_authenticated:
        return jsonify({"error": "Authentication required"}), 401
    if not current_user.is_admin:
        return jsonify({"error": "Admin access required"}), 403
    return None


# ============================================================
# DASHBOARD
# ============================================================

@api_bp.route("/admin/dashboard", methods=["GET"])
@login_required
def admin_dashboard():
    """Get aggregated admin dashboard statistics."""
    guard = _require_admin()
    if guard:
        return guard

    stats = get_admin_dashboard()
    return jsonify({"dashboard": stats})


# ============================================================
# USER MANAGEMENT
# ============================================================

@api_bp.route("/admin/users", methods=["GET"])
@login_required
def admin_list_users():
    """List all users with filtering and pagination.

    Query params: search, status (active/inactive), role (admin/user),
                  page, per_page
    """
    guard = _require_admin()
    if guard:
        return guard

    search = request.args.get("search", "").strip() or None
    status = request.args.get("status", "").strip() or None
    role = request.args.get("role", "").strip() or None
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    result = list_users(
        search=search, status=status, role=role,
        page=page, per_page=per_page,
    )
    return jsonify(result)


@api_bp.route("/admin/users/<int:user_id>", methods=["GET"])
@login_required
def admin_get_user(user_id):
    """Get detailed info for a single user (admin only)."""
    guard = _require_admin()
    if guard:
        return guard

    data = get_user_detail(user_id)
    if not data:
        return jsonify({"error": "User not found"}), 404

    return jsonify({"user": data})


@api_bp.route("/admin/users/<int:user_id>/activate", methods=["POST"])
@login_required
def admin_activate_user(user_id):
    """Activate a user account."""
    guard = _require_admin()
    if guard:
        return guard

    user = set_user_active(user_id, True)
    if not user:
        return jsonify({"error": "User not found"}), 404

    log_admin_action(
        admin_id=current_user.id,
        action="activate_user",
        entity_type="user",
        entity_id=user_id,
        details={"username": user.username},
    )
    db.session.commit()

    return jsonify({
        "status": "success",
        "message": f"User {user.username} activated",
        "user_id": user.id,
        "is_active": True,
    })


@api_bp.route("/admin/users/<int:user_id>/deactivate", methods=["POST"])
@login_required
def admin_deactivate_user(user_id):
    """Deactivate a user account."""
    guard = _require_admin()
    if guard:
        return guard

    # Prevent admin from deactivating themselves
    if user_id == current_user.id:
        return jsonify({"error": "Cannot deactivate your own account"}), 400

    user = set_user_active(user_id, False)
    if not user:
        return jsonify({"error": "User not found"}), 404

    log_admin_action(
        admin_id=current_user.id,
        action="deactivate_user",
        entity_type="user",
        entity_id=user_id,
        details={"username": user.username},
    )
    db.session.commit()

    return jsonify({
        "status": "success",
        "message": f"User {user.username} deactivated",
        "user_id": user.id,
        "is_active": False,
    })


@api_bp.route("/admin/users/<int:user_id>/admin", methods=["POST"])
@login_required
def admin_toggle_admin(user_id):
    """Grant or revoke admin privileges.

    POST body: { "is_admin": true/false }
    """
    guard = _require_admin()
    if guard:
        return guard

    data = request.get_json(silent=True) or {}
    is_admin = data.get("is_admin")
    if is_admin is None:
        return jsonify({"error": "is_admin field required"}), 400

    user = set_user_admin(user_id, bool(is_admin))
    if not user:
        return jsonify({"error": "User not found"}), 404

    log_admin_action(
        admin_id=current_user.id,
        action="grant_admin" if is_admin else "revoke_admin",
        entity_type="user",
        entity_id=user_id,
        details={"username": user.username, "is_admin": is_admin},
    )
    db.session.commit()

    return jsonify({
        "status": "success",
        "message": f"Admin {'granted to' if is_admin else 'revoked from'} {user.username}",
        "user_id": user.id,
        "is_admin": user.is_admin,
    })


# ============================================================
# GENERATION MONITORING
# ============================================================

@api_bp.route("/admin/generations", methods=["GET"])
@login_required
def admin_list_generations():
    """List all generations across all users (admin only).

    Query params: status, provider, user_id, search, page, per_page
    """
    guard = _require_admin()
    if guard:
        return guard

    status = request.args.get("status", "").strip() or None
    provider = request.args.get("provider", "").strip() or None
    user_id = request.args.get("user_id", None, type=int)
    search = request.args.get("search", "").strip() or None
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    result = list_all_generations(
        status=status, provider=provider, user_id=user_id,
        search=search, page=page, per_page=per_page,
    )
    return jsonify(result)


# ============================================================
# PROVIDER HEALTH
# ============================================================

@api_bp.route("/admin/providers", methods=["GET"])
@login_required
def admin_provider_health():
    """Get safe health status of all providers.

    Returns configured/reachable/unavailable status.
    Never returns API keys or internal config.
    """
    guard = _require_admin()
    if guard:
        return guard

    providers = get_provider_health()
    return jsonify({"providers": providers})


# ============================================================
# CONTENT MODERATION (enhanced)
# ============================================================

@api_bp.route("/admin/moderation/stats", methods=["GET"])
@login_required
def admin_moderation_stats():
    """Get moderation statistics (admin only)."""
    guard = _require_admin()
    if guard:
        return guard

    from app.services.moderation_service import get_moderation_stats
    return jsonify(get_moderation_stats())


@api_bp.route("/admin/moderation/reports", methods=["GET"])
@login_required
def admin_list_reports():
    """List content reports (admin only)."""
    guard = _require_admin()
    if guard:
        return guard

    from app.services.moderation_service import get_all_reports
    status = request.args.get("status", "").strip() or None
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    result = get_all_reports(status=status, page=page, per_page=per_page)
    return jsonify(result)


@api_bp.route("/admin/moderation/reports/<int:report_id>/action", methods=["POST"])
@login_required
def admin_moderate_report(report_id):
    """Take action on a content report (admin only).

    POST body: { "action": "dismiss|actioned|reviewed", "note": "..." }
    """
    guard = _require_admin()
    if guard:
        return guard

    from app.services.moderation_service import moderate_report

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip()
    note = (data.get("note") or "").strip() or None

    if not action:
        return jsonify({"error": "Action is required"}), 400

    try:
        report = moderate_report(
            admin_id=current_user.id,
            report_id=report_id,
            action=action,
            note=note,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    log_admin_action(
        admin_id=current_user.id,
        action=f"moderate_report_{action}",
        entity_type="content_report",
        entity_id=report_id,
        details={"action": action, "note": note, "image_id": report.image_id},
    )
    db.session.commit()

    return jsonify({
        "status": "success",
        "report": report.to_dict(),
    })


@api_bp.route("/admin/moderation/images/<int:image_id>/state", methods=["POST"])
@login_required
def admin_set_image_state(image_id):
    """Set moderation state of an image (admin only).

    POST body: { "state": "active|reported|hidden" }
    """
    guard = _require_admin()
    if guard:
        return guard

    from app.services.moderation_service import set_moderation_state

    data = request.get_json(silent=True) or {}
    state = (data.get("state") or "").strip()

    if not state:
        return jsonify({"error": "State is required"}), 400

    try:
        image = set_moderation_state(image_id, state)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    log_admin_action(
        admin_id=current_user.id,
        action=f"set_image_state_{state}",
        entity_type="image",
        entity_id=image_id,
        details={"state": state},
    )
    db.session.commit()

    return jsonify({
        "status": "success",
        "image_id": image.id,
        "moderation_state": image.moderation_state,
    })


# ============================================================
# AUDIT LOGS
# ============================================================

@api_bp.route("/admin/audit-logs", methods=["GET"])
@login_required
def admin_audit_logs():
    """List audit log entries (admin only).

    Query params: admin_id, action, entity_type, page, per_page
    """
    guard = _require_admin()
    if guard:
        return guard

    admin_id = request.args.get("admin_id", None, type=int)
    action = request.args.get("action", "").strip() or None
    entity_type = request.args.get("entity_type", "").strip() or None
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 30, type=int)

    result = get_audit_logs(
        admin_id=admin_id, action=action,
        entity_type=entity_type, page=page, per_page=per_page,
    )
    return jsonify(result)
