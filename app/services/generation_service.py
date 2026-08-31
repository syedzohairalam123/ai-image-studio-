"""Generation service — orchestrates the full image generation workflow."""

from pathlib import Path

from app.extensions import db
from app.config import BASE_DIR
from app.models.generation import Generation
from app.models.image import Image
from app.services.ai_provider import (
    AIProvider,
    GenerationResult,
    ImageData,
    get_provider,
)
from app.services.storage_service import StorageService
from app.utils import generate_filename, now_utc


# Dimension presets by aspect ratio
ASPECT_RATIOS = {
    "1:1":  (512, 512),
    "16:9": (768, 432),
    "9:16": (432, 768),
    "4:3":  (576, 432),
    "3:4":  (432, 576),
}

QUALITY_MAP = {
    "draft":  {"width": 256, "height": 256},
    "standard": {"width": 512, "height": 512},
    "hd":     {"width": 768, "height": 768},
    "ultra":  {"width": 1024, "height": 1024},
}

MAX_PROMPT_LENGTH = 2000
MIN_PROMPT_LENGTH = 1
MAX_OUTPUT_COUNT = 4
MIN_OUTPUT_COUNT = 1


def _default_provider_name() -> str:
    """The provider to use when a request doesn't explicitly specify one —
    reads the app's configured AI_PROVIDER, falling back to "stub" if
    there's no app context (e.g. a script run outside Flask)."""
    try:
        from flask import current_app
        return current_app.config.get("AI_PROVIDER", "stub")
    except Exception:
        import os
        return os.environ.get("AI_PROVIDER", "stub")


