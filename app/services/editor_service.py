"""Editor service — handles local and AI image editing operations.

Local operations: crop, resize, rotate, flip, brightness, contrast, saturation
AI operations: inpainting, outpainting, background replacement, retexture
"""

import io
import json
import base64
from pathlib import Path
from typing import Optional, Tuple

from app.extensions import db
from app.config import BASE_DIR
from app.models.image import Image
from app.models.image_version import ImageVersion
from app.services.storage_service import StorageService
from app.services.ai_provider import get_provider
from app.utils import generate_filename, now_utc


# ============================================================
# LOCAL EDITING OPERATIONS
# ============================================================


def local_edit(image_id: int, user_id: int, operation: str, params: dict) -> ImageVersion:
    """Apply a local editing operation to an image.

    Args:
        image_id: Source image ID
        user_id: Current user ID
        operation: One of: crop, resize, rotate, flip, brightness, contrast, saturation
        params: Operation-specific parameters

    Returns:
        New ImageVersion with the edited image

    Raises:
        ValueError: If image not found or invalid operation
    """
    # Get source image
    image = Image.query.filter_by(
        id=image_id, user_id=user_id, is_deleted=False
    ).first()
    if not image:
        raise ValueError("Image not found")

    source_path = Path(image.file_path)
    if not source_path.exists():
        raise ValueError("Image file not found")

    # Get or create the original version
    original_version = _get_or_create_original_version(image, user_id)

    # Get next version number
    next_version = _get_next_version_number(image_id)

    # Apply the operation
    result = _apply_local_operation(source_path, operation, params)

    # Save edited image
    storage = StorageService(str(BASE_DIR / "uploads" / "edits" / str(user_id)))
    filename = generate_filename(source_path.name, prefix=f"v{next_version}")
    saved = storage.save_bytes(result["bytes"], filename, subfolder="images")

    # Create version record
    version = ImageVersion(
        image_id=image_id,
        user_id=user_id,
        version_number=next_version,
        parent_version_id=original_version.id if original_version else None,
        filename=saved["filename"],
        file_path=saved["file_path"],
        width=result.get("width"),
        height=result.get("height"),
        file_size=saved["file_size"],
        edit_type=f"local_{operation}",
        edit_params=params,
        edit_description=_describe_local_operation(operation, params),
    )
    db.session.add(version)
    db.session.commit()

    return version


