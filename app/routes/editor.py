"""Editor API routes — local editing, AI editing, versioning, comparison."""

from pathlib import Path

from flask import jsonify, request, send_file
from flask_login import current_user, login_required

from app.extensions import db
from app.models.image import Image
from app.models.image_version import ImageVersion
from app.routes import api_bp
from app.services.editor_service import (
    local_edit,
    ai_edit,
    get_version_history,
    get_version,
    get_latest_version,
    revert_to_version,
    get_comparison_data,
)


# ============================================================
# LOCAL EDITING
# ============================================================


@api_bp.route("/editor/local", methods=["POST"])
@login_required
def apply_local_edit():
    """Apply a local editing operation.

    POST body: {
        "image_id": 123,
        "operation": "crop|resize|rotate|flip|brightness|contrast|saturation|"
                      "blur|sharpen|grayscale|sepia|invert|vignette|duotone|"
                      "edge_detect|pixelate|posterize|warmth|gamma|vibrance|denoise",
        "params": { ... operation-specific params ... }
    }
    """
    data = request.get_json(silent=True) or {}

    image_id = data.get("image_id")
    operation = (data.get("operation") or "").strip()
    params = data.get("params") or {}

    if not image_id:
        return jsonify({"error": "image_id is required"}), 400

    valid_ops = {
        "crop", "resize", "rotate", "flip", "brightness", "contrast", "saturation",
        "blur", "sharpen", "grayscale", "sepia", "invert", "vignette", "duotone",
        "edge_detect", "pixelate", "posterize", "warmth", "gamma", "vibrance", "denoise",
    }
    if operation not in valid_ops:
        return jsonify({
            "error": f"Invalid operation. Valid: {', '.join(sorted(valid_ops))}"
        }), 400

    try:
        version = local_edit(
            image_id=int(image_id),
            user_id=current_user.id,
            operation=operation,
            params=params,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Edit failed: {str(e)}"}), 500

    return jsonify({
        "status": "success",
        "version": version.to_dict(),
    }), 200


# ============================================================
# AI EDITING
# ============================================================


@api_bp.route("/editor/ai", methods=["POST"])
@login_required
def apply_ai_edit():
    """Apply an AI editing operation.

    POST body: {
        "image_id": 123,
        "operation": "inpaint|outpaint|background_replace|retexture",
        "prompt": "what to generate/change",
        "params": { ... operation-specific params ... },
        "mask": "base64 mask data (optional, for inpainting)"
    }
    """
    data = request.get_json(silent=True) or {}

    image_id = data.get("image_id")
    operation = (data.get("operation") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    params = data.get("params") or {}
    mask_data = data.get("mask")

    if not image_id:
        return jsonify({"error": "image_id is required"}), 400

    valid_ops = {"inpaint", "outpaint", "background_replace", "retexture"}
    if operation not in valid_ops:
        return jsonify({
            "error": f"Invalid operation. Valid: {', '.join(sorted(valid_ops))}"
        }), 400

    if not prompt:
        return jsonify({"error": "prompt is required for AI editing"}), 400

    try:
        version = ai_edit(
            image_id=int(image_id),
            user_id=current_user.id,
            operation=operation,
            prompt=prompt,
            params=params,
            mask_data=mask_data,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"AI edit failed: {str(e)}"}), 500

    return jsonify({
        "status": "success",
        "version": version.to_dict(),
    }), 200


# ============================================================
# VERSION MANAGEMENT
# ============================================================


@api_bp.route("/editor/images/<int:image_id>/versions", methods=["GET"])
@login_required
def list_versions(image_id):
    """Get all versions of an image."""
    # Verify image ownership
    image = Image.query.filter_by(
        id=image_id, user_id=current_user.id, is_deleted=False
    ).first()
    if not image:
        return jsonify({"error": "Image not found"}), 404

    versions = get_version_history(image_id, current_user.id)

    return jsonify({
        "versions": versions,
        "total": len(versions),
    })


@api_bp.route("/editor/versions/<int:version_id>", methods=["GET"])
@login_required
def get_version_detail(version_id):
    """Get details of a specific version."""
    version = get_version(version_id, current_user.id)
    if not version:
        return jsonify({"error": "Version not found"}), 404

    return jsonify({"version": version.to_dict()})


@api_bp.route("/editor/versions/<int:version_id>/file", methods=["GET"])
@login_required
def get_version_file(version_id):
    """Serve a version's image file."""
    version = get_version(version_id, current_user.id)
    if not version:
        return jsonify({"error": "Version not found"}), 404

    file_path = Path(version.file_path)
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404

    # SECURITY: Path traversal check
    from flask import current_app
    upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "uploads"))
    try:
        if not file_path.resolve().is_relative_to(upload_root.resolve()):
            return jsonify({"error": "Access denied"}), 403
    except (ValueError, OSError):
        return jsonify({"error": "Access denied"}), 403

    ext = file_path.suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }
    mimetype = mime_map.get(ext, "application/octet-stream")

    return send_file(str(file_path), mimetype=mimetype)


