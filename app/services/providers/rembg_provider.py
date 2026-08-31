"""Background removal provider using rembg library.

Uses the u2net model for high-quality background removal.
Produces real transparent PNG output - never fakes transparency.

Requirements:
    pip install rembg

Usage:
    Provider is auto-registered if rembg is installed.
    Set REMBG_MODEL=u2net (default) or other model name in .env.
"""

import io
import logging
from typing import Optional

from app.services.ai_provider import AIProvider, ProviderCapabilities, GenerationResult, ImageData

logger = logging.getLogger(__name__)


def _is_rembg_available() -> bool:
    """Check if rembg is importable."""
    try:
        import rembg  # noqa: F401
        return True
    except ImportError:
        return False


def _is_rembg_usable() -> bool:
    """Check if rembg can actually run (import + runtime check)."""
    try:
        from rembg import remove  # noqa: F401
        return True
    except (ImportError, Exception):
        return False


class RembgProvider(AIProvider):
    """Background removal provider using rembg.

    Supports multiple models:
    - u2net: General purpose (default, best quality)
    - u2net_human_seg: Optimized for human portraits
    - u2net_cloth_seg: Optimized for clothing
    - isnet-general-use: General purpose, newer model
    - isnet-anime: Optimized for anime/illustrations
    """

    name = "rembg"
    display_name = "Rembg (Local AI)"
    capabilities = ProviderCapabilities(
        text_to_image=False,
        image_edit=False,
        variations=False,
        inpainting=False,
        outpainting=False,
        upscale=False,
        transparency=True,
        background_removal=True,
        image_understanding=False,
        multi_reference=False,
        seed=False,
        negative_prompt=False,
        multiple_references=False,
    )

    def __init__(self, api_key: str = "", **kwargs):
        super().__init__(api_key, **kwargs)
        self.model_name = kwargs.get("model", "u2net")
        self._session = None

    def text_to_image(self, prompt: str, **kwargs) -> GenerationResult:
        """Rembg doesn't support text-to-image."""
        return GenerationResult(
            success=False,
            error="Rembg does not support text-to-image generation. Use it for background removal.",
        )

    def remove_background(self, image_bytes: bytes, **kwargs) -> dict:
        """Remove background from an image.

        Args:
            image_bytes: Raw image bytes (PNG, JPEG, WebP)
            **kwargs:
                model: Override model name
                alpha_matting: Enable alpha matting for better edges
                alpha_matting_foreground_threshold: Foreground threshold (0-255)
                alpha_matting_background_threshold: Background threshold (0-255)
                alpha_matting_erode_size: Erosion size

        Returns:
            dict with keys:
                bytes: Transparent PNG bytes
                width: Output width
                height: Output height
                model: Model used
        """
        try:
            from rembg import remove, new_session
        except (ImportError, Exception) as e:
            raise RuntimeError(
                f"rembg is installed but cannot run: {e}. "
                "Check that numba/pymatting dependencies are compatible."
            ) from e

        model = kwargs.get("model", self.model_name)
        alpha_matting = kwargs.get("alpha_matting", False)

        # Create session (cached for reuse)
        if self._session is None or getattr(self, "_current_model", None) != model:
            logger.info(f"Creating rembg session with model: {model}")
            self._session = new_session(model)
            self._current_model = model

        # Build remove kwargs
        remove_kwargs = {
            "session": self._session,
        }

        if alpha_matting:
            remove_kwargs["alpha_matting"] = True
            remove_kwargs["alpha_matting_foreground_threshold"] = kwargs.get(
                "alpha_matting_foreground_threshold", 240
            )
            remove_kwargs["alpha_matting_background_threshold"] = kwargs.get(
                "alpha_matting_background_threshold", 10
            )
            remove_kwargs["alpha_matting_erode_size"] = kwargs.get(
                "alpha_matting_erode_size", 10
            )

        logger.info(f"Removing background with model={model}, alpha_matting={alpha_matting}")

        # Process image
        output_bytes = remove(image_bytes, **remove_kwargs)

        # Get dimensions of output
        from PIL import Image as PILImage
        img = PILImage.open(io.BytesIO(output_bytes))

        return {
            "bytes": output_bytes,
            "width": img.width,
            "height": img.height,
            "model": model,
            "format": "png",
            "has_alpha": img.mode == "RGBA",
        }

    def is_configured(self) -> bool:
        """Rembg is configured if the library can actually run."""
        return _is_rembg_usable()

    @staticmethod
    def available_models() -> list[dict]:
        """List available rembg models with descriptions."""
        return [
            {
                "id": "u2net",
                "name": "U2-Net",
                "description": "General purpose, best overall quality",
                "default": True,
            },
            {
                "id": "u2net_human_seg",
                "name": "U2-Net Human Segmentation",
                "description": "Optimized for human portraits",
                "default": False,
            },
            {
                "id": "u2net_cloth_seg",
                "name": "U2-Net Cloth Segmentation",
                "description": "Optimized for clothing",
                "default": False,
            },
            {
                "id": "isnet-general-use",
                "name": "ISNet General",
                "description": "Newer general purpose model",
                "default": False,
            },
            {
                "id": "isnet-anime",
                "name": "ISNet Anime",
                "description": "Optimized for anime and illustrations",
                "default": False,
            },
            {
                "id": "silueta",
                "name": "Silueta",
                "description": "Lightweight, fast processing",
                "default": False,
            },
        ]
