"""High-quality upscaling provider using Pillow.

Uses advanced resampling algorithms for better quality than basic LANCZOS:
- LANCZOS (Antialiased): Best for downscaling and general purpose
- Multiple pass upscaling for better quality at high scales
- Sharpening pass after upscale to restore detail

Always available (Pillow is a core dependency).

Usage:
    Provider is auto-registered.
    Set PILLOW_UPSCALE_SHARPEN=true in .env to enable post-sharpening.
"""

import io
import logging
from typing import Optional

from PIL import Image as PILImage, ImageFilter, ImageEnhance

from app.services.ai_provider import AIProvider, ProviderCapabilities, GenerationResult, ImageData

logger = logging.getLogger(__name__)


class PillowUpscaleProvider(AIProvider):
    """High-quality upscaling using Pillow with advanced algorithms.

    Features:
    - Multi-pass upscaling for better quality at high scales
    - Configurable sharpening to restore detail
    - Supports all Pillow output formats
    - Preserves alpha channel when present
    """

    name = "pillow_upscale"
    display_name = "AI Upscale (Pillow)"
    capabilities = ProviderCapabilities(
        text_to_image=False,
        image_edit=False,
        variations=False,
        inpainting=False,
        outpainting=False,
        upscale=True,
        transparency=False,
        background_removal=False,
        image_understanding=False,
        multi_reference=False,
        seed=False,
        negative_prompt=False,
        multiple_references=False,
    )

    def __init__(self, api_key: str = "", **kwargs):
        super().__init__(api_key, **kwargs)
        self.sharpen = kwargs.get("sharpen", True)
        self.sharpen_factor = float(kwargs.get("sharpen_factor", 1.2))
        self.multi_pass = kwargs.get("multi_pass", True)

    def text_to_image(self, prompt: str, **kwargs) -> GenerationResult:
        """Pillow upscale doesn't support text-to-image."""
        return GenerationResult(
            success=False,
            error="Pillow Upscale does not support text-to-image generation. Use it for image upscaling.",
        )

    def upscale(self, image_bytes: bytes, scale: float = 2.0, **kwargs) -> dict:
        """Upscale an image with high quality.

        Args:
            image_bytes: Raw image bytes
            scale: Upscale factor (1.5 to 4.0)
            **kwargs:
                sharpen: Enable/disable sharpening (default: True)
                sharpen_factor: Sharpening strength (default: 1.2)
                output_format: Output format ('png', 'jpeg', 'webp')
                quality: JPEG/WebP quality (1-100)

        Returns:
            dict with keys:
                bytes: Upscaled image bytes
                width: Output width
                height: Output height
                scale: Actual scale applied
                format: Output format
        """
        sharpen = kwargs.get("sharpen", self.sharpen)
        sharpen_factor = float(kwargs.get("sharpen_factor", self.sharpen_factor))
        output_format = kwargs.get("output_format", "png")
        quality = kwargs.get("quality", 95)

        # Clamp scale
        scale = max(1.0, min(4.0, float(scale)))

        # Open image
        img = PILImage.open(io.BytesIO(image_bytes))
        original_width, original_height = img.size
        has_alpha = img.mode == "RGBA" or (img.mode == "P" and "transparency" in img.info)

        # Convert to RGBA for processing if needed
        if img.mode == "P":
            img = img.convert("RGBA")
        elif img.mode == "LA":
            img = img.convert("RGBA")
        elif img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        logger.info(f"Upscaling {original_width}x{original_height} by {scale}x using Pillow")

        # Multi-pass upscaling for better quality
        if self.multi_pass and scale > 2.0:
            img = self._multi_pass_upscale(img, scale)
        else:
            target_w = int(original_width * scale)
            target_h = int(original_height * scale)
            img = img.resize((target_w, target_h), PILImage.LANCZOS)

        # Apply sharpening to restore detail
        if sharpen and scale > 1.0:
            img = self._apply_sharpening(img, sharpen_factor)

        # Convert back to original mode if needed
        if not has_alpha and img.mode == "RGBA":
            img = img.convert("RGB")

        # Save output
        buf = io.BytesIO()
        save_kwargs = {}

        if output_format == "jpeg":
            if img.mode == "RGBA":
                img = img.convert("RGB")
            save_kwargs["quality"] = quality
            save_kwargs["optimize"] = True
            img.save(buf, format="JPEG", **save_kwargs)
        elif output_format == "webp":
            save_kwargs["quality"] = quality
            save_kwargs["method"] = 4  # Good compression
            img.save(buf, format="WEBP", **save_kwargs)
        else:  # PNG
            save_kwargs["optimize"] = True
            img.save(buf, format="PNG", **save_kwargs)

        buf.seek(0)
        output_bytes = buf.read()

        actual_scale = img.width / original_width if original_width > 0 else scale

        return {
            "bytes": output_bytes,
            "width": img.width,
            "height": img.height,
            "original_width": original_width,
            "original_height": original_height,
            "scale": round(actual_scale, 2),
            "format": output_format,
            "has_alpha": img.mode == "RGBA",
            "sharpened": sharpen,
        }

    def _multi_pass_upscale(self, img: PILImage.Image, target_scale: float) -> PILImage.Image:
        """Multi-pass upscaling for better quality at high scales.

        Instead of going directly to 4x, we do 2x -> 2x which produces
        better results because each pass has less work to do.
        """
        import math

        original_w, original_h = img.size
        target_w = int(original_w * target_scale)
        target_h = int(original_h * target_scale)

        # Calculate number of passes (2x per pass)
        num_passes = max(1, round(math.log2(target_scale)))
        scale_per_pass = target_scale ** (1.0 / num_passes)

        logger.info(f"Multi-pass upscale: {num_passes} passes, {scale_per_pass:.2f}x each")

        current = img
        for i in range(num_passes):
            new_w = int(current.width * scale_per_pass)
            new_h = int(current.height * scale_per_pass)

            # Clamp to target size on last pass
            if i == num_passes - 1:
                new_w = target_w
                new_h = target_h

            current = current.resize((new_w, new_h), PILImage.LANCZOS)

        return current

    def _apply_sharpening(self, img: PILImage.Image, factor: float) -> PILImage.Image:
        """Apply subtle sharpening to restore detail lost during upscaling."""
        # Use UnsharpMask for better control than simple sharpen
        # radius=1.5, percent=150, threshold=3 is a good starting point
        img = img.filter(ImageFilter.UnsharpMask(
            radius=1.5,
            percent=int(150 * factor),
            threshold=3,
        ))
        return img

    def is_configured(self) -> bool:
        """Pillow upscale is always configured (Pillow is a core dependency)."""
        return True

    @staticmethod
    def available_methods() -> list[dict]:
        """List available upscale methods."""
        return [
            {
                "id": "lanczos",
                "name": "LANCZOS (Default)",
                "description": "High-quality antialiased resampling",
                "default": True,
            },
            {
                "id": "multi_pass",
                "name": "Multi-Pass LANCZOS",
                "description": "Multiple 2x passes for better quality at high scales",
                "default": True,
            },
        ]
