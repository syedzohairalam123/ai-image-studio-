import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProviderCapabilities:
    """Capabilities a provider supports."""

    text_to_image: bool = False
    image_edit: bool = False
    variations: bool = False
    inpainting: bool = False
    outpainting: bool = False
    upscale: bool = False
    transparency: bool = False
    background_removal: bool = False
    image_understanding: bool = False
    multi_reference: bool = False
    seed: bool = False
    negative_prompt: bool = False
    multiple_references: bool = False

    def supports(self, capability: str) -> bool:
        return getattr(self, capability, False)

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class GenerationResult:
    """Standard result from a provider generation."""

    success: bool
    images: list = field(default_factory=list)
    error: Optional[str] = None
    provider_metadata: dict = field(default_factory=dict)


@dataclass
class ImageData:
    """Standard image data from a provider."""

    url: Optional[str] = None
    file_bytes: Optional[bytes] = None
    filename: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    seed: Optional[int] = None
    metadata: dict = field(default_factory=dict)


class AIProvider(ABC):
    """Abstract base class for all AI image providers."""

    name: str = "base"
    display_name: str = "Base Provider"
    capabilities: ProviderCapabilities = ProviderCapabilities()

    def __init__(self, api_key: str = "", **kwargs):
        self.api_key = api_key
        self.config = kwargs

    @abstractmethod
    def text_to_image(self, prompt: str, **kwargs) -> GenerationResult:
        """Generate images from a text prompt."""
        ...

    def get_capabilities(self) -> ProviderCapabilities:
        return self.capabilities

    def supports(self, capability: str) -> bool:
        return self.capabilities.supports(capability)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def __repr__(self):
        return f"<{self.__class__.__name__} ({self.display_name})>"


class StubProvider(AIProvider):
    """Stub provider for development and testing."""

    name = "stub"
    display_name = "Stub Provider (Dev)"
    capabilities = ProviderCapabilities(
        text_to_image=True,
        image_edit=True,
        variations=True,
        inpainting=True,
        outpainting=True,
        upscale=False,
        transparency=False,
        background_removal=False,
        image_understanding=True,
        multi_reference=True,
        seed=True,
        negative_prompt=True,
        multiple_references=True,
    )

    def text_to_image(self, prompt: str, **kwargs) -> GenerationResult:
        """Generate real, unique images with the local procedural art engine.

        No external API call is made — everything is synthesized on-device
        (numpy/scipy/Pillow) so the stub provider works fully offline while
        still producing a genuinely different image per prompt/seed/style,
        not a static placeholder.
        """
        from app.services.procedural_art import generate_art

        count = max(1, min(int(kwargs.get("count", 1)), 8))
        reference_strength = kwargs.get("reference_strength")
        reference_paths = kwargs.get("reference_paths", [])
        base_seed = kwargs.get("seed")
        width = int(kwargs.get("width", 512))
        height = int(kwargs.get("height", 512))
        style = kwargs.get("style", "auto") or "auto"
        negative_prompt = kwargs.get("negative_prompt")

        images = []
        for i in range(count):
            # Always vary per batch item, even when the caller didn't pass an
            # explicit seed — otherwise a "generate 4" request would render
            # the same artwork four times.
            effective_seed = (base_seed if base_seed is not None else 0) + i

            # A reference image nudges the palette/mood deterministically by
            # folding its path into the prompt salt — a lightweight stand-in
            # for "reference-guided" generation without needing a real model.
            effective_prompt = prompt
            if reference_paths:
                effective_prompt = f"{prompt} ::ref::{reference_paths[0]}"

            try:
                image_bytes = generate_art(
                    prompt=effective_prompt,
                    width=width,
                    height=height,
                    style=style,
                    seed=effective_seed,
                    negative_prompt=negative_prompt,
                )
            except Exception:
                image_bytes = None

            metadata = {"stub": True, "prompt": prompt, "index": i, "engine": "procedural_art"}
            if reference_strength is not None:
                metadata["reference_strength"] = reference_strength
            if reference_paths:
                metadata["reference_count"] = len(reference_paths)

            images.append(ImageData(
                file_bytes=image_bytes,
                filename=f"stub_generated_{i}.png",
                width=width,
                height=height,
                seed=effective_seed,
                metadata=metadata,
            ))
        return GenerationResult(
            success=True,
            images=images,
            provider_metadata={"provider": self.name, "engine": "procedural_art"},
        )

    def is_configured(self):
        return True  # Stub is always ready


# Provider registry
_PROVIDER_REGISTRY: dict[str, type[AIProvider]] = {
    "stub": StubProvider,
}


# Auto-register real providers if available
def _register_real_providers():
    """Register real AI providers if their dependencies are installed.

    BUGFIX: this used to import each provider from a background thread with
    an 8s join() timeout, intended to guard against a slow/hanging import.
    In practice both providers import back from `app.services.ai_provider`
    (this very module), which is still mid-import on the main thread when
    the background thread starts — a textbook circular-import deadlock via
    CPython's per-module import lock. The result was that the "timeout"
    fired on *every* run (masking the deadlock as slowness), both real
    providers silently never registered, and startup paid a flat 16s tax
    for nothing. Neither import does any network I/O or long-running work,
    so a plain try/except is the correct, and much faster, guard.
    """
    try:
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider
        _PROVIDER_REGISTRY["pillow_upscale"] = PillowUpscaleProvider
    except Exception as exc:
        import warnings
        warnings.warn(f"Provider 'pillow_upscale' unavailable: {exc}", RuntimeWarning)

    try:
        from app.services.providers.rembg_provider import RembgProvider, _is_rembg_usable
        if _is_rembg_usable():
            _PROVIDER_REGISTRY["rembg"] = RembgProvider
    except Exception as exc:
        import warnings
        warnings.warn(f"Provider 'rembg' unavailable: {exc}", RuntimeWarning)

    try:
        from app.services.providers.pollinations_provider import PollinationsProvider
        _PROVIDER_REGISTRY["pollinations"] = PollinationsProvider
    except Exception as exc:
        import warnings
        warnings.warn(f"Provider 'pollinations' unavailable: {exc}", RuntimeWarning)


_register_real_providers()


def register_provider(name: str, provider_class: type[AIProvider]):
    """Register a new provider class."""
    _PROVIDER_REGISTRY[name] = provider_class


def get_provider(name: str, **kwargs) -> AIProvider:
    """Get a provider instance by name."""
    provider_class = _PROVIDER_REGISTRY.get(name)
    if provider_class is None:
        raise ValueError(f"Unknown provider: {name}. Available: {list(_PROVIDER_REGISTRY.keys())}")
    return provider_class(**kwargs)


def list_providers() -> list[str]:
    """List all registered provider names."""
    return list(_PROVIDER_REGISTRY.keys())
