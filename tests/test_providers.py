"""Tests for the AI provider abstraction."""

from app.services.ai_provider import (
    StubProvider,
    get_provider,
    list_providers,
    ProviderCapabilities,
)


def test_stub_provider_text_to_image():
    """Stub provider generates a real, unique procedurally-rendered image
    (not a static placeholder) using the local procedural art engine."""
    provider = StubProvider()
    result = provider.text_to_image("a beautiful sunset")

    assert result.success is True
    assert len(result.images) == 1
    assert result.images[0].filename == "stub_generated_0.png"
    assert result.images[0].width == 512
    # Real PNG bytes should be present and non-trivial in size.
    assert result.images[0].file_bytes is not None
    assert len(result.images[0].file_bytes) > 500
    assert result.images[0].file_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_stub_provider_is_deterministic_per_prompt():
    """Same prompt + same seed reproduces the same image; different prompts
    (with an explicit seed) still diverge visually."""
    provider = StubProvider()
    a = provider.text_to_image("a quiet forest", seed=7)
    b = provider.text_to_image("a quiet forest", seed=7)
    c = provider.text_to_image("a busy cyberpunk city", seed=7)

    assert a.images[0].file_bytes == b.images[0].file_bytes
    assert a.images[0].file_bytes != c.images[0].file_bytes


def test_stub_provider_batch_produces_distinct_images():
    """Requesting multiple images in one call should not repeat the same
    artwork count times."""
    provider = StubProvider()
    result = provider.text_to_image("an abstract pattern", count=3)

    assert len(result.images) == 3
    byte_sets = {img.file_bytes for img in result.images}
    assert len(byte_sets) == 3


def test_stub_provider_with_params():
    """Test stub provider passes parameters through."""
    provider = StubProvider()
    result = provider.text_to_image("a cat", width=1024, height=768, seed=42)

    assert result.images[0].width == 1024
    assert result.images[0].height == 768
    assert result.images[0].seed == 42


def test_stub_provider_count():
    """Test stub provider respects count parameter."""
    provider = StubProvider()
    result = provider.text_to_image("a cat", count=3)
    assert len(result.images) == 3
    for img in result.images:
        assert img.width == 512


def test_provider_capabilities():
    """Test capability checking."""
    caps = ProviderCapabilities(text_to_image=True, seed=True)
    assert caps.supports("text_to_image") is True
    assert caps.supports("seed") is True
    assert caps.supports("inpainting") is False


def test_get_provider():
    """Test provider registry."""
    provider = get_provider("stub")
    assert isinstance(provider, StubProvider)
    assert provider.is_configured()


def test_get_unknown_provider():
    """Test unknown provider raises error."""
    try:
        get_provider("nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown provider" in str(e)


def test_list_providers():
    """Test listing registered providers."""
    providers = list_providers()
    assert "stub" in providers