class GenerationError(Exception):
    """Raised when generation fails."""

    def __init__(self, message, status_code=400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def validate_generation_params(data: dict) -> dict:
    """Validate and normalize generation parameters. Raises GenerationError on failure."""
    errors = {}

    # Prompt
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        errors["prompt"] = "Prompt is required."
    elif len(prompt) < MIN_PROMPT_LENGTH:
        errors["prompt"] = "Prompt cannot be empty."
    elif len(prompt) > MAX_PROMPT_LENGTH:
        errors["prompt"] = f"Prompt must be at most {MAX_PROMPT_LENGTH} characters."

    # Output count
    try:
        count = int(data.get("count", 1))
        if count < MIN_OUTPUT_COUNT or count > MAX_OUTPUT_COUNT:
            errors["count"] = f"Output count must be between {MIN_OUTPUT_COUNT} and {MAX_OUTPUT_COUNT}."
    except (TypeError, ValueError):
        count = 1

    # Aspect ratio
    aspect = data.get("aspect_ratio", "1:1")
    if aspect not in ASPECT_RATIOS:
        errors["aspect_ratio"] = f"Invalid aspect ratio. Options: {', '.join(ASPECT_RATIOS.keys())}"

    # Quality
    quality = data.get("quality", "standard")
    if quality not in QUALITY_MAP:
        errors["quality"] = f"Invalid quality. Options: {', '.join(QUALITY_MAP.keys())}"

    # Style
    style = data.get("style", "auto")

    # Provider — defaults to whatever the app is configured with
    # (AI_PROVIDER in .env), NOT a hardcoded "stub". Previously this was
    # `data.get("provider", "stub")`, which meant the app-level provider
    # setting had no effect at all on this endpoint (the frontend never
    # sends a `provider` field), so switching AI_PROVIDER in .env silently
    # did nothing here even though it worked for the Advanced AI endpoints.
    provider_name = data.get("provider") or _default_provider_name()

    # Negative prompt (optional)
    negative_prompt = (data.get("negative_prompt") or "").strip() or None

    # Seed (optional)
    seed = None
    if data.get("seed"):
        try:
            seed = int(data["seed"])
        except (TypeError, ValueError):
            pass

    # Reference images (optional)
    reference_image_ids = data.get("reference_image_ids") or []
    reference_strength = None
    if data.get("reference_strength") is not None:
        try:
            reference_strength = max(0.0, min(1.0, float(data["reference_strength"])))
        except (TypeError, ValueError):
            reference_strength = None

    if errors:
        raise GenerationError(f"Validation failed: {'; '.join(errors.values())}")

    # Compute dimensions
    width, height = ASPECT_RATIOS.get(aspect, (512, 512))

    return {
        "prompt": prompt,
        "count": count,
        "aspect_ratio": aspect,
        "quality": quality,
        "style": style,
        "provider_name": provider_name,
        "negative_prompt": negative_prompt,
        "seed": seed,
        "width": width,
        "height": height,
        "reference_image_ids": reference_image_ids,
        "reference_strength": reference_strength,
    }


def run_generation(user_id: int, data: dict) -> Generation:
    """Execute the full generation workflow. Returns a Generation object.

    Steps:
    1. Validate parameters
    2. Get provider
    3. Create generation record (status=pending)
    4. Call provider
    5. Save results
    6. Update status
    """
    # Step 1: Validate
    params = validate_generation_params(data)

    # Step 2: Get provider
    try:
        provider = _get_configured_provider(params["provider_name"])
    except GenerationError:
        raise
    except Exception as e:
        raise GenerationError(f"Provider error: {str(e)}", 500)

    # Step 3: Create generation record
    generation = Generation(
        user_id=user_id,
        prompt=params["prompt"],
        negative_prompt=params["negative_prompt"],
        provider=params["provider_name"],
        model=params.get("model"),
        parameters={
            "style": params["style"],
            "aspect_ratio": params["aspect_ratio"],
            "quality": params["quality"],
            "width": params["width"],
            "height": params["height"],
            "seed": params["seed"],
            "count": params["count"],
        },
        status="processing",
    )
    db.session.add(generation)
    db.session.commit()

    # Step 3.5: Resolve reference images if provided
    reference_paths = []
    if params.get("reference_image_ids"):
        from app.models.reference_image import ReferenceImage
        for ref_id in params["reference_image_ids"]:
            ref = ReferenceImage.query.filter_by(
                id=ref_id, user_id=user_id, is_deleted=False
            ).first()
            if ref:
                from pathlib import Path as _Path
                if _Path(ref.file_path).exists():
                    reference_paths.append(ref.file_path)

    # Step 4: Call provider
    try:
        kwargs = {
            "width": params["width"],
            "height": params["height"],
            "style": params["style"],
            "count": params["count"],
        }
        if params["negative_prompt"]:
            kwargs["negative_prompt"] = params["negative_prompt"]
        if params["seed"] is not None:
            kwargs["seed"] = params["seed"]
        if reference_paths:
            kwargs["reference_paths"] = reference_paths
        if params.get("reference_strength") is not None:
            kwargs["reference_strength"] = params["reference_strength"]

        result: GenerationResult = provider.text_to_image(params["prompt"], **kwargs)
    except Exception as e:
        generation.status = "failed"
        generation.error_message = str(e)
        generation.completed_at = now_utc()
        db.session.commit()
        raise GenerationError(f"Generation failed: {str(e)}", 502)

    # Step 5: Save results
    if not result.success:
        generation.status = "failed"
        generation.error_message = result.error or "Provider returned no results"
        generation.completed_at = now_utc()
        db.session.commit()
        raise GenerationError(result.error or "Generation failed", 502)

    storage = StorageService(str(BASE_DIR / "uploads" / "generations" / str(user_id)))

    for img_data in result.images:
        saved = _save_image_result(storage, img_data, params)

        image = Image(
            generation_id=generation.id,
            user_id=user_id,
            filename=saved["filename"],
            file_path=saved["file_path"],
            width=img_data.width,
            height=img_data.height,
            file_size=saved["file_size"],
            seed=img_data.seed,
            meta=img_data.metadata,
        )
        db.session.add(image)

    # Step 6: Update status
    generation.status = "completed"
    generation.completed_at = now_utc()
    db.session.commit()

    return generation


def _get_configured_provider(name: str) -> AIProvider:
    """Get a configured provider instance."""
    import os

    api_key = os.environ.get("AI_API_KEY", "")

    try:
        return get_provider(name, api_key=api_key)
    except ValueError as e:
        raise GenerationError(str(e))


def _save_image_result(storage: StorageService, img_data: ImageData, params: dict) -> dict:
    """Save an image result to storage."""
    if img_data.file_bytes:
        # Save from bytes
        filename = img_data.filename or generate_filename("generated.png", prefix="gen")
        return storage.save_bytes(img_data.file_bytes, filename, subfolder="images")
    elif img_data.url:
        # Save from URL (demo/stub mode)
        filename = generate_filename("generated.png", prefix="gen")
        # Create a placeholder SVG
        placeholder = _create_placeholder_svg(
            prompt=params["prompt"],
            width=img_data.width or params["width"],
            height=img_data.height or params["height"],
            style=params.get("style", "auto"),
        )
        return storage.save_bytes(placeholder.encode("utf-8"), filename, subfolder="images")
    else:
        # No image data — save a minimal placeholder
        filename = generate_filename("placeholder.svg", prefix="gen")
        placeholder = _create_placeholder_svg(
            prompt=params["prompt"],
            width=params["width"],
            height=params["height"],
            style=params.get("style", "auto"),
        )
        return storage.save_bytes(placeholder.encode("utf-8"), filename, subfolder="images")


def _create_placeholder_svg(prompt: str, width: int, height: int, style: str = "auto") -> str:
    """Create a styled placeholder SVG for demo mode."""
    # Truncate prompt for display
    display_prompt = prompt[:60] + ("..." if len(prompt) > 60 else "")
    # Escape XML special chars
    display_prompt = display_prompt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Style-based colors
    colors = {
        "auto": ("#667eea", "#764ba2"),
        "photo": ("#2d3436", "#636e72"),
        "art": ("#6c5ce7", "#a29bfe"),
        "paint": ("#e17055", "#fdcb6e"),
        "anime": ("#fd79a8", "#e84393"),
        "3d": ("#00b894", "#00cec9"),
        "pixel": ("#0984e3", "#74b9ff"),
        "minimal": ("#dfe6e9", "#b2bec3"),
    }
    c1, c2 = colors.get(style, colors["auto"])

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{c1}"/>
      <stop offset="100%" style="stop-color:{c2}"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#bg)"/>
  <text x="50%" y="45%" text-anchor="middle" fill="white" font-family="Inter, sans-serif" font-size="14" opacity="0.9">{display_prompt}</text>
  <text x="50%" y="58%" text-anchor="middle" fill="white" font-family="Inter, sans-serif" font-size="11" opacity="0.6">Demo mode • {width}×{height}</text>
</svg>'''
