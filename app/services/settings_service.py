"""Settings service — validation, defaults, usage statistics, personalization.

This service is the single source of truth for reading and writing user
settings.  It validates every mutation, computes usage statistics from
the database, and provides personalization helpers (e.g., remembering
the user's recent style choice).
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from flask import current_app

from app.extensions import db
from app.models.user_settings import (
    UserSettings,
    _default_settings,
    VALID_THEMES,
    VALID_STYLES,
    VALID_RATIOS,
    VALID_QUALITIES,
    VALID_OUTPUT_COUNTS,
    VALID_PRIVACY_LEVELS,
)
from app.models.generation import Generation
from app.models.image import Image
from app.models.collection import Collection
from app.models.saved_prompt import SavedPrompt
from app.models.style_preset import StylePreset
from app.models.reference_image import ReferenceImage


# ── Validation ─────────────────────────────────────────────────────

_VALIDATORS = {
    "theme": lambda v: v in VALID_THEMES,
    "default_style": lambda v: v in VALID_STYLES,
    "default_ratio": lambda v: v in VALID_RATIOS,
    "default_quality": lambda v: v in VALID_QUALITIES,
    "default_output_count": lambda v: v in VALID_OUTPUT_COUNTS and isinstance(v, int),
    "default_image_visibility": lambda v: v in VALID_PRIVACY_LEVELS,
    "toast_duration": lambda v: isinstance(v, int) and 1000 <= v <= 15000,
    "rows_per_page": lambda v: isinstance(v, int) and 5 <= v <= 100,
    "display_name": lambda v: isinstance(v, str) and len(v) <= 100,
    "bio": lambda v: isinstance(v, str) and len(v) <= 500,
    "language": lambda v: isinstance(v, str) and len(v) <= 10,
    "timezone": lambda v: isinstance(v, str) and len(v) <= 50,
    "date_format": lambda v: isinstance(v, str) and len(v) <= 20,
    "default_model": lambda v: isinstance(v, str) and len(v) <= 100,
}


def validate_settings(updates: dict) -> tuple[dict, list[str]]:
    """Validate a dict of setting updates.

    Returns:
        (cleaned_updates, error_messages)
        If error_messages is non-empty the caller should reject the update.
    """
    errors = []
    cleaned = {}

    for key, value in updates.items():
        if key not in _default_settings():
            errors.append(f"Unknown setting: '{key}'")
            continue

        validator = _VALIDATORS.get(key)
        if validator and not validator(value):
            errors.append(f"Invalid value for '{key}': {value!r}")
            continue

        cleaned[key] = value

    return cleaned, errors


# ── CRUD ───────────────────────────────────────────────────────────

def get_user_settings(user_id: int) -> UserSettings:
    """Get or create settings for a user (lazy init)."""
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings is None:
        settings = UserSettings(user_id=user_id, settings=_default_settings())
        db.session.add(settings)
        db.session.commit()
    return settings


def update_user_settings(user_id: int, updates: dict) -> tuple[Optional[UserSettings], list[str]]:
    """Validate and apply settings updates for a user.

    Returns:
        (updated_settings, errors)  — errors is empty on success.
    """
    cleaned, errors = validate_settings(updates)
    if errors:
        return None, errors

    settings = get_user_settings(user_id)
    settings.set_many(cleaned)
    db.session.commit()
    return settings, []


def reset_user_settings(user_id: int, section: Optional[str] = None) -> UserSettings:
    """Reset all settings or a specific section to defaults."""
    settings = get_user_settings(user_id)
    if section:
        settings.reset_section(section)
    else:
        settings.reset_to_defaults()
    db.session.commit()
    return settings


# ── Usage Statistics ───────────────────────────────────────────────

def get_user_stats(user_id: int) -> dict:
    """Compute usage statistics from the database for the current user.

    These are real, application-derived numbers — no invented costs.
    """
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    # ── Generations ──
    total_generations = Generation.query.filter_by(user_id=user_id).count()
    completed_generations = Generation.query.filter_by(
        user_id=user_id, status="completed"
    ).count()
    failed_generations = Generation.query.filter_by(
        user_id=user_id, status="failed"
    ).count()
    pending_generations = Generation.query.filter(
        Generation.user_id == user_id,
        Generation.status.in_(["pending", "processing"]),
    ).count()

    # ── Monthly / Weekly ──
    monthly_generations = Generation.query.filter(
        Generation.user_id == user_id,
        Generation.created_at >= month_start,
    ).count()
    weekly_generations = Generation.query.filter(
        Generation.user_id == user_id,
        Generation.created_at >= week_start,
    ).count()

    # ── Images ──
    total_images = Image.query.filter_by(user_id=user_id, is_deleted=False).count()
    total_downloads = Image.query.filter_by(user_id=user_id, is_deleted=False).count()  # We count active images as proxy
    favorited_images = Image.query.filter_by(
        user_id=user_id, is_favorite=True, is_deleted=False
    ).count()
    public_images = Image.query.filter_by(
        user_id=user_id, is_public=True, is_deleted=False
    ).count()

    # ── Total file size ──
    total_size_result = db.session.query(
        db.func.sum(Image.file_size)
    ).filter_by(user_id=user_id, is_deleted=False).scalar()
    total_size_bytes = total_size_result or 0

    # ── Collections ──
    total_collections = Collection.query.filter_by(user_id=user_id, is_deleted=False).count()

    # ── Saved Prompts ──
    total_prompts = SavedPrompt.query.filter_by(user_id=user_id).count()

    # ── Style Presets ──
    total_presets = StylePreset.query.filter_by(user_id=user_id).count()

    # ── Reference Images ──
    total_references = ReferenceImage.query.filter_by(
        user_id=user_id, is_deleted=False
    ).count()

    # ── Most used styles ──
    style_counts = (
        db.session.query(
            Generation.parameters["style"].as_string(),
            db.func.count(Generation.id),
        )
        .filter(Generation.user_id == user_id)
        .filter(Generation.parameters["style"].as_string() != None)
        .group_by(Generation.parameters["style"].as_string())
        .order_by(db.func.count(Generation.id).desc())
        .limit(5)
        .all()
    )
    top_styles = [{"style": s, "count": c} for s, c in style_counts if s]

    # ── Most used aspect ratios ──
    ratio_counts = (
        db.session.query(
            Generation.parameters["aspect_ratio"].as_string(),
            db.func.count(Generation.id),
        )
        .filter(Generation.user_id == user_id)
        .filter(Generation.parameters["aspect_ratio"].as_string() != None)
        .group_by(Generation.parameters["aspect_ratio"].as_string())
        .order_by(db.func.count(Generation.id).desc())
        .limit(5)
        .all()
    )
    top_ratios = [{"ratio": r, "count": c} for r, c in ratio_counts if r]

    # ── Average generations per day (last 30 days) ──
    thirty_days_ago = now - timedelta(days=30)
    recent_count = Generation.query.filter(
        Generation.user_id == user_id,
        Generation.created_at >= thirty_days_ago,
    ).count()
    avg_per_day = round(recent_count / 30, 1) if recent_count else 0

    # ── Success rate ──
    total_attempted = completed_generations + failed_generations
    success_rate = (
        round((completed_generations / total_attempted) * 100, 1)
        if total_attempted > 0
        else 0
    )

    # ── Member since ──
    from app.models.user import User
    user = db.session.get(User, user_id)
    member_since = user.created_at.isoformat() if user and user.created_at else None

    return {
        # Generations
        "total_generations": total_generations,
        "completed_generations": completed_generations,
        "failed_generations": failed_generations,
        "pending_generations": pending_generations,
        "monthly_generations": monthly_generations,
        "weekly_generations": weekly_generations,
        "avg_per_day": avg_per_day,
        "success_rate": success_rate,
        # Images
        "total_images": total_images,
        "favorited_images": favorited_images,
        "public_images": public_images,
        "total_size_bytes": total_size_bytes,
        "total_size_mb": round(total_size_bytes / (1024 * 1024), 2) if total_size_bytes else 0,
        # Library
        "total_collections": total_collections,
        "total_prompts": total_prompts,
        "total_presets": total_presets,
        "total_references": total_references,
        # Insights
        "top_styles": top_styles,
        "top_ratios": top_ratios,
        # Account
        "member_since": member_since,
    }


# ── Personalization ────────────────────────────────────────────────

def remember_generation_defaults(user_id: int, params: dict) -> None:
    """Update generation defaults based on the last generation.

    Called after a successful generation to remember the user's
    most recent style, ratio, quality, and model choices.
    """
    updates = {}

    if "style" in params and params["style"]:
        updates["default_style"] = params["style"]
    if "aspect_ratio" in params and params["aspect_ratio"]:
        updates["default_ratio"] = params["aspect_ratio"]
    if "quality" in params and params["quality"]:
        updates["default_quality"] = params["quality"]
    if "count" in params and params["count"]:
        updates["default_output_count"] = params["count"]
    if "model" in params and params["model"]:
        updates["default_model"] = params["model"]

    if updates:
        settings = get_user_settings(user_id)
        settings.set_many(updates)
        db.session.commit()


def get_generation_defaults(user_id: int) -> dict:
    """Get the user's generation defaults for pre-filling the generator."""
    settings = get_user_settings(user_id)
    return {
        "style": settings.get("default_style", "auto"),
        "aspect_ratio": settings.get("default_ratio", "1:1"),
        "quality": settings.get("default_quality", "standard"),
        "count": settings.get("default_output_count", 1),
        "model": settings.get("default_model", "stub"),
        "auto_enhance": settings.get("auto_enhance", False),
        "show_negative_prompt": settings.get("show_negative_prompt", False),
        "show_seed": settings.get("show_seed", False),
        "show_advanced": settings.get("show_advanced", False),
    }


