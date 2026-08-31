"""Settings routes — API endpoints for user settings, usage stats, and account management.

Endpoints:
  GET  /api/v1/settings          — Get all user settings
  PUT  /api/v1/settings          — Update settings (partial)
  POST /api/v1/settings/reset    — Reset settings to defaults
  GET  /api/v1/settings/usage    — Get usage statistics
  GET  /api/v1/settings/options  — Get available option values
  POST /api/v1/settings/export   — Export user data (GDPR)
  POST /api/v1/account/password  — Change password
  POST /api/v1/account/deactivate — Deactivate account
"""

from flask import jsonify, request
from flask_login import current_user, login_required

from app.extensions import db
from app.models.user import User
from app.routes import api_bp
from app.services.settings_service import (
    get_user_settings,
    update_user_settings,
    reset_user_settings,
    get_user_stats,
    get_generation_defaults,
    get_available_options,
    get_notification_preferences,
)


# ============================================================
# SETTINGS CRUD
# ============================================================

@api_bp.route("/settings", methods=["GET"])
@login_required
def get_settings():
    """Get all settings for the current user."""
    settings = get_user_settings(current_user.id)
    return jsonify({
        "settings": settings.get_all(),
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    })


@api_bp.route("/settings", methods=["PUT"])
@login_required
def update_settings():
    """Update settings for the current user.

    Accepts partial updates — only the keys in the request body are changed.
    """
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    settings, errors = update_user_settings(current_user.id, data)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 422

    return jsonify({
        "status": "success",
        "settings": settings.get_all(),
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    })


@api_bp.route("/settings/reset", methods=["POST"])
@login_required
def reset_settings():
    """Reset settings to defaults.

    Optional body: { "section": "appearance" } to reset a specific section.
    """
    data = request.get_json(silent=True) or {}
    section = data.get("section")

    valid_sections = (
        "appearance", "generation_defaults", "privacy",
        "notifications", "account", None,
    )
    if section not in valid_sections:
        return jsonify({
            "error": f"Invalid section. Must be one of: {[s for s in valid_sections if s]}"
        }), 400

    settings = reset_user_settings(current_user.id, section)
    return jsonify({
        "status": "success",
        "message": f"Settings reset{f' for section: {section}' if section else ''}.",
        "settings": settings.get_all(),
    })


# ============================================================
# USAGE STATISTICS
# ============================================================

@api_bp.route("/settings/usage", methods=["GET"])
@login_required
def usage_stats():
    """Get usage statistics for the current user."""
    stats = get_user_stats(current_user.id)
    return jsonify({"usage": stats})


# ============================================================
# AVAILABLE OPTIONS
# ============================================================

@api_bp.route("/settings/options", methods=["GET"])
@login_required
def available_options():
    """Get all available option values for settings fields."""
    return jsonify({"options": get_available_options()})


# ============================================================
# GENERATION DEFAULTS (convenience endpoint)
# ============================================================

@api_bp.route("/settings/generation-defaults", methods=["GET"])
@login_required
def generation_defaults():
    """Get the user's generation defaults for pre-filling the generator."""
    defaults = get_generation_defaults(current_user.id)
    return jsonify({"defaults": defaults})


@api_bp.route("/settings/generation-defaults", methods=["PUT"])
@login_required
def update_generation_defaults():
    """Update generation defaults."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    # Only allow generation default keys
    allowed_keys = {
        "default_model", "default_style", "default_ratio",
        "default_output_count", "default_quality",
        "auto_enhance", "show_negative_prompt", "show_seed", "show_advanced",
    }
    updates = {k: v for k, v in data.items() if k in allowed_keys}

    if not updates:
        return jsonify({"error": "No valid settings to update"}), 400

    settings, errors = update_user_settings(current_user.id, updates)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 422

    return jsonify({
        "status": "success",
        "defaults": get_generation_defaults(current_user.id),
    })


# ============================================================
# NOTIFICATION PREFERENCES
# ============================================================

@api_bp.route("/settings/notifications", methods=["GET"])
@login_required
def notification_prefs():
    """Get notification preferences."""
    prefs = get_notification_preferences(current_user.id)
    return jsonify({"notifications": prefs})


@api_bp.route("/settings/notifications", methods=["PUT"])
@login_required
def update_notification_prefs():
    """Update notification preferences."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    # Map incoming keys to settings keys
    mapping = {
        "generation_complete": "notify_generation_complete",
        "generation_failed": "notify_generation_failed",
        "system_updates": "notify_system_updates",
        "tips_tricks": "notify_tips_tricks",
        "email": "email_notifications",
        "toast_duration": "toast_duration",
    }

    updates = {}
    for incoming_key, value in data.items():
        settings_key = mapping.get(incoming_key, incoming_key)
        updates[settings_key] = value

    settings, errors = update_user_settings(current_user.id, updates)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 422

    return jsonify({
        "status": "success",
        "notifications": get_notification_preferences(current_user.id),
    })


