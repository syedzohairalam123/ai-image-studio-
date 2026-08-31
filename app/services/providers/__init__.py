"""Real AI providers for upscale and background removal.

These providers wrap actual ML libraries:
- rembg: Background removal using u2net/other models
- Pillow: High-quality upscaling (always available)
"""

from app.services.providers.rembg_provider import RembgProvider
from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

__all__ = ["RembgProvider", "PillowUpscaleProvider"]
