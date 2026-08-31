"""Image utilities service — upscale, background removal, image-to-prompt.

These operations require the selected provider to actually support them.
Stub provider returns placeholder results for development/testing.

Supports batch processing and operation history tracking.
"""

import io
import uuid
import base64
from pathlib import Path
from typing import Optional

from app.extensions import db
from app.config import BASE_DIR
from app.models.image import Image
from app.models.image_version import ImageVersion
from app.models.utility_operation import UtilityOperation
from app.services.storage_service import StorageService
from app.services.ai_provider import get_provider, list_providers, register_provider
from app.utils import generate_filename, now_utc

# Import and register real providers
try:
    from app.services.providers.rembg_provider import RembgProvider
    register_provider("rembg", RembgProvider)
except ImportError:
    pass

try:
    from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider
    register_provider("pillow_upscale", PillowUpscaleProvider)
except ImportError:
    pass


# ============================================================
# UPLOAD VALIDATION
# ============================================================

ALLOWED_UPLOAD_MIMES = {
    "image/png", "image/jpeg", "image/webp", "image/gif",
}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
MIN_DIMENSION = 64
MAX_DIMENSION = 4096


def validate_upload(file_storage) -> tuple:
    """Validate an uploaded file. Returns (is_valid, error_message, file_bytes)."""
    if not file_storage or not file_storage.filename:
        return False, "No file provided", None

    mime = file_storage.content_type
    if not mime or mime not in ALLOWED_UPLOAD_MIMES:
        return False, f"Invalid file type. Allowed: {', '.join(sorted(ALLOWED_UPLOAD_MIMES))}", None

    file_bytes = file_storage.read()
    if not file_bytes:
        return False, "Empty file", None

    # Validate magic bytes
    if not _is_valid_image_bytes(file_bytes):
        return False, "File does not appear to be a valid image", None

    if len(file_bytes) > MAX_UPLOAD_SIZE:
        return False, f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024*1024)}MB", None

    # Validate dimensions
    width, height = _get_image_dimensions(file_bytes)
    if width and height:
        if width < MIN_DIMENSION or height < MIN_DIMENSION:
            return False, f"Image too small. Minimum dimension is {MIN_DIMENSION}px", None
        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            return False, f"Image too large. Maximum dimension is {MAX_DIMENSION}px", None

    return True, None, file_bytes


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


def _get_image_dimensions(data: bytes) -> tuple:
    """Extract image dimensions from raw bytes. Returns (width, height) or (None, None)."""
    try:
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            import struct
            if len(data) >= 24:
                width = struct.unpack('>I', data[16:20])[0]
                height = struct.unpack('>I', data[20:24])[0]
                return (width, height)
        elif data[:3] == b'\xff\xd8\xff':
            return _parse_jpeg_dimensions(data)
        elif data[:4] == b'RIFF' and len(data) >= 20:
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
            if marker == 0xD8 or marker == 0xD9:
                i += 2
                continue
            if marker == 0x00:
                i += 1
                continue
            length = struct.unpack('>H', data[i + 2:i + 4])[0] if i + 3 < len(data) else 0
            if 0xC0 <= marker <= 0xC3 and i + 9 < len(data):
                height = struct.unpack('>H', data[i + 5:i + 7])[0]
                width = struct.unpack('>H', data[i + 7:i + 9])[0]
                return (width, height)
            i += 2 + length
    except Exception:
        pass
    return (None, None)


# ============================================================
# UPSCALE
# ============================================================


