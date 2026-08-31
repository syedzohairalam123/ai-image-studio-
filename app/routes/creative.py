"""Creative controls API routes — style presets, reference images, remix, variations."""

import io
import os
from pathlib import Path

from flask import jsonify, request, send_file
from flask_login import current_user, login_required

from app.extensions import db
from app.config import BASE_DIR
from app.models.style_preset import StylePreset
from app.models.reference_image import ReferenceImage
from app.models.generation import Generation
from app.models.image import Image
from app.routes import api_bp
from app.services.storage_service import StorageService
from app.services.generation_service import run_generation, GenerationError
from app.services.ai_provider import get_provider, list_providers
from app.utils import generate_filename, paginate_query

# Allowed image MIME types
ALLOWED_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_REFERENCE_SIZE = 10 * 1024 * 1024  # 10MB
MIN_DIMENSION = 64
MAX_DIMENSION = 4096


# ============================================================
# STYLE CATEGORIES (built-in)
# ============================================================

STYLE_CATEGORIES = [
    {"id": "photography", "name": "Photography", "icon": "📷", "styles": ["photo", "portrait", "landscape", "macro", "street", "aerial"]},
    {"id": "digital_art", "name": "Digital Art", "icon": "🖌️", "styles": ["art", "concept", "illustration", "painting"]},
    {"id": "traditional_art", "name": "Traditional Art", "icon": "🎨", "styles": ["paint", "watercolor", "oil", "sketch", "charcoal"]},
    {"id": "illustration", "name": "Illustration", "icon": "✏️", "styles": ["anime", "manga", "comic", "storybook"]},
    {"id": "cinematic", "name": "Cinematic", "icon": "🎬", "styles": ["film", "noir", "retro", "sci-fi-cinema"]},
    {"id": "architecture", "name": "Architecture", "icon": "🏛️", "styles": ["modern", "classical", "brutalist", "futuristic"]},
    {"id": "product", "name": "Product", "icon": "📦", "styles": ["minimal", "commercial", "lifestyle"]},
    {"id": "minimal", "name": "Minimal", "icon": "📐", "styles": ["clean", "geometric", "flat"]},
    {"id": "fantasy", "name": "Fantasy", "icon": "🧙", "styles": ["medieval", "magical", "ethereal", "dark-fantasy"]},
    {"id": "sci_fi", "name": "Science Fiction", "icon": "🚀", "styles": ["cyberpunk", "space", "mech", "alien"]},
]


# ============================================================
# STYLE CATEGORIES ENDPOINT
# ============================================================

@api_bp.route("/styles/categories", methods=["GET"])
@login_required
def list_style_categories():
    """List built-in style categories."""
    return jsonify({"categories": STYLE_CATEGORIES})


# ============================================================
# STYLE PRESETS CRUD
# ============================================================

@api_bp.route("/style-presets", methods=["GET"])
@login_required
def list_style_presets():
    """List user's style presets with filtering."""
    category = request.args.get("category", "").strip()
    search = request.args.get("search", "").strip()

    query = StylePreset.query.filter_by(user_id=current_user.id)

    if category:
        query = query.filter_by(category=category)
    if search:
        query = query.filter(StylePreset.name.ilike(f"%{search}%"))

    query = query.order_by(StylePreset.name.asc())
    presets = [p.to_dict() for p in query.all()]

    return jsonify({"presets": presets})


@api_bp.route("/style-presets", methods=["POST"])
@login_required
def create_style_preset():
    """Create a new style preset.

    POST body: { "name": "...", "category": "custom", "style": "...",
                  "negative_prompt": "...", "prompt_prefix": "...",
                  "prompt_suffix": "...", "settings": {...} }
    """
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    if len(name) > 100:
        return jsonify({"error": "Name must be 100 characters or fewer"}), 400

    category = (data.get("category") or "custom").strip()
    style = (data.get("style") or "").strip() or None
    negative_prompt = (data.get("negative_prompt") or "").strip() or None
    prompt_prefix = (data.get("prompt_prefix") or "").strip() or None
    prompt_suffix = (data.get("prompt_suffix") or "").strip() or None
    settings = data.get("settings") or {}

    preset = StylePreset(
        user_id=current_user.id,
        name=name,
        category=category,
        style=style,
        negative_prompt=negative_prompt,
        prompt_prefix=prompt_prefix,
        prompt_suffix=prompt_suffix,
        settings=settings,
    )
    db.session.add(preset)
    db.session.commit()

    return jsonify(preset.to_dict()), 201


