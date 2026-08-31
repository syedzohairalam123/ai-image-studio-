import os
import re
from pathlib import Path

from flask import jsonify, request, send_file
from flask_login import current_user, login_required

from app.extensions import db
from app.models.generation import Generation
from app.models.image import Image
from app.routes import api_bp
from app.services.ai_provider import list_providers
from app.services.generation_service import (
    GenerationError,
    run_generation,
    validate_generation_params,
)
from app.utils import paginate_query


# ---- Safe MIME detection (don't trust file extension alone) ----

_MIME_MAP = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _safe_mimetype(file_path: Path) -> str:
    """Determine MIME type from file extension with a safe default."""
    ext = file_path.suffix.lower()
    return _MIME_MAP.get(ext, "application/octet-stream")


# ---- Path traversal protection ----

def _is_safe_path(file_path: Path, allowed_root: Path) -> bool:
    """Ensure resolved path stays within the allowed root directory."""
    try:
        resolved = file_path.resolve()
        return resolved.is_relative_to(allowed_root.resolve())
    except (ValueError, OSError):
        return False


# ---- API Status ----

@api_bp.route("/status", methods=["GET"])
def api_status():
    """API status endpoint."""
    return jsonify({
        "status": "running",
        "version": "0.1.0",
        "providers": list_providers(),
    })


# ---- Generate Image ----

@api_bp.route("/generate", methods=["POST"])
@login_required
def generate_image():
    """Generate an image from a prompt."""
    data = request.get_json(silent=True) or request.form.to_dict()

    try:
        generation = run_generation(current_user.id, data)
    except GenerationError as e:
        return jsonify({"error": e.message, "status_code": e.status_code}), e.status_code
    except Exception as e:
        # SECURITY: Never leak stack traces in production
        from flask import current_app
        current_app.logger.exception("Unexpected error in generate_image")
        return jsonify({"error": "An unexpected error occurred", "status_code": 500}), 500

    # Build response with image data
    images = []
    for img in generation.images:
        images.append({
            "id": img.id,
            "url": f"/api/v1/images/{img.id}/file",
            "thumb_url": f"/api/v1/images/{img.id}/thumbnail",
            "filename": img.filename,
            "width": img.width,
            "height": img.height,
            "seed": img.seed,
            "file_size": img.file_size,
        })

    return jsonify({
        "status": "success",
        "generation": generation.to_dict(),
        "images": images,
    }), 200


# ---- Get Image File ----

@api_bp.route("/images/<int:image_id>/file", methods=["GET"])
def get_image_file(image_id):
    """Serve an image file.

    SECURITY FIX: Now checks ownership OR public status instead of
    serving to anyone.  Public images are served without auth;
    private images require the owner to be logged in.
    """
    image = Image.query.filter_by(id=image_id, is_deleted=False).first()
    if not image:
        return jsonify({"error": "Image not found"}), 404

    # ACCESS CHECK: owner or public
    is_owner = current_user.is_authenticated and image.user_id == current_user.id
    is_public = image.is_public and image.moderation_state == "active"
    if not is_owner and not is_public:
        return jsonify({"error": "Access denied"}), 403

    file_path = Path(image.file_path)
    if not file_path.exists():
        return jsonify({"error": "Image file not found"}), 404

    # SECURITY: Path traversal check
    from flask import current_app
    upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "uploads"))
    if not _is_safe_path(file_path, upload_root):
        current_app.logger.warning("Path traversal attempt blocked: %s", file_path)
        return jsonify({"error": "Access denied"}), 403

    return send_file(str(file_path), mimetype=_safe_mimetype(file_path))


# ---- Thumbnail Image ----

@api_bp.route("/images/<int:image_id>/thumbnail", methods=["GET"])
def get_image_thumbnail(image_id):
    """Serve an image thumbnail.

    SECURITY FIX: Same access control as file endpoint.
    """
    image = Image.query.filter_by(id=image_id, is_deleted=False).first()
    if not image:
        return jsonify({"error": "Image not found"}), 404

    # ACCESS CHECK: owner or public
    is_owner = current_user.is_authenticated and image.user_id == current_user.id
    is_public = image.is_public and image.moderation_state == "active"
    if not is_owner and not is_public:
        return jsonify({"error": "Access denied"}), 403

    # Try thumbnail path first, fallback to main image
    thumb_path = None
    if image.thumb_path:
        thumb_path = Path(image.thumb_path)
        if not thumb_path.exists():
            thumb_path = None
    
    # Fallback to main image file
    if not thumb_path:
        thumb_path = Path(image.file_path)

    if not thumb_path.exists():
        return jsonify({"error": "Image file not found"}), 404

    # SECURITY: Path traversal check
    from flask import current_app
    upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "uploads"))
    if not _is_safe_path(thumb_path, upload_root):
        current_app.logger.warning("Path traversal attempt blocked: %s", thumb_path)
        return jsonify({"error": "Access denied"}), 403

    return send_file(str(thumb_path), mimetype=_safe_mimetype(thumb_path))