def upscale_image(image_id: int, user_id: int, scale: float = 2.0, params: dict = None) -> dict:
    """Upscale an image by a given factor.

    Args:
        image_id: Source image ID
        user_id: Current user ID
        scale: Upscale factor (2.0 = 2x)
        params: Additional parameters including provider name

    Returns:
        Dict with result image info

    Raises:
        ValueError: If image not found, file missing, or provider doesn't support upscale
    """
    from PIL import Image as PILImage

    image = Image.query.filter_by(
        id=image_id, user_id=user_id, is_deleted=False
    ).first()
    if not image:
        raise ValueError("Image not found")

    source_path = Path(image.file_path)
    if not source_path.exists():
        raise ValueError("Image file not found")

    # Get provider
    provider_name = (params or {}).get("provider", "stub")
    try:
        provider = get_provider(provider_name)
    except ValueError:
        raise ValueError(f"Provider '{provider_name}' not available")

    # Check capability
    if not provider.supports("upscale"):
        raise ValueError(
            f"Provider '{provider_name}' does not support upscaling. "
            "Choose a provider that supports this feature."
        )

    # Clamp scale
    scale = max(1.5, min(4.0, float(scale)))

    original_width = image.width or 512
    original_height = image.height or 512
    target_width = int(original_width * scale)
    target_height = int(original_height * scale)

    # Limit output size
    target_width = min(target_width, 4096)
    target_height = min(target_height, 4096)

    # Read source image bytes
    source_bytes = source_path.read_bytes()

    # Use real provider if available, otherwise fallback to stub
    if provider_name == "pillow_upscale":
        result = provider.upscale(
            source_bytes,
            scale=scale,
            sharpen=True,
            output_format="png",
        )
    else:
        # Stub/fallback: use Pillow LANCZOS
        result = _stub_upscale(source_path, target_width, target_height)

    # Save result
    storage = StorageService(str(BASE_DIR / "uploads" / "utilities" / str(user_id)))
    filename = generate_filename(source_path.name, prefix=f"upscale_{int(scale)}x")
    saved = storage.save_bytes(result["bytes"], filename, subfolder="images")

    # Create version record
    original_version = _get_or_create_original_version(image, user_id)
    next_version = _get_next_version_number(image_id)

    version = ImageVersion(
        image_id=image_id,
        user_id=user_id,
        version_number=next_version,
        parent_version_id=original_version.id if original_version else None,
        filename=saved["filename"],
        file_path=saved["file_path"],
        width=result["width"],
        height=result["height"],
        file_size=saved["file_size"],
        edit_type="upscale",
        edit_params={"scale": scale, "original_width": original_width, "original_height": original_height},
        edit_description=f"Upscaled {int(scale)}x ({original_width}×{original_height} → {result['width']}×{result['height']})",
    )
    db.session.add(version)
    db.session.commit()

    # Track in history
    op = _start_operation(
        user_id=user_id, operation="upscale", provider=provider_name,
        image_id=image_id, params={"scale": scale},
    )
    _complete_operation(op, {
        "version_id": version.id,
        "original_width": original_width,
        "original_height": original_height,
        "upscaled_width": result["width"],
        "upscaled_height": result["height"],
    })

    return {
        "version": version.to_dict(),
        "original_width": original_width,
        "original_height": original_height,
        "upscaled_width": result["width"],
        "upscaled_height": result["height"],
        "scale": scale,
    }


def _stub_upscale(source_path: Path, target_width: int, target_height: int) -> dict:
    """Stub upscale using Pillow LANCZOS."""
    from PIL import Image as PILImage

    img = PILImage.open(source_path)
    img = img.resize((target_width, target_height), PILImage.LANCZOS)

    buf = io.BytesIO()
    if img.mode == "RGBA":
        img.save(buf, format="PNG", optimize=True)
    else:
        if img.mode == "RGBA":
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=95, optimize=True)
    buf.seek(0)

    return {
        "bytes": buf.read(),
        "width": img.width,
        "height": img.height,
    }


# ============================================================
# BACKGROUND REMOVAL
# ============================================================


