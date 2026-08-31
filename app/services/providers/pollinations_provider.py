"""Pollinations.ai provider — real, free, key-less text-to-image generation.

Unlike the ``stub`` provider (local procedural art with no semantic
understanding of the prompt), this calls a real hosted image model
(Flux, via https://image.pollinations.ai) that actually understands and
renders what the prompt describes — "a cat" produces an actual cat.

No signup or API key is required for this service; it's a widely used,
open-source, community-run project (see https://pollinations.ai). An
optional ``api_key``/referrer can still be passed through for higher
priority access if the user later sets one up, but the provider works
fully anonymously out of the box.

Because this depends on outbound internet access, every call degrades
gracefully: if the request fails for any reason (offline machine, the
service being temporarily down, a corporate firewall, a timeout), the
affected image is generated locally via the procedural art engine
instead of failing the whole batch — the caller always gets back
``count`` images, just annotated (in metadata) with which path produced
each one.
"""

from __future__ import annotations

import random
import urllib.parse
from typing import Optional

from app.services.ai_provider import AIProvider, ProviderCapabilities, GenerationResult, ImageData

BASE_URL = "https://image.pollinations.ai/prompt/"

# Map the app's existing style chips (see generate.html `data-style`) to a
# Pollinations model + an optional prompt suffix for extra steering. Flux
# variants are the current best-quality options Pollinations hosts.
_STYLE_TO_MODEL = {
    "auto": ("flux", ""),
    "photo": ("flux-realism", ", photorealistic, DSLR photo, sharp focus"),
    "art": ("flux", ", digital art, detailed illustration"),
    "paint": ("flux", ", oil painting, painterly brushstrokes"),
    "anime": ("flux-anime", ", anime style"),
    "3d": ("flux-3d", ", 3d render, octane render, studio lighting"),
    "pixel": ("turbo", ", pixel art, 8-bit"),
    "minimal": ("flux", ", minimalist, clean, simple composition"),
}

_DEFAULT_TIMEOUT = (10, 90)  # (connect, read) seconds — real generation isn't instant


class PollinationsProvider(AIProvider):
    """Real text-to-image generation via the free Pollinations.ai API."""

    name = "pollinations"
    display_name = "Pollinations.ai (Free, real AI)"
    capabilities = ProviderCapabilities(
        text_to_image=True,
        seed=True,
        negative_prompt=True,
    )

    def text_to_image(self, prompt: str, **kwargs) -> GenerationResult:
        count = max(1, min(int(kwargs.get("count", 1)), 4))
        width = int(kwargs.get("width", 512))
        height = int(kwargs.get("height", 512))
        style = kwargs.get("style", "auto") or "auto"
        base_seed = kwargs.get("seed")
        negative_prompt = kwargs.get("negative_prompt")

        model, suffix = _STYLE_TO_MODEL.get(style, _STYLE_TO_MODEL["auto"])
        full_prompt = f"{prompt}{suffix}"

        images = []
        any_real = False
        for i in range(count):
            effective_seed = (base_seed if base_seed is not None else random.randint(1, 2_000_000_000)) + i

            image_bytes, source = self._generate_one(
                full_prompt, width, height, model, effective_seed, negative_prompt
            )
            if source == "pollinations":
                any_real = True

            images.append(ImageData(
                file_bytes=image_bytes,
                filename=f"pollinations_{i}.png",
                width=width,
                height=height,
                seed=effective_seed,
                metadata={"engine": source, "model": model if source == "pollinations" else "procedural_art"},
            ))

        return GenerationResult(
            success=True,
            images=images,
            provider_metadata={
                "provider": self.name,
                "model": model,
                "any_real_generation": any_real,
            },
        )

    def _generate_one(self, prompt: str, width: int, height: int, model: str,
                       seed: int, negative_prompt: Optional[str]):
        """Try the real API once; on any failure, fall back to the local
        procedural engine for just this image so the batch never comes back
        empty. Returns (image_bytes, source) where source is "pollinations"
        or "procedural_fallback"."""
        try:
            import requests

            encoded_prompt = urllib.parse.quote(prompt)
            url = f"{BASE_URL}{encoded_prompt}"
            params = {
                "width": width,
                "height": height,
                "model": model,
                "seed": seed,
                "nologo": "true",
                "safe": "true",
                "referrer": "ai-image-studio",
            }
            if negative_prompt:
                params["negative"] = negative_prompt
            if self.api_key:
                params["token"] = self.api_key

            resp = requests.get(url, params=params, timeout=_DEFAULT_TIMEOUT)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "image" not in content_type or len(resp.content) < 500:
                raise ValueError(f"Unexpected response ({content_type}, {len(resp.content)} bytes)")
            return resp.content, "pollinations"
        except Exception:
            from app.services.procedural_art import generate_art
            fallback_bytes = generate_art(prompt=prompt, width=width, height=height, seed=seed)
            return fallback_bytes, "procedural_fallback"

    def is_reachable(self) -> bool:
        """Lightweight connectivity probe used by the capabilities endpoint
        so the UI can tell the person whether real generation is currently
        available or if it will fall back to the local engine."""
        try:
            import requests
            resp = requests.get(
                "https://image.pollinations.ai/", timeout=(5, 8)
            )
            return resp.status_code < 500
        except Exception:
            return False