@api_bp.route("/style-presets/<int:preset_id>", methods=["GET"])
@login_required
def get_style_preset(preset_id):
    """Get a single style preset."""
    preset = StylePreset.query.filter_by(id=preset_id, user_id=current_user.id).first()
    if not preset:
        return jsonify({"error": "Preset not found"}), 404
    return jsonify(preset.to_dict())


@api_bp.route("/style-presets/<int:preset_id>", methods=["PUT"])
@login_required
def update_style_preset(preset_id):
    """Update a style preset."""
    preset = StylePreset.query.filter_by(id=preset_id, user_id=current_user.id).first()
    if not preset:
        return jsonify({"error": "Preset not found"}), 404

    data = request.get_json(silent=True) or {}

    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            return jsonify({"error": "Name cannot be empty"}), 400
        preset.name = name

    if "category" in data:
        preset.category = (data["category"] or "custom").strip()
    if "style" in data:
        preset.style = (data["style"] or "").strip() or None
    if "negative_prompt" in data:
        preset.negative_prompt = (data["negative_prompt"] or "").strip() or None
    if "prompt_prefix" in data:
        preset.prompt_prefix = (data["prompt_prefix"] or "").strip() or None
    if "prompt_suffix" in data:
        preset.prompt_suffix = (data["prompt_suffix"] or "").strip() or None
    if "settings" in data:
        preset.settings = data["settings"] or {}

    db.session.commit()
    return jsonify(preset.to_dict())


@api_bp.route("/style-presets/<int:preset_id>", methods=["DELETE"])
@login_required
def delete_style_preset(preset_id):
    """Delete a style preset."""
    preset = StylePreset.query.filter_by(id=preset_id, user_id=current_user.id).first()
    if not preset:
        return jsonify({"error": "Preset not found"}), 404

    db.session.delete(preset)
    db.session.commit()

    return jsonify({"status": "success", "message": "Preset deleted"})


@api_bp.route("/style-presets/<int:preset_id>/duplicate", methods=["POST"])
@login_required
def duplicate_style_preset(preset_id):
    """Duplicate a style preset."""
    original = StylePreset.query.filter_by(id=preset_id, user_id=current_user.id).first()
    if not original:
        return jsonify({"error": "Preset not found"}), 404

    dup = StylePreset(
        user_id=current_user.id,
        name=f"{original.name} (copy)",
        category=original.category,
        style=original.style,
        negative_prompt=original.negative_prompt,
        prompt_prefix=original.prompt_prefix,
        prompt_suffix=original.prompt_suffix,
        settings=dict(original.settings) if original.settings else {},
    )
    db.session.add(dup)
    db.session.commit()

    return jsonify(dup.to_dict()), 201


# ============================================================
# REFERENCE IMAGES
# ============================================================

@api_bp.route("/references", methods=["GET"])
@login_required
def list_references():
    """List user's reference images."""
    refs = (
        ReferenceImage.query
        .filter_by(user_id=current_user.id, is_deleted=False)
        .order_by(ReferenceImage.created_at.desc())
        .all()
    )
    return jsonify({"references": [r.to_dict() for r in refs]})