# ============================================================
# DATA EXPORT (GDPR)
# ============================================================

@api_bp.route("/settings/export", methods=["POST"])
@login_required
def export_data():
    """Export all user data as JSON (GDPR compliance)."""
    settings = get_user_settings(current_user.id)
    stats = get_user_stats(current_user.id)

    # Gather user data
    from app.models.generation import Generation
    from app.models.image import Image
    from app.models.saved_prompt import SavedPrompt
    from app.models.collection import Collection

    generations = [
        g.to_dict() for g in
        Generation.query.filter_by(user_id=current_user.id)
        .order_by(Generation.created_at.desc()).all()
    ]

    images = [
        img.to_dict(include_metadata=True) for img in
        Image.query.filter_by(user_id=current_user.id, is_deleted=False).all()
    ]

    prompts = [
        p.to_dict() for p in
        SavedPrompt.query.filter_by(user_id=current_user.id).all()
    ]

    collections = [
        c.to_dict() for c in
        Collection.query.filter_by(user_id=current_user.id, is_deleted=False).all()
    ]

    return jsonify({
        "user": {
            "username": current_user.username,
            "email": current_user.email,
            "display_name": current_user.effective_display_name,
            "is_admin": current_user.is_admin,
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        },
        "settings": settings.get_all(),
        "usage": stats,
        "generations": generations,
        "images": images,
        "saved_prompts": prompts,
        "collections": collections,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    })


# ============================================================
# ACCOUNT MANAGEMENT
# ============================================================

@api_bp.route("/account/password", methods=["POST"])
@login_required
def change_password():
    """Change the user's password.

    POST body: { "current_password": "...", "new_password": "..." }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body required"}), 400

    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    if not current_password:
        return jsonify({"error": "Current password is required"}), 400
    if not new_password:
        return jsonify({"error": "New password is required"}), 400
    if len(new_password) < 8:
        return jsonify({"error": "New password must be at least 8 characters"}), 400
    if len(new_password) > 128:
        return jsonify({"error": "New password must be at most 128 characters"}), 400

    if not current_user.check_password(current_password):
        return jsonify({"error": "Current password is incorrect"}), 401

    current_user.set_password(new_password)
    db.session.commit()

    return jsonify({
        "status": "success",
        "message": "Password changed successfully.",
    })


@api_bp.route("/account/profile", methods=["PUT"])
@login_required
def update_profile():
    """Update profile fields (display_name, bio).

    Does NOT expose or return email or password hash.
    """
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    updates = {}

    if "display_name" in data:
        display_name = (data["display_name"] or "").strip()
        if len(display_name) > 100:
            return jsonify({"error": "Display name must be at most 100 characters"}), 400
        current_user.display_name = display_name or None

    if "bio" in data:
        bio = (data["bio"] or "").strip()
        if len(bio) > 500:
            return jsonify({"error": "Bio must be at most 500 characters"}), 400
        # Store bio in settings
        settings = get_user_settings(current_user.id)
        settings.set_many({"bio": bio})
        updates["bio"] = bio

    db.session.commit()

    return jsonify({
        "status": "success",
        "user": current_user.to_public_dict(),
    })


@api_bp.route("/account/deactivate", methods=["POST"])
@login_required
def deactivate_account():
    """Soft-deactivate the user's account.

    The user can no longer log in but data is preserved.
    Requires password confirmation.
    """
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")

    if not password:
        return jsonify({"error": "Password required to deactivate account"}), 400

    if not current_user.check_password(password):
        return jsonify({"error": "Incorrect password"}), 401

    current_user.is_active = False
    db.session.commit()

    return jsonify({
        "status": "success",
        "message": "Account deactivated. You can no longer log in.",
    })


# ── Import for export endpoint ──
from datetime import datetime, timezone