@api_bp.route("/editor/images/<int:image_id>/revert/<int:version_id>", methods=["POST"])
@login_required
def revert_image(image_id, version_id):
    """Revert an image to a specific version.

    Creates a new version instead of deleting current.
    """
    # Verify image ownership
    image = Image.query.filter_by(
        id=image_id, user_id=current_user.id, is_deleted=False
    ).first()
    if not image:
        return jsonify({"error": "Image not found"}), 404

    try:
        version = revert_to_version(image_id, version_id, current_user.id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "status": "success",
        "version": version.to_dict(),
    }), 200


# ============================================================
# BEFORE/AFTER COMPARISON
# ============================================================


@api_bp.route("/editor/images/<int:image_id>/compare/<int:version_id>", methods=["GET"])
@login_required
def compare_versions(image_id, version_id):
    """Get before/after data for comparison slider."""
    # Verify image ownership
    image = Image.query.filter_by(
        id=image_id, user_id=current_user.id, is_deleted=False
    ).first()
    if not image:
        return jsonify({"error": "Image not found"}), 404

    try:
        data = get_comparison_data(image_id, version_id, current_user.id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(data)


# ============================================================
# IMAGE INFO FOR EDITOR
# ============================================================


@api_bp.route("/editor/images/<int:image_id>/info", methods=["GET"])
@login_required
def get_editor_image_info(image_id):
    """Get image info needed for the editor."""
    image = Image.query.filter_by(
        id=image_id, user_id=current_user.id, is_deleted=False
    ).first()
    if not image:
        return jsonify({"error": "Image not found"}), 404

    versions = get_version_history(image_id, current_user.id)
    latest = get_latest_version(image_id, current_user.id)

    return jsonify({
        "image": {
            "id": image.id,
            "url": f"/api/v1/images/{image.id}/file",
            "width": image.width,
            "height": image.height,
            "filename": image.filename,
        },
        "versions": versions,
        "latest_version": latest.to_dict() if latest else None,
        "version_count": len(versions),
    })


# ============================================================
# PROVIDER CAPABILITIES FOR EDITOR
# ============================================================


@api_bp.route("/editor/capabilities", methods=["GET"])
@login_required
def get_editor_capabilities():
    """Get AI editing capabilities for the current provider."""
    from app.services.ai_provider import list_providers, get_provider

    providers = list_providers()
    capabilities = {}

    for name in providers:
        try:
            provider = get_provider(name)
            caps = provider.get_capabilities()
            capabilities[name] = {
                "name": provider.display_name,
                "inpainting": caps.inpainting,
                "outpainting": caps.outpainting,
                "image_edit": caps.image_edit,
                "variations": caps.variations,
                "upscale": caps.upscale,
            }
        except Exception:
            capabilities[name] = {
                "name": name,
                "inpainting": False,
                "outpainting": False,
                "image_edit": False,
                "variations": False,
                "upscale": False,
            }

    return jsonify({"capabilities": capabilities})
