from flask import render_template
from flask_login import current_user, login_required

from app.extensions import db
from app.models.generation import Generation
from app.models.image import Image
from app.models.collection import Collection
from app.routes import main_bp


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return _dashboard()
    return render_template("index.html")


def _dashboard():
    """Build dashboard data from the database."""
    user = current_user

    # Recent generations (last 6)
    recent_generations = (
        Generation.query
        .filter_by(user_id=user.id)
        .order_by(Generation.created_at.desc())
        .limit(6)
        .all()
    )

    # Total counts
    total_generations = Generation.query.filter_by(user_id=user.id).count()
    total_images = Image.query.filter_by(user_id=user.id, is_deleted=False).count()

    # This month's generations
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_generations = (
        Generation.query
        .filter(Generation.user_id == user.id, Generation.created_at >= month_start)
        .count()
    )

    # Failed generations
    failed_generations = (
        Generation.query
        .filter_by(user_id=user.id, status="failed")
        .count()
    )

    # 14-day activity, bucketed in Python (works the same on SQLite/Postgres/
    # MySQL — no DB-specific date-truncation SQL required) for a real chart
    # on the dashboard instead of a decorative/static graphic.
    from datetime import date, timedelta
    window_start_date = now.date() - timedelta(days=13)
    window_start_dt = datetime(window_start_date.year, window_start_date.month,
                                window_start_date.day, tzinfo=timezone.utc)
    window_rows = (
        Generation.query
        .filter(Generation.user_id == user.id, Generation.created_at >= window_start_dt)
        .with_entities(Generation.created_at, Generation.status)
        .all()
    )
    buckets = {window_start_date + timedelta(days=i): {"total": 0, "completed": 0} for i in range(14)}
    for created_at, status in window_rows:
        bucket_date = created_at.date() if created_at else None
        if bucket_date in buckets:
            buckets[bucket_date]["total"] += 1
            if status == "completed":
                buckets[bucket_date]["completed"] += 1
    ordered_days = sorted(buckets.keys())
    activity_chart = {
        "labels": [d.strftime("%b %d") for d in ordered_days],
        "total": [buckets[d]["total"] for d in ordered_days],
        "completed": [buckets[d]["completed"] for d in ordered_days],
    }

    return render_template(
        "dashboard.html",
        user=user,
        recent_generations=recent_generations,
        total_generations=total_generations,
        total_images=total_images,
        monthly_generations=monthly_generations,
        failed_generations=failed_generations,
        activity_chart=activity_chart,
    )


@main_bp.route("/generate")
def generate():
    return render_template("generate.html")


@main_bp.route("/editor")
def editor():
    return render_template("editor.html")


@main_bp.route("/history")
@login_required
def history():
    return render_template("history.html")


@main_bp.route("/gallery")
def gallery():
    return render_template("gallery.html")


@main_bp.route("/favorites")
@login_required
def favorites():
    return render_template("favorites.html")


@main_bp.route("/images/<int:image_id>")
@login_required
def image_detail(image_id):
    """Image detail page — only shown if user owns the image."""
    image = Image.query.filter_by(
        id=image_id, user_id=current_user.id, is_deleted=False
    ).first()
    if not image:
        from flask import abort
        abort(404)
    return render_template("image_detail.html", image=image)


@main_bp.route("/collections")
@login_required
def collections():
    return render_template("collections.html")


@main_bp.route("/collections/<int:collection_id>")
@login_required
def collection_detail(collection_id):
    """Collection detail page with images."""
    collection = Collection.query.filter_by(
        id=collection_id, user_id=current_user.id, is_deleted=False
    ).first()
    if not collection:
        from flask import abort
        abort(404)
    return render_template("collection_detail.html", collection=collection)


@main_bp.route("/prompts")
@login_required
def prompts():
    return render_template("prompts.html")


@main_bp.route("/explore")
def explore():
    return render_template("explore.html")


@main_bp.route("/moderation")
@login_required
def moderation_dashboard():
    """Moderation dashboard (admin only)."""
    if not current_user.is_admin:
        from flask import abort
        abort(403)
    return render_template("moderation.html")


@main_bp.route("/styles")
def styles():
    return render_template("styles.html")


@main_bp.route("/utilities")
@login_required
def utilities():
    return render_template("utilities.html")


@main_bp.route("/settings")
@login_required
def settings():
    from app.services.settings_service import get_user_settings, get_available_options, get_user_stats
    user_settings = get_user_settings(current_user.id)
    options = get_available_options()
    stats = get_user_stats(current_user.id)
    return render_template(
        "settings.html",
        settings=user_settings.get_all(),
        options=options,
        stats=stats,
    )


@main_bp.route("/admin")
@login_required
def admin_dashboard():
    """Admin dashboard page (admin only)."""
    if not current_user.is_admin:
        from flask import abort
        abort(403)
    from app.services.admin_service import get_admin_dashboard, get_provider_health
    dashboard_stats = get_admin_dashboard()
    providers = get_provider_health()
    return render_template(
        "admin.html",
        dashboard=dashboard_stats,
        providers=providers,
    )
