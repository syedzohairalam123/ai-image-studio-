"""Sharing API routes — privacy toggle, share URLs, create-similar, public share page."""

from flask import jsonify, request, render_template, Response
from flask_login import current_user, login_required

from app.routes import api_bp, main_bp
from app.services.sharing_service import (
    toggle_privacy,
    set_privacy,
    regenerate_share_token,
    get_public_image_by_token,
    get_create_similar_params,
    bulk_set_privacy,
    generate_share_qrcode_png,
)


# ============================================================
# PRIVACY TOGGLE
# ============================================================


@api_bp.route("/images/<int:image_id>/privacy", methods=["POST"])
@login_required
def api_toggle_privacy(image_id):
    """Toggle image between public and private.

    POST body (optional): { "public": true/false }  — explicit set
    If no body or body missing 'public', toggles current state.
    """
    data = request.get_json(silent=True) or {}

    try:
        if "public" in data:
            make_public = bool(data["public"])
            result = set_privacy(current_user.id, image_id, make_public)
        else:
            result = toggle_privacy(current_user.id, image_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "status": "success",
        **result,
    })


@api_bp.route("/images/<int:image_id>/share", methods=["GET"])
@login_required
def api_get_share_info(image_id):
    """Get share token and URL for an image (owner only)."""
    image = get_create_similar_params(current_user.id, image_id)
    # This will raise ValueError if not found
    from app.models.image import Image
    img = Image.query.filter_by(id=image_id, user_id=current_user.id, is_deleted=False).first()
    if not img:
        return jsonify({"error": "Image not found"}), 404

    if not img.share_token:
        img.generate_share_token()
        from app.extensions import db
        db.session.commit()

    return jsonify({
        "status": "success",
        "share_token": img.share_token,
        "share_url": f"/share/{img.share_token}",
        "is_public": img.is_public,
    })


@api_bp.route("/images/<int:image_id>/share/regenerate", methods=["POST"])
@login_required
def api_regenerate_share_token(image_id):
    """Generate a new share token (invalidates the old one)."""
    try:
        result = regenerate_share_token(current_user.id, image_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "status": "success",
        **result,
    })


# ============================================================
# BULK PRIVACY
# ============================================================


@api_bp.route("/gallery/bulk/privacy", methods=["POST"])
@login_required
def api_bulk_privacy():
    """Bulk set privacy for multiple images.

    POST body: { "image_ids": [1,2,3], "public": true }
    """
    data = request.get_json(silent=True) or {}
    image_ids = data.get("image_ids") or []
    make_public = data.get("public", True)

    if not image_ids:
        return jsonify({"error": "No image IDs provided"}), 400

    if not isinstance(image_ids, list):
        return jsonify({"error": "image_ids must be a list"}), 400

    count = bulk_set_privacy(current_user.id, image_ids, bool(make_public))
    return jsonify({
        "status": "success",
        "affected": count,
    })


# ============================================================
# CREATE SIMILAR
# ============================================================


@api_bp.route("/images/<int:image_id>/create-similar", methods=["POST"])
@login_required
def api_create_similar(image_id):
    """Get generation params from an image to start a new creation.

    This NEVER modifies the original image — it only reads its parameters
    and returns them for the generator to prefill.
    """
    try:
        params = get_create_similar_params(current_user.id, image_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    return jsonify({
        "status": "success",
        "params": params,
    })


# ============================================================
# PUBLIC SHARE PAGE (non-API view)
# ============================================================


@main_bp.route("/share/<share_token>")
def share_page(share_token):
    """Public share page for a shared image.

    Shows: image, title, optional prompt, style, creator display name, date.
    Does NOT expose: email, internal IDs, filesystem paths, secrets.
    """
    image_data = get_public_image_by_token(share_token)
    if not image_data:
        from flask import abort
        abort(404)

    return render_template("share.html", image=image_data, share_token=share_token)


@main_bp.route("/share/<share_token>/qrcode.png")
def share_qrcode(share_token):
    """Public QR code pointing back to this share page — same visibility
    rules as the share page itself (404s for a token that isn't public)."""
    try:
        png_bytes = generate_share_qrcode_png(share_token, request.host_url)
    except ValueError:
        from flask import abort
        abort(404)

    return Response(
        png_bytes,
        mimetype="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )
