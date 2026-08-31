"""Explore API routes — public gallery, categories, search, styles, featured content."""

from flask import jsonify, request
from flask_login import current_user, login_required

from app.routes import api_bp
from app.services.explore_service import (
    explore_images,
    get_categories_with_counts,
    get_public_styles,
    get_featured_images,
    get_recent_public,
    get_explore_image_detail,
    like_public_image,
)
from app.services.moderation_service import report_image


# ============================================================
# EXPLORE — PUBLIC GALLERY
# ============================================================


@api_bp.route("/explore", methods=["GET"])
def api_explore():
    """List public images with search, filter, and pagination.

    Query params:
      search   – search title, prompt
      style    – filter by generation style
      category – filter by category (maps to styles)
      sort     – recent, popular, liked
      page, per_page – pagination
    """
    result = explore_images(
        search=request.args.get("search", "").strip(),
        style=request.args.get("style", "").strip(),
        category=request.args.get("category", "").strip(),
        sort=request.args.get("sort", "recent").strip().lower(),
        page=request.args.get("page", 1, type=int),
        per_page=request.args.get("per_page", 24, type=int),
    )

    return jsonify(result)


# ============================================================
# EXPLORE CATEGORIES
# ============================================================


@api_bp.route("/explore/categories", methods=["GET"])
def api_explore_categories():
    """List explore categories with image counts."""
    categories = get_categories_with_counts()
    return jsonify({"categories": categories})


# ============================================================
# EXPLORE STYLES
# ============================================================


@api_bp.route("/explore/styles", methods=["GET"])
def api_explore_styles():
    """List unique styles from public images with counts."""
    styles = get_public_styles()
    return jsonify({"styles": styles})


# ============================================================
# FEATURED IMAGES
# ============================================================


@api_bp.route("/explore/featured", methods=["GET"])
def api_explore_featured():
    """Get top featured public images."""
    limit = request.args.get("limit", 8, type=int)
    limit = min(max(1, limit), 50)
    images = get_featured_images(limit=limit)
    return jsonify({"images": images})


# ============================================================
# RECENT PUBLIC IMAGES
# ============================================================


@api_bp.route("/explore/recent", methods=["GET"])
def api_explore_recent():
    """Get most recently published public images."""
    limit = request.args.get("limit", 12, type=int)
    limit = min(max(1, limit), 50)
    images = get_recent_public(limit=limit)
    return jsonify({"images": images})


# ============================================================
# EXPLORE IMAGE DETAIL
# ============================================================


@api_bp.route("/explore/<share_token>", methods=["GET"])
def api_explore_detail(share_token):
    """Get full public detail for an explore image by share token."""
    detail = get_explore_image_detail(share_token)
    if not detail:
        return jsonify({"error": "Image not found"}), 404
    return jsonify(detail)


# ============================================================
# LIKE A PUBLIC IMAGE
# ============================================================


@api_bp.route("/explore/<share_token>/like", methods=["POST"])
def api_explore_like(share_token):
    """Like a public image (increments like count)."""
    try:
        result = like_public_image(share_token)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    return jsonify({
        "status": "success",
        **result,
    })


# ============================================================
# REPORT A PUBLIC IMAGE
# ============================================================


@api_bp.route("/explore/<share_token>/report", methods=["POST"])
@login_required
def api_explore_report(share_token):
    """Report a public image for inappropriate content.

    POST body: { "reason": "spam|inappropriate|copyright|other", "description": "..." }
    """
    # SECURITY: Ensure user is actually authenticated
    if not current_user.is_authenticated:
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()
    description = (data.get("description") or "").strip() or None

    if not reason:
        return jsonify({"error": "Reason is required"}), 400

    # Resolve share_token to image_id
    from app.models.image import Image
    image = Image.query.filter_by(
        share_token=share_token, is_deleted=False
    ).first()
    if not image or not image.is_public:
        return jsonify({"error": "Image not found"}), 404

    try:
        report = report_image(
            reporter_id=current_user.id,
            image_id=image.id,
            reason=reason,
            description=description,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "status": "success",
        "message": "Report submitted. Thank you for helping keep our community safe.",
        "report_id": report.id,
    }), 201