def remove_background(image_id: int, user_id: int, params: dict = None) -> dict:
    """Remove the background from an image.

    Only succeeds if the provider actually supports background removal.
    Returns a real transparent PNG when the provider supports it.

    Raises:
        ValueError: If provider doesn't support background removal
    """
    from PIL import Image as PILImage

    image = Image.query.filter_by(
        id=image_id, user_id=user_id, is_deleted=False
    ).first()
    if not image:
        raise ValueError("Image not found")

    source_path = Path(image.file_path)
    if not source_path.exists():
        raise ValueError("Image file not found")

    # Get provider
    provider_name = (params or {}).get("provider", "stub")
    try:
        provider = get_provider(provider_name)
    except ValueError:
        raise ValueError(f"Provider '{provider_name}' not available")

    # Check capability
    if not provider.supports("background_removal"):
        raise ValueError(
            f"Provider '{provider_name}' does not support background removal. "
            "Choose a provider that supports this feature (e.g., one with real alpha-channel output)."
        )

    # For stub provider, return a meaningful error since we can't fake transparency
    if provider_name == "stub":
        raise ValueError(
            "Background removal requires a real AI provider. "
            "The stub provider cannot perform actual background removal. "
            "Install rembg: pip install rembg"
        )

    # Use rembg provider
    if provider_name == "rembg":
        source_bytes = source_path.read_bytes()
        result = provider.remove_background(source_bytes)

        # Save result as transparent PNG
        storage = StorageService(str(BASE_DIR / "uploads" / "utilities" / str(user_id)))
        filename = generate_filename(source_path.name, prefix="bgremove")
        saved = storage.save_bytes(result["bytes"], filename, subfolder="images")

        # Create version record
        original_version = _get_or_create_original_version(image, user_id)
        next_version = _get_next_version_number(image_id)

        version = ImageVersion(
            image_id=image_id,
            user_id=user_id,
            version_number=next_version,
            parent_version_id=original_version.id if original_version else None,
            filename=saved["filename"],
            file_path=saved["file_path"],
            width=result["width"],
            height=result["height"],
            file_size=saved["file_size"],
            edit_type="bg_remove",
            edit_params={"model": result.get("model", "unknown")},
            edit_description=f"Background removed using {result.get('model', 'unknown')} model",
        )
        db.session.add(version)
        db.session.commit()

        return {
            "version": version.to_dict(),
            "width": result["width"],
            "height": result["height"],
            "model": result.get("model"),
            "has_alpha": result.get("has_alpha", True),
        }

    raise ValueError(f"Background removal not implemented for provider '{provider_name}'")


# ============================================================
# IMAGE-TO-PROMPT / IMAGE DESCRIPTION
# ============================================================


def describe_image(image_id: int, user_id: int, params: dict = None) -> dict:
    """Generate a structured description of an image.

    Returns a structured analysis with subject, environment, style,
    composition, lighting, colors, and mood.

    Raises:
        ValueError: If image not found or provider doesn't support image understanding
    """
    image = Image.query.filter_by(
        id=image_id, user_id=user_id, is_deleted=False
    ).first()
    if not image:
        raise ValueError("Image not found")

    source_path = Path(image.file_path)
    if not source_path.exists():
        raise ValueError("Image file not found")

    # Get provider
    provider_name = (params or {}).get("provider", "stub")
    try:
        provider = get_provider(provider_name)
    except ValueError:
        raise ValueError(f"Provider '{provider_name}' not available")

    # Check capability
    if not provider.supports("image_understanding"):
        raise ValueError(
            f"Provider '{provider_name}' does not support image understanding. "
            "Choose a provider that supports this feature."
        )

    # For stub provider, return a structured description grounded in real
    # pixel analysis of the actual saved file (see _stub_describe_image).
    if provider_name == "stub":
        result = _stub_describe_image(image, source_path)
    else:
        # Real provider would analyze the image here
        result = _stub_describe_image(image, source_path)

    # Track in history
    op = _start_operation(
        user_id=user_id, operation="describe", provider=provider_name,
        image_id=image_id, params={},
    )
    _complete_operation(op, result)

    return result


def _stub_describe_image(image: Image, source_path: Path = None) -> dict:
    """Structured image description.

    Previously this never looked at the actual image at all — subject,
    lighting, colors, composition, and mood were all templated strings
    derived purely from the stored prompt/style text. It now runs real
    pixel-level analysis (dominant colors via k-means, brightness/contrast,
    sharpness, a colourfulness score, rule-of-thirds focus, face detection)
    on the actual saved file and uses that for lighting/colors/composition/
    mood, while still using the stored prompt/style for subject/environment
    (which genuinely can't be read back out of pixels alone). If the file
    can't be analyzed for any reason, this falls back to the original
    template-only behaviour so describe_image never hard-fails.
    """
    prompt = image.prompt or "An image"
    style = image.style or "unknown"
    width = image.width or 512
    height = image.height or 512

    if source_path is None:
        source_path = Path(image.file_path) if image.file_path else None

    pixel_stats = None
    if source_path and Path(source_path).exists():
        try:
            pixel_stats = _analyze_pixels(Path(source_path))
        except Exception:
            pixel_stats = None

    if pixel_stats:
        colors_desc = _describe_colors(pixel_stats)
        lighting_desc = _describe_lighting(pixel_stats)
        mood = pixel_stats["mood"]
        composition = _describe_composition(pixel_stats, width, height)
        disclaimer = (
            "Subject/environment are drawn from generation metadata; colors, "
            "lighting, composition, and mood are computed from the actual "
            "image pixels (dominant-color clustering, brightness/contrast, "
            "edge-based composition analysis)."
        )
    else:
        colors_desc = "Varied color palette based on the prompt and style"
        lighting_desc = "Standard AI-generated lighting"
        mood = f"Creative {style} mood"
        composition = _guess_composition(width, height)
        disclaimer = (
            "This is a placeholder description — the image file could not "
            "be analyzed, so this falls back to metadata only."
        )

    description = {
        "subject": prompt[:200] if prompt else "Unknown subject",
        "environment": f"Generated image environment with {style} style",
        "style": style,
        "composition": composition,
        "lighting": lighting_desc,
        "colors": colors_desc,
        "mood": mood,
        "prompt": f"A detailed {style} image: {prompt}",
        "is_stub": True,
        "pixel_analysis": pixel_stats,
        "disclaimer": disclaimer,
    }

    return description