def _apply_local_operation(source_path: Path, operation: str, params: dict) -> dict:
    """Apply a local operation using Pillow.

    Returns dict with 'bytes', 'width', 'height'.
    """
    from PIL import Image as PILImage, ImageEnhance, ImageFilter

    img = PILImage.open(source_path)

    # Convert to RGB if necessary (for JPEG compatibility)
    if img.mode in ("RGBA", "P"):
        # Keep RGBA for PNG, convert others
        if source_path.suffix.lower() not in (".png",):
            img = img.convert("RGB")

    if operation == "crop":
        x = int(params.get("x", 0))
        y = int(params.get("y", 0))
        width = int(params.get("width", img.width))
        height = int(params.get("height", img.height))
        # Clamp values
        x = max(0, min(x, img.width))
        y = max(0, min(y, img.height))
        width = max(1, min(width, img.width - x))
        height = max(1, min(height, img.height - y))
        img = img.crop((x, y, x + width, y + height))

    elif operation == "resize":
        target_w = int(params.get("width", img.width))
        target_h = int(params.get("height", img.height))
        maintain_ratio = params.get("maintain_ratio", True)

        if maintain_ratio:
            ratio = min(target_w / img.width, target_h / img.height)
            target_w = max(1, int(img.width * ratio))
            target_h = max(1, int(img.height * ratio))

        target_w = min(target_w, 4096)  # Safety limit
        target_h = min(target_h, 4096)
        img = img.resize((target_w, target_h), PILImage.LANCZOS)

    elif operation == "rotate":
        angle = float(params.get("angle", 0))
        expand = params.get("expand", True)
        img = img.rotate(-angle, expand=expand, resample=PILImage.BICUBIC)

    elif operation == "flip":
        direction = params.get("direction", "horizontal")
        if direction == "horizontal":
            img = img.transpose(PILImage.FLIP_LEFT_RIGHT)
        elif direction == "vertical":
            img = img.transpose(PILImage.FLIP_TOP_BOTTOM)

    elif operation == "brightness":
        factor = float(params.get("factor", 1.0))
        factor = max(0.1, min(3.0, factor))
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(factor)

    elif operation == "contrast":
        factor = float(params.get("factor", 1.0))
        factor = max(0.1, min(3.0, factor))
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(factor)

    elif operation == "saturation":
        factor = float(params.get("factor", 1.0))
        factor = max(0.0, min(3.0, factor))
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(factor)

    # ---- New local operations (additive — none of the above changed) ----

    elif operation == "blur":
        radius = max(0.1, min(20.0, float(params.get("radius", 2.0))))
        img = img.filter(ImageFilter.GaussianBlur(radius=radius))

    elif operation == "sharpen":
        factor = max(0.1, min(5.0, float(params.get("factor", 2.0))))
        img = ImageEnhance.Sharpness(img).enhance(factor)

    elif operation == "grayscale":
        alpha = img.getchannel("A") if img.mode == "RGBA" else None
        gray = img.convert("L").convert("RGB")
        img = PILImage.merge("RGBA", (*gray.split(), alpha)) if alpha else gray

    elif operation == "sepia":
        img = _apply_sepia(img)

    elif operation == "invert":
        from PIL import ImageOps as _ImageOps
        if img.mode == "RGBA":
            r, g, b, a = img.split()
            rgb = _ImageOps.invert(PILImage.merge("RGB", (r, g, b)))
            img = PILImage.merge("RGBA", (*rgb.split(), a))
        else:
            img = _ImageOps.invert(img.convert("RGB"))

    elif operation == "vignette":
        strength = max(0.0, min(1.0, float(params.get("strength", 0.45))))
        img = _apply_vignette_local(img, strength)

    elif operation == "duotone":
        shadow = params.get("shadow_color", "#1a1a2e")
        highlight = params.get("highlight_color", "#f4d35e")
        img = _apply_duotone(img, shadow, highlight)

    elif operation == "edge_detect":
        edges = img.convert("RGB").filter(ImageFilter.FIND_EDGES)
        img = edges if img.mode != "RGBA" else PILImage.merge(
            "RGBA", (*edges.split(), img.getchannel("A")))

    elif operation == "pixelate":
        block = max(2, min(100, int(params.get("block_size", 12))))
        small = img.resize((max(1, img.width // block), max(1, img.height // block)), PILImage.BILINEAR)
        img = small.resize(img.size, PILImage.NEAREST)

    elif operation == "posterize":
        bits = max(1, min(8, int(params.get("levels", 4))))
        from PIL import ImageOps as _ImageOps
        if img.mode == "RGBA":
            r, g, b, a = img.split()
            posterized = _ImageOps.posterize(PILImage.merge("RGB", (r, g, b)), bits)
            img = PILImage.merge("RGBA", (*posterized.split(), a))
        else:
            img = _ImageOps.posterize(img.convert("RGB"), bits)

    elif operation == "warmth":
        amount = max(-100.0, min(100.0, float(params.get("amount", 20))))
        img = _shift_warmth(img, amount)

    elif operation == "gamma":
        gamma = max(0.1, min(5.0, float(params.get("gamma", 1.2))))
        img = _apply_gamma(img, gamma)

    elif operation == "vibrance":
        amount = max(-100.0, min(100.0, float(params.get("amount", 30))))
        img = _apply_vibrance(img, amount)

    elif operation == "denoise":
        strength = max(1, min(15, int(params.get("strength", 5))))
        img = _apply_denoise(img, strength)

    else:
        raise ValueError(f"Unknown operation: {operation}")

    # Encode to bytes
    buf = io.BytesIO()
    if img.mode == "RGBA" and source_path.suffix.lower() == ".png":
        img.save(buf, format="PNG", optimize=True)
    else:
        if img.mode == "RGBA":
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=92, optimize=True)
    buf.seek(0)

    return {
        "bytes": buf.read(),
        "width": img.width,
        "height": img.height,
    }


def _apply_sepia(img):
    """Classic sepia tone via a fixed RGB transform matrix."""
    from PIL import Image as PILImage
    import numpy as np
    alpha = img.getchannel("A") if img.mode == "RGBA" else None
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    matrix = np.array([
        [0.393, 0.769, 0.189],
        [0.349, 0.686, 0.168],
        [0.272, 0.534, 0.131],
    ], dtype=np.float32)
    sepia = np.clip(rgb @ matrix.T, 0, 255).astype(np.uint8)
    out = PILImage.fromarray(sepia, mode="RGB")
    return PILImage.merge("RGBA", (*out.split(), alpha)) if alpha else out


def _apply_vignette_local(img, strength: float):
    from PIL import Image as PILImage
    import numpy as np
    alpha = img.getchannel("A") if img.mode == "RGBA" else None
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2, h / 2
    d = np.sqrt(((xx - cx) / (w / 2)) ** 2 + ((yy - cy) / (h / 2)) ** 2)
    mask = np.clip(1.0 - strength * np.clip(d - 0.3, 0, None), 0.15, 1.0)
    out = np.clip(rgb * mask[..., None], 0, 255).astype(np.uint8)
    result = PILImage.fromarray(out, mode="RGB")
    return PILImage.merge("RGBA", (*result.split(), alpha)) if alpha else result


def _hex_to_rgb(hex_color: str):
    hex_color = (hex_color or "#000000").lstrip("#")
    if len(hex_color) != 6:
        return (0, 0, 0)
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _apply_duotone(img, shadow_hex: str, highlight_hex: str):
    """Map luminance to a two-colour gradient — a real duotone effect (as
    seen in Spotify covers etc.), not just a tint overlay."""
    from PIL import Image as PILImage
    import numpy as np
    alpha = img.getchannel("A") if img.mode == "RGBA" else None
    gray = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
    shadow = np.array(_hex_to_rgb(shadow_hex), dtype=np.float32)
    highlight = np.array(_hex_to_rgb(highlight_hex), dtype=np.float32)
    out = shadow[None, None, :] * (1 - gray[..., None]) + highlight[None, None, :] * gray[..., None]
    result = PILImage.fromarray(np.clip(out, 0, 255).astype(np.uint8), mode="RGB")
    return PILImage.merge("RGBA", (*result.split(), alpha)) if alpha else result


def _shift_warmth(img, amount: float):
    """amount in [-100, 100]: positive = warmer (more red/yellow, less blue),
    negative = cooler (more blue, less red)."""
    from PIL import Image as PILImage
    import numpy as np
    alpha = img.getchannel("A") if img.mode == "RGBA" else None
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    scale = amount / 100.0
    rgb[..., 0] = np.clip(rgb[..., 0] * (1 + 0.25 * scale), 0, 255)
    rgb[..., 2] = np.clip(rgb[..., 2] * (1 - 0.25 * scale), 0, 255)
    result = PILImage.fromarray(rgb.astype(np.uint8), mode="RGB")
    return PILImage.merge("RGBA", (*result.split(), alpha)) if alpha else result


def _apply_gamma(img, gamma: float):
    """Power-law gamma correction, applied only to colour channels — alpha
    (if present) is left untouched so transparency doesn't shift."""
    from PIL import Image as PILImage
    inv_gamma = 1.0 / gamma
    lut = [min(255, max(0, int(((i / 255.0) ** inv_gamma) * 255))) for i in range(256)]
    if img.mode == "RGBA":
        r, g, b, a = img.split()
        r, g, b = (band.point(lut) for band in (r, g, b))
        return PILImage.merge("RGBA", (r, g, b, a))
    rgb = img.convert("RGB")
    r, g, b = rgb.split()
    return PILImage.merge("RGB", tuple(band.point(lut) for band in (r, g, b)))


def _apply_vibrance(img, amount: float):
    """Smart saturation: boosts *muted* colours more than already-saturated
    ones, which is what real "vibrance" sliders do (as opposed to a flat
    saturation multiply, which oversaturates skin tones fastest)."""
    from PIL import Image as PILImage
    import colorsys
    import numpy as np
    alpha = img.getchannel("A") if img.mode == "RGBA" else None
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    maxc = rgb.max(axis=-1)
    minc = rgb.min(axis=-1)
    sat = (maxc - minc) / np.clip(maxc, 1e-6, None)
    boost = (amount / 100.0) * (1.0 - sat)  # muted pixels get a bigger nudge
    mean = rgb.mean(axis=-1, keepdims=True)
    out = rgb + (rgb - mean) * boost[..., None]
    out = np.clip(out, 0, 1)
    result = PILImage.fromarray((out * 255).astype(np.uint8), mode="RGB")
    return PILImage.merge("RGBA", (*result.split(), alpha)) if alpha else result


def _apply_denoise(img, strength: int):
    """Edge-preserving denoise via OpenCV's bilateral filter — smooths flat
    regions/noise while keeping edges sharp, unlike a plain blur."""
    from PIL import Image as PILImage
    import numpy as np
    try:
        import cv2
        alpha = img.getchannel("A") if img.mode == "RGBA" else None
        rgb = np.asarray(img.convert("RGB"))
        bgr = rgb[:, :, ::-1]
        d = max(3, min(15, strength))
        filtered = cv2.bilateralFilter(bgr, d=d, sigmaColor=strength * 8, sigmaSpace=strength * 8)
        result = PILImage.fromarray(filtered[:, :, ::-1], mode="RGB")
        return PILImage.merge("RGBA", (*result.split(), alpha)) if alpha else result
    except Exception:
        from PIL import ImageFilter as _ImageFilter
        return img.filter(_ImageFilter.MedianFilter(size=min(9, 2 * (strength // 3) + 3)))


def _describe_local_operation(operation: str, params: dict) -> str:
    """Generate a human-readable description for a local edit."""
    descriptions = {
        "crop": "Cropped to {width}×{height}",
        "resize": "Resized to {width}×{height}",
        "rotate": "Rotated {angle}°",
        "flip": "Flipped {direction}",
        "brightness": "Brightness adjusted to {factor}×",
        "contrast": "Contrast adjusted to {factor}×",
        "saturation": "Saturation adjusted to {factor}×",
        "blur": "Gaussian blur (radius {radius})",
        "sharpen": "Sharpened {factor}×",
        "grayscale": "Converted to grayscale",
        "sepia": "Sepia tone applied",
        "invert": "Colors inverted",
        "vignette": "Vignette applied (strength {strength})",
        "duotone": "Duotone applied",
        "edge_detect": "Edge detection applied",
        "pixelate": "Pixelated ({block_size}px blocks)",
        "posterize": "Posterized to {levels} levels",
        "warmth": "Warmth adjusted ({amount})",
        "gamma": "Gamma corrected ({gamma})",
        "vibrance": "Vibrance adjusted ({amount})",
        "denoise": "Denoised (strength {strength})",
    }
    desc = descriptions.get(operation, operation)
    try:
        return desc.format(**params)
    except (KeyError, TypeError):
        return operation


# ============================================================
# AI EDITING OPERATIONS
# ============================================================


def ai_edit(
    image_id: int,
    user_id: int,
    operation: str,
    prompt: str,
    params: dict,
    mask_data: Optional[str] = None,
) -> ImageVersion:
    """Apply an AI editing operation.

    Args:
        image_id: Source image ID
        user_id: Current user ID
        operation: One of: inpaint, outpaint, background_replace, retexture
        prompt: Text prompt describing the desired edit
        params: Operation-specific parameters
        mask_data: Base64 mask image for inpainting (optional)

    Returns:
        New ImageVersion with the AI-edited image

    Raises:
        ValueError: If image not found, file missing, or provider error
    """
    from PIL import Image as PILImage

    # Get source image
    image = Image.query.filter_by(
        id=image_id, user_id=user_id, is_deleted=False
    ).first()
    if not image:
        raise ValueError("Image not found")

    source_path = Path(image.file_path)
    if not source_path.exists():
        raise ValueError("Image file not found")

    # Get original version
    original_version = _get_or_create_original_version(image, user_id)
    next_version = _get_next_version_number(image_id)

    # Get the AI provider
    provider_name = params.get("provider", "stub")
    try:
        provider = get_provider(provider_name)
    except ValueError:
        raise ValueError(f"Provider '{provider_name}' not available")

    # Check provider supports the operation
    capability_map = {
        "inpaint": "inpainting",
        "outpaint": "outpainting",
        "background_replace": "image_edit",
        "retexture": "image_edit",
    }
    required_cap = capability_map.get(operation)
    if required_cap and not provider.supports(required_cap):
        raise ValueError(
            f"Provider '{provider_name}' does not support {operation}. "
            f"Required capability: {required_cap}"
        )

    # Prepare the mask if provided
    mask_path = None
    if mask_data:
        mask_path = _save_mask_data(mask_data, user_id)

    # Process based on operation type
    try:
        if operation == "inpaint":
            result = _process_inpaint(provider, source_path, prompt, mask_path, params)
        elif operation == "outpaint":
            result = _process_outpaint(provider, source_path, prompt, params)
        elif operation == "background_replace":
            result = _process_background_replace(provider, source_path, prompt, params)
        elif operation == "retexture":
            result = _process_retexture(provider, source_path, prompt, params)
        else:
            raise ValueError(f"Unknown AI operation: {operation}")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"AI processing failed: {str(e)}")

    # Save result
    storage = StorageService(str(BASE_DIR / "uploads" / "edits" / str(user_id)))
    filename = generate_filename(source_path.name, prefix=f"ai_v{next_version}")

    if isinstance(result["bytes"], bytes):
        saved = storage.save_bytes(result["bytes"], filename, subfolder="images")
    else:
        # Create placeholder for stub provider
        placeholder = _create_edit_placeholder(
            prompt, result.get("width", 512), result.get("height", 512), operation
        )
        saved = storage.save_bytes(placeholder.encode("utf-8"), filename, subfolder="images")

    # Create version record
    version = ImageVersion(
        image_id=image_id,
        user_id=user_id,
        version_number=next_version,
        parent_version_id=original_version.id if original_version else None,
        filename=saved["filename"],
        file_path=saved["file_path"],
        width=result.get("width"),
        height=result.get("height"),
        file_size=saved["file_size"],
        edit_type=f"ai_{operation}",
        edit_params={**params, "prompt": prompt},
        edit_description=f"AI {operation}: {prompt[:80]}",
    )
    db.session.add(version)
    db.session.commit()

    # Cleanup mask file
    if mask_path and mask_path.exists():
        mask_path.unlink(missing_ok=True)

    return version


def _process_inpaint(provider, source_path: Path, prompt: str, mask_path: Optional[Path], params: dict) -> dict:
    """Process inpainting operation."""
    from PIL import Image as PILImage

    img = PILImage.open(source_path)

    # If no real inpainting support, simulate with prompt-based generation
    if provider.supports("inpainting") and mask_path:
        # Real inpainting would go here
        pass

    # Fallback: generate based on prompt with reference
    result = provider.text_to_image(
        prompt,
        width=img.width,
        height=img.height,
        reference_paths=[str(source_path)],
        reference_strength=params.get("strength", 0.7),
    )

    if result.success and result.images:
        img_data = result.images[0]
        if img_data.file_bytes:
            return {
                "bytes": img_data.file_bytes,
                "width": img_data.width or img.width,
                "height": img_data.height or img.height,
            }

    return {"bytes": None, "width": img.width, "height": img.height}


def _process_outpaint(provider, source_path: Path, prompt: str, params: dict) -> dict:
    """Process outpainting operation."""
    from PIL import Image as PILImage

    img = PILImage.open(source_path)

    direction = params.get("direction", "right")
    extend_pct = params.get("extend_percent", 25)

    # Calculate new dimensions
    new_w, new_h = img.width, img.height
    if direction in ("left", "right"):
        extend = int(img.width * extend_pct / 100)
        new_w = img.width + extend
    if direction in ("top", "bottom"):
        extend = int(img.height * extend_pct / 100)
        new_h = img.height + extend

    # Limit total size
    new_w = min(new_w, 2048)
    new_h = min(new_h, 2048)

    # Use provider for outpainting
    result = provider.text_to_image(
        prompt,
        width=new_w,
        height=new_h,
        reference_paths=[str(source_path)],
        reference_strength=0.6,
    )

    if result.success and result.images:
        img_data = result.images[0]
        if img_data.file_bytes:
            return {
                "bytes": img_data.file_bytes,
                "width": img_data.width or new_w,
                "height": img_data.height or new_h,
            }

    return {"bytes": None, "width": new_w, "height": new_h}


def _process_background_replace(provider, source_path: Path, prompt: str, params: dict) -> dict:
    """Process background replacement operation."""
    from PIL import Image as PILImage

    img = PILImage.open(source_path)

    result = provider.text_to_image(
        prompt,
        width=img.width,
        height=img.height,
        reference_paths=[str(source_path)],
        reference_strength=params.get("strength", 0.5),
    )

    if result.success and result.images:
        img_data = result.images[0]
        if img_data.file_bytes:
            return {
                "bytes": img_data.file_bytes,
                "width": img_data.width or img.width,
                "height": img_data.height or img.height,
            }

    return {"bytes": None, "width": img.width, "height": img.height}


def _process_retexture(provider, source_path: Path, prompt: str, params: dict) -> dict:
    """Process retexture/restyle operation."""
    from PIL import Image as PILImage

    img = PILImage.open(source_path)

    strength = params.get("strength", 0.7)

    result = provider.text_to_image(
        prompt,
        width=img.width,
        height=img.height,
        reference_paths=[str(source_path)],
        reference_strength=strength,
    )

    if result.success and result.images:
        img_data = result.images[0]
        if img_data.file_bytes:
            return {
                "bytes": img_data.file_bytes,
                "width": img_data.width or img.width,
                "height": img_data.height or img.height,
            }

    return {"bytes": None, "width": img.width, "height": img.height}


# ============================================================
# VERSION MANAGEMENT
# ============================================================


def get_version_history(image_id: int, user_id: int) -> list:
    """Get all versions of an image, ordered by version number."""
    versions = (
        ImageVersion.query
        .filter_by(image_id=image_id, user_id=user_id)
        .order_by(ImageVersion.version_number.asc())
        .all()
    )
    return [v.to_dict() for v in versions]


def get_version(version_id: int, user_id: int) -> Optional[ImageVersion]:
    """Get a specific version by ID."""
    return ImageVersion.query.filter_by(
        id=version_id, user_id=user_id
    ).first()


def get_latest_version(image_id: int, user_id: int) -> Optional[ImageVersion]:
    """Get the latest version of an image."""
    return (
        ImageVersion.query
        .filter_by(image_id=image_id, user_id=user_id)
        .order_by(ImageVersion.version_number.desc())
        .first()
    )


def revert_to_version(image_id: int, version_id: int, user_id: int) -> ImageVersion:
    """Revert to a specific version by creating a new version from it.

    Does NOT delete any versions — always creates new.
    """
    target_version = ImageVersion.query.filter_by(
        id=version_id, image_id=image_id, user_id=user_id
    ).first()
    if not target_version:
        raise ValueError("Version not found")

    source_path = Path(target_version.file_path)
    if not source_path.exists():
        raise ValueError("Version file not found")

    next_version = _get_next_version_number(image_id)
    original_version = _get_or_create_original_version(
        Image.query.filter_by(id=image_id).first(), user_id
    )

    # Save a copy as new version
    storage = StorageService(str(BASE_DIR / "uploads" / "edits" / str(user_id)))
    filename = generate_filename(source_path.name, prefix=f"revert_v{next_version}")

    with open(source_path, "rb") as f:
        file_bytes = f.read()

    saved = storage.save_bytes(file_bytes, filename, subfolder="images")

    version = ImageVersion(
        image_id=image_id,
        user_id=user_id,
        version_number=next_version,
        parent_version_id=original_version.id if original_version else None,
        filename=saved["filename"],
        file_path=saved["file_path"],
        width=target_version.width,
        height=target_version.height,
        file_size=saved["file_size"],
        edit_type="revert",
        edit_params={"reverted_to_version": version_id},
        edit_description=f"Reverted to version {target_version.version_number}",
    )
    db.session.add(version)
    db.session.commit()

    return version


# ============================================================
# BEFORE/AFTER COMPARISON
# ============================================================


def get_comparison_data(image_id: int, version_id: int, user_id: int) -> dict:
    """Get before/after data for comparison slider."""
    version = ImageVersion.query.filter_by(
        id=version_id, image_id=image_id, user_id=user_id
    ).first()
    if not version:
        raise ValueError("Version not found")

    # Get the "before" (parent or original)
    if version.parent_version_id:
        before = ImageVersion.query.filter_by(id=version.parent_version_id).first()
    else:
        before = _get_original_version(image_id, user_id)

    return {
        "before": {
            "url": f"/api/v1/editor/versions/{before.id}/file" if before else None,
            "width": before.width if before else None,
            "height": before.height if before else None,
        },
        "after": {
            "url": f"/api/v1/editor/versions/{version.id}/file",
            "width": version.width,
            "height": version.height,
        },
        "version_number": version.version_number,
        "edit_type": version.edit_type,
        "edit_description": version.edit_description,
    }


# ============================================================
# MASK HANDLING
# ============================================================


def _save_mask_data(mask_data: str, user_id: int) -> Path:
    """Save base64 mask data to a temporary file."""
    import base64

    # Remove data URL prefix if present
    if "," in mask_data:
        mask_data = mask_data.split(",", 1)[1]

    mask_bytes = base64.b64decode(mask_data)

    mask_dir = BASE_DIR / "uploads" / "masks" / str(user_id)
    mask_dir.mkdir(parents=True, exist_ok=True)

    filename = f"mask_{now_utc().strftime('%Y%m%d_%H%M%S')}.png"
    mask_path = mask_dir / filename
    mask_path.write_bytes(mask_bytes)

    return mask_path


# ============================================================
# HELPERS
# ============================================================


def _get_or_create_original_version(image: Image, user_id: int) -> Optional[ImageVersion]:
    """Get or create the original (v1) version for an image."""
    existing = ImageVersion.query.filter_by(
        image_id=image.id, version_number=1
    ).first()

    if existing:
        return existing

    # Create original version from current image
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


def _get_original_version(image_id: int, user_id: int) -> Optional[ImageVersion]:
    """Get the original version for an image."""
    return ImageVersion.query.filter_by(
        image_id=image_id, version_number=1
    ).first()


def _get_next_version_number(image_id: int) -> int:
    """Get the next version number for an image."""
    latest = (
        ImageVersion.query
        .filter_by(image_id=image_id)
        .order_by(ImageVersion.version_number.desc())
        .first()
    )
    return (latest.version_number + 1) if latest else 1


def _create_edit_placeholder(prompt: str, width: int, height: int, operation: str) -> str:
    """Create placeholder SVG for AI edit in stub mode."""
    display_prompt = prompt[:60] + ("..." if len(prompt) > 60 else "")
    display_prompt = display_prompt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    colors = {
        "inpaint": ("#e17055", "#d63031"),
        "outpaint": ("#0984e3", "#74b9ff"),
        "background_replace": ("#00b894", "#55efc4"),
        "retexture": ("#6c5ce7", "#a29bfe"),
    }
    c1, c2 = colors.get(operation, ("#667eea", "#764ba2"))

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{c1}"/>
      <stop offset="100%" style="stop-color:{c2}"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#bg)"/>
  <text x="50%" y="42%" text-anchor="middle" fill="white" font-family="Inter, sans-serif" font-size="16" opacity="0.9">🤖 AI {operation.title()}</text>
  <text x="50%" y="55%" text-anchor="middle" fill="white" font-family="Inter, sans-serif" font-size="12" opacity="0.7">{display_prompt}</text>
  <text x="50%" y="68%" text-anchor="middle" fill="white" font-family="Inter, sans-serif" font-size="10" opacity="0.5">Stub mode • {width}×{height}</text>
</svg>'''