@api_bp.route("/references/upload", methods=["POST"])
@login_required
def upload_reference():
    """Upload a reference image with validation.

    Validates: MIME type, actual image content, file size, dimensions.
    Does NOT trust filename extensions.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    # Validate MIME type from Content-Type header
    mime = file.content_type
    if not mime or mime not in ALLOWED_MIMES:
        return jsonify({
            "error": f"Invalid file type. Allowed: {', '.join(ALLOWED_MIMES)}"
        }), 400

    # Read file bytes
    file_bytes = file.read()
    if not file_bytes:
        return jsonify({"error": "Empty file"}), 400

    # Validate actual image content (magic bytes)
    if not _is_valid_image_bytes(file_bytes):
        return jsonify({"error": "File does not appear to be a valid image"}), 400

    # Validate file size
    if len(file_bytes) > MAX_REFERENCE_SIZE:
        return jsonify({
            "error": f"File too large. Maximum size is {MAX_REFERENCE_SIZE // (1024*1024)}MB"
        }), 400

    # Validate dimensions
    width, height = _get_image_dimensions(file_bytes)
    if width and height:
        if width < MIN_DIMENSION or height < MIN_DIMENSION:
            return jsonify({"error": f"Image too small. Minimum dimension is {MIN_DIMENSION}px"}), 400
        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            return jsonify({"error": f"Image too large. Maximum dimension is {MAX_DIMENSION}px"}), 400

    # Save to storage
    storage = StorageService(str(BASE_DIR / "uploads" / "references" / str(current_user.id)))
    filename = generate_filename(file.filename, prefix="ref")
    result = storage.save_bytes(file_bytes, filename, subfolder="images")

    ref = ReferenceImage(
        user_id=current_user.id,
        filename=result["filename"],
        file_path=result["file_path"],
        original_filename=file.filename,
        file_size=len(file_bytes),
        width=width,
        height=height,
        mime_type=mime,
    )
    db.session.add(ref)
    db.session.commit()

    return jsonify(ref.to_dict()), 201


@api_bp.route("/references/<int:ref_id>/file", methods=["GET"])
@login_required
def get_reference_file(ref_id):
    """Serve a reference image file (ownership required)."""
    ref = ReferenceImage.query.filter_by(
        id=ref_id, user_id=current_user.id, is_deleted=False
    ).first()
    if not ref:
        return jsonify({"error": "Reference not found"}), 404

    file_path = Path(ref.file_path)
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

    return send_file(str(file_path), mimetype=ref.mime_type or "application/octet-stream")


@api_bp.route("/references/<int:ref_id>", methods=["DELETE"])
@login_required
def delete_reference(ref_id):
    """Soft-delete a reference image."""
    ref = ReferenceImage.query.filter_by(
        id=ref_id, user_id=current_user.id, is_deleted=False
    ).first()
    if not ref:
        return jsonify({"error": "Reference not found"}), 404

    ref.soft_delete()
    db.session.commit()

    return jsonify({"status": "success", "message": "Reference deleted"})


@api_bp.route("/references/<int:ref_id>/permanent", methods=["POST"])
@login_required
def toggle_reference_permanent(ref_id):
    """Toggle permanent status of a reference (prevents cleanup)."""
    ref = ReferenceImage.query.filter_by(
        id=ref_id, user_id=current_user.id, is_deleted=False
    ).first()
    if not ref:
        return jsonify({"error": "Reference not found"}), 404

    ref.is_permanent = not ref.is_permanent
    db.session.commit()

    return jsonify({"status": "success", "is_permanent": ref.is_permanent})


# ============================================================
# REMIX
# ============================================================

@api_bp.route("/images/<int:image_id>/remix", methods=["POST"])
@login_required
def remix_image(image_id):
    """Remix an existing image — opens generator with its settings as defaults.

    POST body: { "reference_strength": 0.5 }  (optional)
    Returns the generation settings to prefill the generator.
    """
    image = Image.query.filter_by(
        id=image_id, user_id=current_user.id, is_deleted=False
    ).first()
    if not image:
        return jsonify({"error": "Image not found"}), 404

    gen = image.generation
    params = gen.parameters or {}

    result = {
        "prompt": gen.prompt,
        "negative_prompt": gen.negative_prompt,
        "style": params.get("style", "auto"),
        "aspect_ratio": params.get("aspect_ratio", "1:1"),
        "quality": params.get("quality", "standard"),
        "seed": params.get("seed"),
        "provider": gen.provider,
        "reference_image_id": image.id,
        "reference_url": f"/api/v1/images/{image.id}/file",
    }

    data = request.get_json(silent=True) or {}
    if "reference_strength" in data:
        try:
            result["reference_strength"] = max(0.0, min(1.0, float(data["reference_strength"])))
        except (TypeError, ValueError):
            result["reference_strength"] = 0.7
    else:
        result["reference_strength"] = 0.7

    return jsonify(result)


# ============================================================
# VARIATIONS
# ============================================================

@api_bp.route("/images/<int:image_id>/variations", methods=["POST"])
@login_required
def generate_variations(image_id):
    """Generate variations of an existing image.

    Creates independent new images based on the original.
    Only works if provider supports variations.
    """
    image = Image.query.filter_by(
        id=image_id, user_id=current_user.id, is_deleted=False
    ).first()
    if not image:
        return jsonify({"error": "Image not found"}), 404

    gen = image.generation
    params = gen.parameters or {}

    data = request.get_json(silent=True) or {}
    count = min(max(1, data.get("count", 1)), 4)

    # Check provider supports variations
    provider_name = gen.provider or "stub"
    try:
        provider = get_provider(provider_name)
        if not provider.supports("variations"):
            return jsonify({
                "error": f"Provider '{provider_name}' does not support variations",
                "status_code": 400
            }), 400
    except ValueError:
        return jsonify({"error": f"Provider '{provider_name}' not available"}), 400

    # Build generation data
    gen_data = {
        "prompt": gen.prompt,
        "style": params.get("style", "auto"),
        "aspect_ratio": params.get("aspect_ratio", "1:1"),
        "quality": params.get("quality", "standard"),
        "count": count,
        "negative_prompt": gen.negative_prompt,
        "seed": params.get("seed"),
    }

    # Include reference image if available
    if image.file_path:
        gen_data["reference_image_path"] = image.file_path

    try:
        generation = run_generation(current_user.id, gen_data)
    except GenerationError as e:
        return jsonify({"error": e.message, "status_code": e.status_code}), e.status_code
    except Exception as e:
        return jsonify({"error": "An unexpected error occurred", "status_code": 500}), 500

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
        "source_image_id": image.id,
    }), 200


# ============================================================
# USE AS REFERENCE (from existing generated image)
# ============================================================

@api_bp.route("/images/<int:image_id>/as-reference", methods=["POST"])
@login_required
def use_as_reference(image_id):
    """Convert an existing generated image into a reference image."""
    image = Image.query.filter_by(
        id=image_id, user_id=current_user.id, is_deleted=False
    ).first()
    if not image:
        return jsonify({"error": "Image not found"}), 404

    file_path = Path(image.file_path)
    if not file_path.exists():
        return jsonify({"error": "Image file not found"}), 404

    # Check if already a reference for this user
    existing = ReferenceImage.query.filter_by(
        user_id=current_user.id,
        file_path=image.file_path,
        is_deleted=False,
    ).first()
    if existing:
        return jsonify(existing.to_dict()), 200

    ref = ReferenceImage(
        user_id=current_user.id,
        filename=image.filename,
        file_path=image.file_path,
        original_filename=image.original_filename,
        file_size=image.file_size,
        width=image.width,
        height=image.height,
        mime_type="image/png",
        is_permanent=True,
    )
    db.session.add(ref)
    db.session.commit()

    return jsonify(ref.to_dict()), 201


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _is_valid_image_bytes(data: bytes) -> bool:
    """Check magic bytes to verify the file is actually an image."""
    if len(data) < 8:
        return False

    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return True
    # JPEG: FF D8 FF
    if data[:3] == b'\xff\xd8\xff':
        return True
    # WebP: RIFF....WEBP
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return True
    # GIF: GIF87a or GIF89a
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return True

    return False


def _get_image_dimensions(data: bytes) -> tuple:
    """Extract image dimensions from raw bytes. Returns (width, height) or (None, None)."""
    try:
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            # PNG - read IHDR chunk
            import struct
            if len(data) >= 24:
                width = struct.unpack('>I', data[16:20])[0]
                height = struct.unpack('>I', data[20:24])[0]
                return (width, height)
        elif data[:3] == b'\xff\xd8\xff':
            # JPEG - parse markers
            return _parse_jpeg_dimensions(data)
        elif data[:4] == b'RIFF' and len(data) >= 20:
            # WebP - check VP8 chunk
            import struct
            if data[12:16] == b'VP8 ' and len(data) >= 30:
                width = struct.unpack('<H', data[26:28])[0] & 0x3FFF
                height = struct.unpack('<H', data[28:30])[0] & 0x3FFF
                return (width, height)
            elif data[12:16] == b'VP8L' and len(data) >= 25:
                bits = struct.unpack('<I', data[21:25])[0]
                width = (bits & 0x3FFF) + 1
                height = ((bits >> 14) & 0x3FFF) + 1
                return (width, height)
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            # GIF
            import struct
            if len(data) >= 10:
                width = struct.unpack('<H', data[6:8])[0]
                height = struct.unpack('<H', data[8:10])[0]
                return (width, height)
    except Exception:
        pass

    return (None, None)


def _parse_jpeg_dimensions(data: bytes) -> tuple:
    """Parse JPEG SOF marker to get dimensions."""
    try:
        import struct
        i = 2
        while i < len(data) - 1:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker == 0xD8 or marker == 0xD9:  # SOI/EOI
                i += 2
                continue
            if marker == 0x00:
                i += 1
                continue

            length = struct.unpack('>H', data[i + 2:i + 4])[0] if i + 3 < len(data) else 0

            # SOF0-SOF3 markers
            if 0xC0 <= marker <= 0xC3 and i + 9 < len(data):
                height = struct.unpack('>H', data[i + 5:i + 7])[0]
                width = struct.unpack('>H', data[i + 7:i + 9])[0]
                return (width, height)

            i += 2 + length
    except Exception:
        pass

    return (None, None)