def _analyze_pixels(path: Path) -> dict:
    """Real pixel-level analysis: dominant colors (k-means), brightness,
    contrast, sharpness, colourfulness, warm/cool mood, face detection, and
    a rule-of-thirds composition read. Reuses the same well-tested numpy/
    OpenCV routines the Advanced AI analyze endpoint uses."""
    from PIL import Image as PILImage
    import numpy as np
    from app.services.advanced_ai_service import (
        _kmeans_dominant_colors, _mood_from_stats,
        _measure_sharpness, _measure_contrast, _detect_faces,
    )

    img = PILImage.open(path).convert("RGB")
    sample = img.copy()
    sample.thumbnail((160, 160))
    arr = np.asarray(sample, dtype=np.float32).reshape(-1, 3)

    avg = arr.mean(axis=0)
    brightness = float(avg.mean()) / 255
    warmth = float(avg[0] / (avg[0] + avg[2] + 1))
    coolness = float(avg[2] / (avg[0] + avg[2] + 1))

    rg = arr[:, 0] - arr[:, 1]
    yb = 0.5 * (arr[:, 0] + arr[:, 1]) - arr[:, 2]
    colorfulness = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) +
                          0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))

    dominant_colors = _kmeans_dominant_colors(arr, k=5)
    mood = _mood_from_stats(warmth, coolness, brightness, colorfulness)
    faces = _detect_faces(img)

    return {
        "width": img.width,
        "height": img.height,
        "brightness": round(brightness, 3),
        "contrast": round(_measure_contrast(img), 3),
        "sharpness": round(_measure_sharpness(img), 2),
        "colorfulness": round(colorfulness, 2),
        "warmth": round(warmth, 3),
        "coolness": round(coolness, 3),
        "dominant_colors": dominant_colors,
        "mood": mood,
        "face_boxes": faces,
        "faces_detected": len(faces),
        "rule_of_thirds_focus": _rule_of_thirds_energy(img),
    }


_NAMED_COLORS = {
    "red": (196, 44, 44), "orange": (219, 118, 38), "yellow": (219, 194, 45),
    "yellow-green": (150, 189, 60), "green": (58, 145, 65), "teal": (40, 150, 140),
    "cyan": (60, 180, 200), "blue": (48, 96, 190), "indigo": (80, 60, 170),
    "purple": (130, 60, 170), "magenta": (180, 55, 160), "pink": (222, 120, 160),
    "brown": (120, 80, 50), "gray": (128, 128, 128), "black": (24, 24, 24),
    "white": (240, 240, 240),
}


def _nearest_color_name(rgb) -> str:
    r, g, b = rgb
    best_name, best_dist = "gray", float("inf")
    for name, (nr, ng, nb) in _NAMED_COLORS.items():
        dist = (r - nr) ** 2 + (g - ng) ** 2 + (b - nb) ** 2
        if dist < best_dist:
            best_dist, best_name = dist, name
    return best_name


def _describe_colors(stats: dict) -> str:
    dominant = stats.get("dominant_colors") or []
    if not dominant:
        return "Varied color palette"
    names = []
    for entry in dominant[:3]:
        name = _nearest_color_name(entry["color"])
        if name not in names:
            names.append(name)
    palette = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    return f"{palette} tones (colorfulness {stats['colorfulness']})"


def _describe_lighting(stats: dict) -> str:
    brightness, contrast = stats["brightness"], stats["contrast"]
    if brightness > 0.72:
        base = "Bright, high-key lighting"
    elif brightness < 0.28:
        base = "Dark, low-key lighting"
    else:
        base = "Balanced, mid-tone lighting"
    if contrast > 0.5:
        base += " with strong contrast"
    elif contrast < 0.18:
        base += " with soft, flat contrast"
    return base