def apply_privacy_defaults(user_id: int, image: Image) -> None:
    """Apply the user's default privacy settings to a newly created image."""
    settings = get_user_settings(user_id)
    default_visibility = settings.get("default_image_visibility", "private")

    if default_visibility == "public":
        image.make_public()
    elif default_visibility == "unlisted":
        image.is_public = True
        image.generate_share_token()
    else:
        image.is_public = False


def get_notification_preferences(user_id: int) -> dict:
    """Get the user's notification preferences."""
    settings = get_user_settings(user_id)
    return {
        "generation_complete": settings.get("notify_generation_complete", True),
        "generation_failed": settings.get("notify_generation_failed", True),
        "system_updates": settings.get("notify_system_updates", True),
        "tips_tricks": settings.get("notify_tips_tricks", False),
        "email": settings.get("email_notifications", False),
        "toast_duration": settings.get("toast_duration", 4000),
    }


# ── Available Options ──────────────────────────────────────────────

def get_available_options() -> dict:
    """Return valid options for each settings field.

    Only show models/options that are actually available in the system.
    """
    from app.services.ai_provider import list_providers, get_provider

    models = []
    for name in list_providers():
        try:
            p = get_provider(name)
            models.append({
                "id": p.name,
                "name": p.display_name,
                "configured": p.is_configured(),
            })
        except Exception:
            models.append({"id": name, "name": name, "configured": False})

    return {
        "themes": [{"id": t, "name": t.capitalize()} for t in VALID_THEMES],
        "styles": [{"id": s, "name": _style_display(s)} for s in VALID_STYLES],
        "ratios": [{"id": r, "name": r} for r in VALID_RATIOS],
        "qualities": [{"id": q, "name": q.capitalize()} for q in VALID_QUALITIES],
        "output_counts": [{"id": c, "name": str(c)} for c in VALID_OUTPUT_COUNTS],
        "privacy_levels": [{"id": p, "name": p.capitalize()} for p in VALID_PRIVACY_LEVELS],
        "models": models,
    }


def _style_display(style: str) -> str:
    """Human-readable style name."""
    labels = {
        "auto": "✨ Auto",
        "photo": "📷 Photo",
        "art": "🖌️ Digital Art",
        "paint": "🎨 Painting",
        "anime": "🎞️ Anime",
        "3d": "🧊 3D Render",
        "pixel": "👾 Pixel Art",
        "minimal": "📐 Minimal",
    }
    return labels.get(style, style.capitalize())