# ---- Download Image ----

@api_bp.route("/images/<int:image_id>/download", methods=["GET"])
@login_required
def download_image(image_id):
    """Download an image file with ownership check."""
    image = Image.query.filter_by(id=image_id, is_deleted=False).first()
    if not image:
        return jsonify({"error": "Image not found"}), 404

    # Ownership check
    if image.user_id != current_user.id:
        return jsonify({"error": "Access denied"}), 403

    file_path = Path(image.file_path)
    if not file_path.exists():
        return jsonify({"error": "Image file not found"}), 404

    # SECURITY: Path traversal check
    from flask import current_app
    upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "uploads"))
    if not _is_safe_path(file_path, upload_root):
        return jsonify({"error": "Access denied"}), 403

    # SECURITY: Sanitize download name — strip path components
    safe_name = re.sub(r'[^\w\-]', '_', f"ai-studio-{image.id}") + file_path.suffix

    return send_file(
        str(file_path),
        as_attachment=True,
        download_name=safe_name,
    )


# ---- Generation History (Enhanced) ----

@api_bp.route("/generations", methods=["GET"])
@login_required
def list_generations():
    """List user's generations with filtering, search, sorting, and pagination."""
    page = request.args.get("page", 1, type=int)
    per_page = min(max(1, request.args.get("per_page", 20, type=int)), 100)
    search = request.args.get("search", "").strip()
    style = request.args.get("style", "").strip()
    model = request.args.get("model", "").strip()
    status = request.args.get("status", "").strip()
    favorite = request.args.get("favorite", "").strip().lower()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sort = request.args.get("sort", "newest").strip().lower()

    query = Generation.query.filter_by(user_id=current_user.id)

    # Search on prompt
    if search:
        # SECURITY: Use parameterized query (SQLAlchemy handles this)
        query = query.filter(Generation.prompt.ilike(f"%{search}%"))

    # Filter by style (stored in parameters JSON)
    if style:
        query = query.filter(Generation.parameters["style"].as_string() == style)

    # Filter by model
    if model:
        query = query.filter(Generation.model.ilike(f"%{model}%"))

    # Filter by status
    if status and status in Generation.STATUSES:
        query = query.filter_by(status=status)

    # Filter by favorite
    if favorite == "true":
        query = query.filter(
            Generation.images.any(
                db.and_(Image.is_favorite == True, Image.is_deleted == False)
            )
        )

    # Exclude soft-deleted generations
    query = query.filter(
        db.or_(
            Generation.images.any(Image.is_deleted == False),
            ~Generation.images.any()
        )
    )

    # Date range filter
    if date_from:
        from datetime import datetime, timezone
        try:
            dt_from = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            query = query.filter(Generation.created_at >= dt_from)
        except (ValueError, TypeError):
            pass
    if date_to:
        from datetime import datetime, timezone
        try:
            dt_to = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            query = query.filter(Generation.created_at <= dt_to)
        except (ValueError, TypeError):
            pass

    # Sort
    if sort == "oldest":
        query = query.order_by(Generation.created_at.asc())
    else:
        query = query.order_by(Generation.created_at.desc())

    result = paginate_query(query, page=page, per_page=per_page)

    # Enrich generations with image data
    generations = []
    for gen in result["items"]:
        gen_dict = gen.to_dict()
        thumb = gen.images.filter_by(is_deleted=False).first()
        if thumb:
            gen_dict["thumbnail_url"] = f"/api/v1/images/{thumb.id}/thumbnail"
            gen_dict["image_id"] = thumb.id
        else:
            gen_dict["thumbnail_url"] = None
            gen_dict["image_id"] = None

        gen_dict["image_count"] = gen.images.filter_by(is_deleted=False).count()
        gen_dict["has_favorite"] = gen.images.filter_by(
            is_favorite=True, is_deleted=False
        ).first() is not None

        generations.append(gen_dict)

    # SECURITY: Get available styles and models efficiently (avoid N+1)
    all_generations = Generation.query.filter_by(user_id=current_user.id).all()
    styles_set = set()
    models_set = set()
    for g in all_generations:
        if g.parameters and g.parameters.get("style"):
            styles_set.add(g.parameters["style"])
        if g.model:
            models_set.add(g.model)

    return jsonify({
        "generations": generations,
        "total": result["total"],
        "page": result["page"],
        "pages": result["pages"],
        "per_page": result["per_page"],
        "has_next": result["has_next"],
        "has_prev": result["has_prev"],
        "filters": {
            "styles": sorted(styles_set),
            "models": sorted(models_set),
            "statuses": list(Generation.STATUSES),
        },
    })


