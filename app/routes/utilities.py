"""Image utilities API routes — upscale, background removal, image-to-prompt.

Includes batch processing and operation history.
"""

from pathlib import Path

from flask import jsonify, request, send_file
from flask_login import current_user, login_required

from app.extensions import db
from app.models.image import Image
from app.routes import api_bp
from app.services.utilities_service import (
    validate_upload,
    upscale_image,
    remove_background,
    describe_image,
    get_utilities_capabilities,
    batch_upscale,
    batch_describe,
    get_user_history,
    get_batch_status,
)


def _is_valid_image_bytes(data: bytes) -> bool:
    """Check magic bytes to verify the file is actually an image."""
    if len(data) < 8:
        return False
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return True
    if data[:3] == b'\xff\xd8\xff':
        return True
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return True
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return True
    return False


# ============================================================
# CAPABILITIES
# ============================================================


@api_bp.route("/utilities/capabilities", methods=["GET"])
@login_required
def utilities_capabilities():
    """Get utility capabilities for all providers.

    The UI uses this to dynamically show/hide features based on
    what the selected provider actually supports.
    """
    return jsonify({"capabilities": get_utilities_capabilities()})


# ============================================================
# UPSCALE
# ============================================================


@api_bp.route("/utilities/upscale", methods=["POST"])
@login_required
def utilities_upscale():
    """Upscale an image by a given factor.

    POST body: {
        "image_id": 123,
        "scale": 2.0,
        "provider": "stub"
    }

    Returns original and upscaled dimensions.
    Only works if the provider supports upscaling.
    """
    data = request.get_json(silent=True) or {}

    image_id = data.get("image_id")
    scale = data.get("scale", 2.0)
    provider = data.get("provider", "stub")

    if not image_id:
        return jsonify({"error": "image_id is required"}), 400

    try:
        scale = float(scale)
        if scale < 1.0 or scale > 4.0:
            return jsonify({"error": "Scale must be between 1.0 and 4.0"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid scale value"}), 400

    try:
        result = upscale_image(
            image_id=int(image_id),
            user_id=current_user.id,
            scale=scale,
            params={"provider": provider},
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Upscale failed: {str(e)}"}), 500

    return jsonify({
        "status": "success",
        **result,
    })


# ============================================================
# BACKGROUND REMOVAL
# ============================================================


@api_bp.route("/utilities/remove-background", methods=["POST"])
@login_required
def utilities_remove_background():
    """Remove the background from an image.

    POST body: {
        "image_id": 123,
        "provider": "stub"
    }

    Only works if the provider supports background removal.
    Returns a real transparent PNG — never fakes transparency.
    """
    data = request.get_json(silent=True) or {}

    image_id = data.get("image_id")
    provider = data.get("provider", "stub")

    if not image_id:
        return jsonify({"error": "image_id is required"}), 400

    try:
        result = remove_background(
            image_id=int(image_id),
            user_id=current_user.id,
            params={"provider": provider},
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Background removal failed: {str(e)}"}), 500

    return jsonify({
        "status": "success",
        **result,
    })


# ============================================================
# IMAGE-TO-PROMPT / DESCRIPTION
# ============================================================


@api_bp.route("/utilities/describe", methods=["POST"])
@login_required
def utilities_describe():
    """Generate a structured description of an image.

    POST body: {
        "image_id": 123,
        "provider": "stub"
    }

    Returns structured analysis:
      - subject, environment, style, composition,
        lighting, colors, mood, prompt

    Does not claim the generated text will reproduce the original image.
    """
    data = request.get_json(silent=True) or {}

    image_id = data.get("image_id")
    provider = data.get("provider", "stub")

    if not image_id:
        return jsonify({"error": "image_id is required"}), 400

    try:
        result = describe_image(
            image_id=int(image_id),
            user_id=current_user.id,
            params={"provider": provider},
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Image description failed: {str(e)}"}), 500

    return jsonify({
        "status": "success",
        "description": result,
    })


# ============================================================
# UPLOAD FOR UTILITIES
# ============================================================


@api_bp.route("/utilities/upload", methods=["POST"])
@login_required
def utilities_upload():
    """Upload an image for utility processing.

    Validates file type, size, dimensions, and actual content (magic bytes).
    Returns the image ID for use with other utility endpoints.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    is_valid, error_msg, file_bytes = validate_upload(file)

    if not is_valid:
        return jsonify({"error": error_msg}), 400

    # SECURITY: Validate magic bytes — don't trust Content-Type alone
    if not _is_valid_image_bytes(file_bytes):
        return jsonify({"error": "File does not appear to be a valid image"}), 400

    # Get dimensions from the validated bytes
    from app.services.utilities_service import _get_image_dimensions
    width, height = _get_image_dimensions(file_bytes)

    # Save to storage
    from app.config import BASE_DIR
    from app.services.storage_service import StorageService
    from app.services.generation_service import _create_placeholder_svg
    from app.utils import generate_filename
    from app.models.generation import Generation

    # Create a generation record for the upload
    gen = Generation(
        user_id=current_user.id,
        prompt="Uploaded image",
        provider="upload",
        status="completed",
    )
    db.session.add(gen)
    db.session.flush()

    storage = StorageService(str(BASE_DIR / "uploads" / "utilities" / str(current_user.id)))
    filename = generate_filename(file.filename or "upload.png", prefix="util")
    saved = storage.save_bytes(file_bytes, filename, subfolder="images")

    # Create image record
    image = Image(
        generation_id=gen.id,
        user_id=current_user.id,
        filename=saved["filename"],
        original_filename=file.filename,
        file_path=saved["file_path"],
        width=width,
        height=height,
        file_size=saved["file_size"],
    )
    db.session.add(image)
    db.session.commit()

    return jsonify({
        "status": "success",
        "image": {
            "id": image.id,
            "url": f"/api/v1/images/{image.id}/file",
            "width": image.width,
            "height": image.height,
            "filename": image.filename,
        },
    }), 201


# ============================================================
# BATCH PROCESSING
# ============================================================


@api_bp.route("/utilities/batch/upscale", methods=["POST"])
@login_required
def utilities_batch_upscale():
    """Upscale multiple images in a batch.

    POST body: {
        "image_ids": [123, 456, 789],
        "scale": 2.0,
        "provider": "stub"
    }

    Returns a batch_id and all results.
    """
    data = request.get_json(silent=True) or {}

    image_ids = data.get("image_ids", [])
    scale = data.get("scale", 2.0)
    provider = data.get("provider", "stub")

    if not image_ids or not isinstance(image_ids, list):
        return jsonify({"error": "image_ids must be a non-empty list"}), 400

    if len(image_ids) > 20:
        return jsonify({"error": "Maximum 20 images per batch"}), 400

    try:
        scale = float(scale)
        if scale < 1.0 or scale > 4.0:
            return jsonify({"error": "Scale must be between 1.0 and 4.0"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid scale value"}), 400

    try:
        result = batch_upscale(
            image_ids=[int(i) for i in image_ids],
            user_id=current_user.id,
            scale=scale,
            provider=provider,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Batch upscale failed: {str(e)}"}), 500

    return jsonify({"status": "success", **result})


@api_bp.route("/utilities/batch/describe", methods=["POST"])
@login_required
def utilities_batch_describe():
    """Describe multiple images in a batch.

    POST body: {
        "image_ids": [123, 456, 789],
        "provider": "stub"
    }

    Returns a batch_id and all results.
    """
    data = request.get_json(silent=True) or {}

    image_ids = data.get("image_ids", [])
    provider = data.get("provider", "stub")

    if not image_ids or not isinstance(image_ids, list):
        return jsonify({"error": "image_ids must be a non-empty list"}), 400

    if len(image_ids) > 20:
        return jsonify({"error": "Maximum 20 images per batch"}), 400

    try:
        result = batch_describe(
            image_ids=[int(i) for i in image_ids],
            user_id=current_user.id,
            provider=provider,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Batch describe failed: {str(e)}"}), 500

    return jsonify({"status": "success", **result})


# ============================================================
# BATCH STATUS
# ============================================================


@api_bp.route("/utilities/batch/<batch_id>/status", methods=["GET"])
@login_required
def utilities_batch_status(batch_id):
    """Get the status of a batch operation."""
    result = get_batch_status(batch_id, current_user.id)
    if result is None:
        return jsonify({"error": "Batch not found"}), 404
    return jsonify(result)


# ============================================================
# HISTORY
# ============================================================


@api_bp.route("/utilities/history", methods=["GET"])
@login_required
def utilities_history():
    """Get utility operation history for the current user.

    Query params:
        limit: Max results (default 50)
        offset: Pagination offset (default 0)
    """
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    limit = min(max(1, limit), 100)
    offset = max(0, offset)

    result = get_user_history(current_user.id, limit=limit, offset=offset)
    return jsonify(result)