def _describe_composition(stats: dict, width: int, height: int) -> str:
    parts = [_guess_composition(width, height)]
    faces = stats.get("faces_detected", 0)
    if faces:
        parts.append(f"{faces} face{'s' if faces != 1 else ''} detected")
    focus = stats.get("rule_of_thirds_focus")
    if focus and focus != "center":
        parts.append(f"visual weight toward the {focus.replace('-', ' ')}")
    return "; ".join(parts)


def _rule_of_thirds_energy(img) -> str:
    """Which third of the frame has the most visual "energy" (edge
    density) — a real, if simple, composition signal."""
    import numpy as np
    try:
        import cv2
        gray = np.array(img.convert("L"))
        edges = cv2.Canny(gray, 60, 160).astype(np.float32)
    except Exception:
        gray = np.asarray(img.convert("L"), dtype=np.float32)
        edges = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1])) + \
                np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))

    h, w = edges.shape
    rows = [0, h // 3, 2 * h // 3, h]
    cols = [0, w // 3, 2 * w // 3, w]
    grid_labels = [
        ["upper-left", "upper-center", "upper-right"],
        ["middle-left", "center", "middle-right"],
        ["lower-left", "lower-center", "lower-right"],
    ]
    best_score, best_label = -1.0, "center"
    for ri in range(3):
        for ci in range(3):
            cell = edges[rows[ri]:rows[ri + 1], cols[ci]:cols[ci + 1]]
            score = float(cell.mean()) if cell.size else 0.0
            if score > best_score:
                best_score, best_label = score, grid_labels[ri][ci]
    return best_label


def _guess_composition(width: int, height: int) -> str:
    """Guess composition based on aspect ratio."""
    if width == 0 or height == 0:
        return "Unknown composition"
    ratio = width / height
    if ratio > 1.5:
        return "Landscape orientation, wide composition"
    elif ratio < 0.67:
        return "Portrait orientation, tall composition"
    else:
        return "Square or near-square composition"


# ============================================================
# HISTORY TRACKING HELPERS
# ============================================================


def _start_operation(user_id: int, operation: str, provider: str,
                     image_id: int = None, params: dict = None,
                     batch_id: str = None, batch_total: int = None) -> UtilityOperation:
    """Create and commit a new operation record in 'processing' state."""
    op = UtilityOperation(
        user_id=user_id,
        image_id=image_id,
        operation=operation,
        provider=provider,
        status="processing",
        params=params or {},
        started_at=now_utc(),
        batch_id=batch_id,
        batch_total=batch_total,
        batch_completed=0,
        batch_failed=0,
    )
    db.session.add(op)
    db.session.commit()
    return op


def _complete_operation(op: UtilityOperation, result: dict = None):
    """Mark an operation as completed."""
    op.status = "completed"
    op.result = result or {}
    op.completed_at = now_utc()
    if op.batch_total is not None:
        op.batch_completed = (op.batch_completed or 0) + 1
    db.session.commit()


def _fail_operation(op: UtilityOperation, error: str):
    """Mark an operation as failed."""
    op.status = "failed"
    op.error_message = error
    op.completed_at = now_utc()
    if op.batch_total is not None:
        op.batch_failed = (op.batch_failed or 0) + 1
    db.session.commit()


def get_user_history(user_id: int, limit: int = 50, offset: int = 0) -> dict:
    """Get paginated utility operation history for a user."""
    query = (
        UtilityOperation.query
        .filter_by(user_id=user_id)
        .order_by(UtilityOperation.created_at.desc())
    )
    total = query.count()
    operations = query.offset(offset).limit(limit).all()

    return {
        "operations": [op.to_dict() for op in operations],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
    }


def get_batch_status(batch_id: str, user_id: int) -> dict:
    """Get the current status of a batch operation."""
    ops = (
        UtilityOperation.query
        .filter_by(batch_id=batch_id, user_id=user_id)
        .order_by(UtilityOperation.created_at.asc())
        .all()
    )
    if not ops:
        return None

    first_op = ops[0]
    total = first_op.batch_total or len(ops)
    completed = sum(1 for o in ops if o.status == "completed")
    failed = sum(1 for o in ops if o.status == "failed")
    processing = sum(1 for o in ops if o.status in ("pending", "processing"))

    return {
        "batch_id": batch_id,
        "operation": first_op.operation,
        "total": total,
        "completed": completed,
        "failed": failed,
        "pending": processing,
        "progress": round((completed + failed) / total * 100) if total > 0 else 0,
        "status": "completed" if (completed + failed) >= total else "processing",
        "operations": [op.to_dict() for op in ops],
    }


# ============================================================
# BATCH PROCESSING
# ============================================================


def batch_upscale(image_ids: list, user_id: int, scale: float = 2.0,
                   provider: str = "stub") -> dict:
    """Upscale multiple images in a batch.

    Returns a batch_id that the client can poll for progress.
    Each image is processed sequentially.
    """
    batch_id = str(uuid.uuid4())
    total = len(image_ids)

    results = []
    for image_id in image_ids:
        op = _start_operation(
            user_id=user_id,
            operation="upscale",
            provider=provider,
            image_id=image_id,
            params={"scale": scale},
            batch_id=batch_id,
            batch_total=total,
        )

        try:
            result = upscale_image(
                image_id=image_id,
                user_id=user_id,
                scale=scale,
                params={"provider": provider},
            )
            _complete_operation(op, result)
            results.append({"image_id": image_id, "status": "success", **result})
        except Exception as e:
            _fail_operation(op, str(e))
            results.append({"image_id": image_id, "status": "failed", "error": str(e)})

    return {
        "batch_id": batch_id,
        "total": total,
        "results": results,
    }


def batch_describe(image_ids: list, user_id: int, provider: str = "stub") -> dict:
    """Describe multiple images in a batch.

    Returns a batch_id that the client can poll for progress.
    Each image is processed sequentially.
    """
    batch_id = str(uuid.uuid4())
    total = len(image_ids)

    results = []
    for image_id in image_ids:
        op = _start_operation(
            user_id=user_id,
            operation="describe",
            provider=provider,
            image_id=image_id,
            params={},
            batch_id=batch_id,
            batch_total=total,
        )

        try:
            result = describe_image(
                image_id=image_id,
                user_id=user_id,
                params={"provider": provider},
            )
            _complete_operation(op, result)
            results.append({"image_id": image_id, "status": "success", "description": result})
        except Exception as e:
            _fail_operation(op, str(e))
            results.append({"image_id": image_id, "status": "failed", "error": str(e)})

    return {
        "batch_id": batch_id,
        "total": total,
        "results": results,
    }


# ============================================================
# CAPABILITIES ENDPOINT
# ============================================================


def get_utilities_capabilities() -> dict:
    """Get utility capabilities for all providers."""
    providers = list_providers()
    capabilities = {}

    for name in providers:
        try:
            provider = get_provider(name)
            caps = provider.get_capabilities()
            capabilities[name] = {
                "name": provider.display_name,
                "configured": provider.is_configured(),
                "upscale": caps.upscale,
                "transparency": caps.transparency,
                "background_removal": caps.background_removal,
                "image_understanding": caps.image_understanding,
                "multi_reference": caps.multi_reference,
            }
        except Exception:
            capabilities[name] = {
                "name": name,
                "configured": False,
                "upscale": False,
                "transparency": False,
                "background_removal": False,
                "image_understanding": False,
                "multi_reference": False,
            }

    return capabilities


# ============================================================
# HELPERS (shared with editor_service)
# ============================================================


def _get_or_create_original_version(image: Image, user_id: int) -> Optional[ImageVersion]:
    """Get or create the original (v1) version for an image."""
    existing = ImageVersion.query.filter_by(
        image_id=image.id, version_number=1
    ).first()
    if existing:
        return existing

    version = ImageVersion(
        image_id=image.id,
        user_id=user_id,
        version_number=1,
        filename=image.filename,
        file_path=image.file_path,
        thumb_path=image.thumb_path,
        width=image.width,
        height=image.height,
        file_size=image.file_size,
        edit_type="original",
        edit_params={},
        edit_description="Original image",
    )
    db.session.add(version)
    db.session.commit()
    return version


def _get_next_version_number(image_id: int) -> int:
    """Get the next version number for an image."""
    latest = (
        ImageVersion.query
        .filter_by(image_id=image_id)
        .order_by(ImageVersion.version_number.desc())
        .first()
    )
    return (latest.version_number + 1) if latest else 1