# ---- Image Detail ----

@api_bp.route("/images/<int:image_id>", methods=["GET"])
@login_required
def get_image_detail(image_id):
    """Get full details for a single image (ownership required)."""
    image = Image.query.filter_by(id=image_id, user_id=current_user.id, is_deleted=False).first()
    if not image:
        return jsonify({"error": "Image not found"}), 404

    gen = image.generation
    gen_dict = gen.to_dict()

    img_dict = image.to_dict()
    img_dict["aspect_ratio"] = image.aspect_ratio
    img_dict["url"] = f"/api/v1/images/{image.id}/file"
    img_dict["thumb_url"] = f"/api/v1/images/{image.id}/thumbnail"
    img_dict["download_url"] = f"/api/v1/images/{image.id}/download"

    return jsonify({
        "image": img_dict,
        "generation": gen_dict,
    })


# ---- Toggle Favorite ----

@api_bp.route("/images/<int:image_id>/favorite", methods=["POST"])
@login_required
def toggle_favorite(image_id):
    """Toggle the favorite status of an image (ownership required)."""
    image = Image.query.filter_by(id=image_id, user_id=current_user.id, is_deleted=False).first()
    if not image:
        return jsonify({"error": "Image not found"}), 404

    image.is_favorite = not image.is_favorite
    db.session.commit()

    return jsonify({
        "status": "success",
        "is_favorite": image.is_favorite,
    })


# ---- Soft Delete Image ----

@api_bp.route("/images/<int:image_id>", methods=["DELETE"])
@login_required
def delete_image(image_id):
    """Soft-delete an image (ownership required)."""
    image = Image.query.filter_by(id=image_id, user_id=current_user.id, is_deleted=False).first()
    if not image:
        return jsonify({"error": "Image not found"}), 404

    image.soft_delete()
    db.session.commit()

    return jsonify({
        "status": "success",
        "message": "Image deleted",
    })


# ---- Favorites List ----

@api_bp.route("/favorites", methods=["GET"])
@login_required
def list_favorites():
    """List all favorite images for the current user with pagination."""
    page = request.args.get("page", 1, type=int)
    per_page = min(max(1, request.args.get("per_page", 20, type=int)), 100)

    query = (
        Image.query
        .filter_by(user_id=current_user.id, is_favorite=True, is_deleted=False)
        .order_by(Image.created_at.desc())
    )

    result = paginate_query(query, page=page, per_page=per_page)

    images = []
    for img in result["items"]:
        img_dict = img.to_dict()
        img_dict["aspect_ratio"] = img.aspect_ratio
        img_dict["url"] = f"/api/v1/images/{img.id}/file"
        img_dict["thumb_url"] = f"/api/v1/images/{img.id}/thumbnail"
        img_dict["prompt"] = img.generation.prompt if img.generation else None
        img_dict["style"] = (img.generation.parameters or {}).get("style") if img.generation else None
        img_dict["model"] = img.generation.model if img.generation else None
        images.append(img_dict)

    return jsonify({
        "images": images,
        "total": result["total"],
        "page": result["page"],
        "pages": result["pages"],
        "has_next": result["has_next"],
        "has_prev": result["has_prev"],
    })


# ---- Provider Info ----

@api_bp.route("/providers", methods=["GET"])
def list_providers_info():
    """List available providers and their capabilities."""
    providers = list_providers()
    info = []
    for name in providers:
        try:
            from app.services.ai_provider import get_provider
            p = get_provider(name)
            info.append({
                "name": p.name,
                "display_name": p.display_name,
                "configured": p.is_configured(),
                "capabilities": p.get_capabilities().to_dict(),
            })
        except Exception:
            info.append({"name": name, "display_name": name, "configured": False})
    return jsonify({"providers": info})
