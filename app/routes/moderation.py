"""Moderation API routes — admin content report management and moderation actions."""

from flask import jsonify, request
from flask_login import current_user, login_required

from app.routes import api_bp
from app.services.moderation_service import (
    get_pending_reports,
    get_all_reports,
    moderate_report,
    set_moderation_state,
    get_moderation_stats,
)


def _require_admin():
    """Check that current user is an admin."""
    if not current_user.is_authenticated or not current_user.is_admin:
        return False
    return True


# ============================================================
# MODERATION DASHBOARD
# ============================================================


@api_bp.route("/moderation/stats", methods=["GET"])
@login_required
def api_moderation_stats():
    """Get moderation statistics (admin only)."""
    if not _require_admin():
        return jsonify({"error": "Admin access required"}), 403

    stats = get_moderation_stats()
    return jsonify(stats)


# ============================================================
# PENDING REPORTS
# ============================================================


@api_bp.route("/moderation/reports", methods=["GET"])
@login_required
def api_list_reports():
    """List content reports with optional status filter (admin only).

    Query params:
      status – pending, reviewed, dismissed, actioned
      page, per_page – pagination
    """
    if not _require_admin():
        return jsonify({"error": "Admin access required"}), 403

    status = request.args.get("status", "").strip() or None
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    result = get_all_reports(status=status, page=page, per_page=per_page)
    return jsonify(result)


@api_bp.route("/moderation/reports/pending", methods=["GET"])
@login_required
def api_pending_reports():
    """List pending reports (admin only)."""
    if not _require_admin():
        return jsonify({"error": "Admin access required"}), 403

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    result = get_pending_reports(page=page, per_page=per_page)
    return jsonify(result)


# ============================================================
# MODERATE A REPORT
# ============================================================


@api_bp.route("/moderation/reports/<int:report_id>/action", methods=["POST"])
@login_required
def api_moderate_report(report_id):
    """Take action on a report (admin only).

    POST body: { "action": "dismiss|actioned|reviewed", "note": "..." }
    """
    if not _require_admin():
        return jsonify({"error": "Admin access required"}), 403

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

    return jsonify({
        "status": "success",
        "report": report.to_dict(),
    })


# ============================================================
# DIRECT MODERATION STATE
# ============================================================


@api_bp.route("/moderation/images/<int:image_id>/state", methods=["POST"])
@login_required
def api_set_moderation_state(image_id):
    """Directly set moderation state of an image (admin only).

    POST body: { "state": "active|reported|hidden" }
    """
    if not _require_admin():
        return jsonify({"error": "Admin access required"}), 403

    data = request.get_json(silent=True) or {}
    state = (data.get("state") or "").strip()

    if not state:
        return jsonify({"error": "State is required"}), 400

    try:
        image = set_moderation_state(image_id, state)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "status": "success",
        "image_id": image.id,
        "moderation_state": image.moderation_state,
    })
