"""Tests for real AI providers: rembg background removal, Pillow upscaling.

Covers:
  - RembgProvider: availability, capabilities, background removal, model selection
  - PillowUpscaleProvider: availability, capabilities, upscaling, sharpening, multi-pass
  - Integration: both providers work through utilities service
"""

import io
import struct
import pytest
from pathlib import Path

from app.extensions import db
from app.models.user import User
from app.models.generation import Generation
from app.models.image import Image
from app.models.image_version import ImageVersion
from app.services.ai_provider import (
    StubProvider,
    ProviderCapabilities,
    get_provider,
    list_providers,
)


# ============================================================
# HELPERS
# ============================================================

def make_png_bytes(width=100, height=100, color=(100, 150, 200)):
    """Create a valid PNG with actual pixel data."""
    from PIL import Image as PILImage
    import io

    img = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_rgba_png_bytes(width=100, height=100):
    """Create a valid RGBA PNG with transparency."""
    from PIL import Image as PILImage
    import io

    img = PILImage.new("RGBA", (width, height), color=(100, 150, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_user(email="provider@test.com", username="provideruser", password="securepass123!"):
    user = User(email=email, username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def create_image_with_file(user_id, db_ext, width=256, height=256, filename="test_provider.png"):
    """Create an image record with a real file on disk."""
    from app.config import BASE_DIR

    gen = Generation(
        user_id=user_id,
        prompt="test provider image",
        provider="stub",
        status="completed",
    )
    db_ext.session.add(gen)
    db_ext.session.flush()

    upload_dir = BASE_DIR / "uploads" / "providers" / str(user_id) / "images"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename

    from PIL import Image as PILImage
    img = PILImage.new("RGB", (width, height), color=(100, 150, 200))
    img.save(str(file_path), format="PNG")

    image = Image(
        generation_id=gen.id,
        user_id=user_id,
        filename=filename,
        file_path=str(file_path),
        width=width,
        height=height,
        file_size=file_path.stat().st_size,
    )
    db_ext.session.add(image)
    db_ext.session.commit()
    return image


@pytest.fixture
def logged_in_client(client, db):
    """Register and login a test user."""
    client.post("/signup", data={
        "username": "provideruser",
        "email": "provider@test.com",
        "password": "securepass123!",
        "confirm_password": "securepass123!",
    }, follow_redirects=True)
    client.post("/login", data={
        "email": "provider@test.com",
        "password": "securepass123!",
    }, follow_redirects=True)
    return client


# ============================================================
# REMBG PROVIDER TESTS
# ============================================================

class TestRembgProvider:
    """Test the rembg background removal provider."""

    def test_rembg_is_available(self):
        """rembg should be importable and usable."""
        try:
            from app.services.providers.rembg_provider import _is_rembg_usable
            if not _is_rembg_usable():
                pytest.skip("rembg not usable (runtime dependency issue)")
            assert True
        except ImportError:
            pytest.skip("rembg not installed")

    def test_rembg_provider_capabilities(self):
        """Rembg provider should have correct capabilities."""
        try:
            from app.services.providers.rembg_provider import RembgProvider
        except ImportError:
            pytest.skip("rembg not installed")

        provider = RembgProvider()
        caps = provider.get_capabilities()

        assert caps.supports("background_removal") is True
        assert caps.supports("transparency") is True
        assert caps.supports("upscale") is False
        assert caps.supports("text_to_image") is False
        assert caps.supports("image_understanding") is False

    def test_rembg_provider_is_configured(self):
        """Rembg provider should report configuration status correctly."""
        try:
            from app.services.providers.rembg_provider import RembgProvider, _is_rembg_usable
        except ImportError:
            pytest.skip("rembg not installed")

        provider = RembgProvider()
        usable = _is_rembg_usable()
        assert provider.is_configured() == usable

    def test_rembg_provider_name(self):
        """Rembg provider should have correct name."""
        try:
            from app.services.providers.rembg_provider import RembgProvider
        except ImportError:
            pytest.skip("rembg not installed")

        provider = RembgProvider()
        assert provider.name == "rembg"
        assert provider.display_name == "Rembg (Local AI)"

    def test_rembg_text_to_image_fails(self):
        """Rembg should not support text-to-image."""
        try:
            from app.services.providers.rembg_provider import RembgProvider
        except ImportError:
            pytest.skip("rembg not installed")

        provider = RembgProvider()
        result = provider.text_to_image("test prompt")
        assert result.success is False
        assert "does not support" in result.error.lower()

    def test_rembg_remove_background(self):
        """Rembg should successfully remove background from an image."""
        try:
            from app.services.providers.rembg_provider import RembgProvider
        except ImportError:
            pytest.skip("rembg not installed")

        provider = RembgProvider()
        image_bytes = make_png_bytes(128, 128)

        try:
            result = provider.remove_background(image_bytes)
        except RuntimeError as e:
            pytest.skip(f"rembg runtime issue: {e}")

        assert "bytes" in result
        assert "width" in result
        assert "height" in result
        assert result["width"] == 128
        assert result["height"] == 128
        assert result["has_alpha"] is True
        assert result["format"] == "png"
        assert len(result["bytes"]) > 0

    def test_rembg_output_is_transparent_png(self):
        """Rembg output should be a valid transparent PNG."""
        try:
            from app.services.providers.rembg_provider import RembgProvider
        except ImportError:
            pytest.skip("rembg not installed")

        provider = RembgProvider()
        image_bytes = make_png_bytes(64, 64)

        try:
            result = provider.remove_background(image_bytes)
        except RuntimeError as e:
            pytest.skip(f"rembg runtime issue: {e}")

        # Verify it's a valid PNG
        output_bytes = result["bytes"]
        assert output_bytes[:8] == b'\x89PNG\r\n\x1a\n'

        # Verify it has alpha channel
        from PIL import Image as PILImage
        img = PILImage.open(io.BytesIO(output_bytes))
        assert img.mode == "RGBA"

    def test_rembg_available_models(self):
        """Rembg should list available models."""
        try:
            from app.services.providers.rembg_provider import RembgProvider
        except ImportError:
            pytest.skip("rembg not installed")

        models = RembgProvider.available_models()
        assert len(models) >= 4
        model_ids = [m["id"] for m in models]
        assert "u2net" in model_ids
        assert "isnet-general-use" in model_ids

    def test_rembg_registered_in_registry(self):
        """Rembg should be registered in the provider registry when usable."""
        try:
            from app.services.providers.rembg_provider import _is_rembg_usable
            if not _is_rembg_usable():
                pytest.skip("rembg not usable")
        except ImportError:
            pytest.skip("rembg not installed")
        providers = list_providers()
        assert "rembg" in providers

    def test_rembg_get_from_registry(self):
        """Should be able to get rembg from registry when usable."""
        try:
            from app.services.providers.rembg_provider import RembgProvider, _is_rembg_usable
            if not _is_rembg_usable():
                pytest.skip("rembg not usable")
        except ImportError:
            pytest.skip("rembg not installed")

        provider = get_provider("rembg")
        assert isinstance(provider, RembgProvider)


# ============================================================
# PILLOW UPSCALE PROVIDER TESTS
# ============================================================

class TestPillowUpscaleProvider:
    """Test the Pillow upscaling provider."""

    def test_pillow_provider_capabilities(self):
        """Pillow provider should have correct capabilities."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider()
        caps = provider.get_capabilities()

        assert caps.supports("upscale") is True
        assert caps.supports("background_removal") is False
        assert caps.supports("transparency") is False
        assert caps.supports("text_to_image") is False

    def test_pillow_provider_is_configured(self):
        """Pillow provider should always be configured."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider()
        assert provider.is_configured() is True

    def test_pillow_provider_name(self):
        """Pillow provider should have correct name."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider()
        assert provider.name == "pillow_upscale"
        assert provider.display_name == "AI Upscale (Pillow)"

    def test_pillow_text_to_image_fails(self):
        """Pillow should not support text-to-image."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider()
        result = provider.text_to_image("test prompt")
        assert result.success is False
        assert "does not support" in result.error.lower()

    def test_pillow_upscale_2x(self):
        """Pillow should upscale 2x correctly."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider()
        image_bytes = make_png_bytes(128, 128)

        result = provider.upscale(image_bytes, scale=2.0)

        assert result["width"] == 256
        assert result["height"] == 256
        assert result["original_width"] == 128
        assert result["original_height"] == 128
        assert result["scale"] == 2.0
        assert len(result["bytes"]) > 0

    def test_pillow_upscale_4x(self):
        """Pillow should upscale 4x correctly."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider()
        image_bytes = make_png_bytes(64, 64)

        result = provider.upscale(image_bytes, scale=4.0)

        assert result["width"] == 256
        assert result["height"] == 256
        assert result["scale"] == 4.0

    def test_pillow_upscale_3x(self):
        """Pillow should upscale 3x correctly."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider()
        image_bytes = make_png_bytes(100, 100)

        result = provider.upscale(image_bytes, scale=3.0)

        assert result["width"] == 300
        assert result["height"] == 300
        assert result["scale"] == 3.0

    def test_pillow_upscale_preserves_alpha(self):
        """Pillow should preserve alpha channel."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider()
        image_bytes = make_rgba_png_bytes(64, 64)

        result = provider.upscale(image_bytes, scale=2.0)

        assert result["has_alpha"] is True
        from PIL import Image as PILImage
        img = PILImage.open(io.BytesIO(result["bytes"]))
        assert img.mode == "RGBA"

    def test_pillow_upscale_with_sharpening(self):
        """Pillow should apply sharpening when enabled."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider(sharpen=True)
        image_bytes = make_png_bytes(64, 64)

        result = provider.upscale(image_bytes, scale=2.0, sharpen=True)
        assert result["sharpened"] is True

    def test_pillow_upscale_without_sharpening(self):
        """Pillow should skip sharpening when disabled."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider(sharpen=False)
        image_bytes = make_png_bytes(64, 64)

        result = provider.upscale(image_bytes, scale=2.0, sharpen=False)
        assert result["sharpened"] is False

    def test_pillow_upscale_jpeg_output(self):
        """Pillow should output JPEG when requested."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider()
        image_bytes = make_png_bytes(64, 64)

        result = provider.upscale(image_bytes, scale=2.0, output_format="jpeg")

        assert result["format"] == "jpeg"
        # JPEG should start with FF D8 FF
        assert result["bytes"][:3] == b'\xff\xd8\xff'

    def test_pillow_upscale_webp_output(self):
        """Pillow should output WebP when requested."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider()
        image_bytes = make_png_bytes(64, 64)

        result = provider.upscale(image_bytes, scale=2.0, output_format="webp")

        assert result["format"] == "webp"
        # WebP should start with RIFF
        assert result["bytes"][:4] == b'RIFF'

    def test_pillow_upscale_clamps_scale(self):
        """Pillow should clamp scale to valid range."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider()
        image_bytes = make_png_bytes(64, 64)

        # Scale too high
        result = provider.upscale(image_bytes, scale=10.0)
        assert result["scale"] <= 4.0

        # Scale too low
        result = provider.upscale(image_bytes, scale=0.1)
        assert result["scale"] >= 1.0

    def test_pillow_multi_pass_upscale(self):
        """Pillow multi-pass should produce correct dimensions."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = PillowUpscaleProvider(multi_pass=True)
        image_bytes = make_png_bytes(64, 64)

        result = provider.upscale(image_bytes, scale=4.0)

        assert result["width"] == 256
        assert result["height"] == 256

    def test_pillow_registered_in_registry(self):
        """Pillow provider should be registered in the provider registry."""
        providers = list_providers()
        assert "pillow_upscale" in providers

    def test_pillow_get_from_registry(self):
        """Should be able to get pillow_upscale from registry."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        provider = get_provider("pillow_upscale")
        assert isinstance(provider, PillowUpscaleProvider)

    def test_pillow_available_methods(self):
        """Pillow should list available methods."""
        from app.services.providers.pillow_upscale_provider import PillowUpscaleProvider

        methods = PillowUpscaleProvider.available_methods()
        assert len(methods) >= 2
        method_ids = [m["id"] for m in methods]
        assert "lanczos" in method_ids
        assert "multi_pass" in method_ids


# ============================================================
# INTEGRATION TESTS (via utilities API)
# ============================================================

class TestProviderIntegration:
    """Test that real providers work through the utilities API."""

    def test_capabilities_include_rembg(self, logged_in_client, db):
        """Capabilities should include rembg when installed."""
        resp = logged_in_client.get("/api/v1/utilities/capabilities")
        assert resp.status_code == 200
        data = resp.get_json()

        if "rembg" in data["capabilities"]:
            assert data["capabilities"]["rembg"]["background_removal"] is True
            assert data["capabilities"]["rembg"]["transparency"] is True

    def test_capabilities_include_pillow_upscale(self, logged_in_client, db):
        """Capabilities should include pillow_upscale."""
        resp = logged_in_client.get("/api/v1/utilities/capabilities")
        assert resp.status_code == 200
        data = resp.get_json()

        assert "pillow_upscale" in data["capabilities"]
        assert data["capabilities"]["pillow_upscale"]["upscale"] is True

    def test_upscale_with_pillow_provider(self, logged_in_client, db):
        """Upscale should work with pillow_upscale provider."""
        user = User.query.filter_by(username="provideruser").first()
        image = create_image_with_file(user.id, db, width=128, height=128)

        resp = logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={
                "image_id": image.id,
                "scale": 2.0,
                "provider": "pillow_upscale",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["upscaled_width"] == 256
        assert data["upscaled_height"] == 256

    def test_bg_removal_with_rembg(self, logged_in_client, db):
        """Background removal should work with rembg provider."""
        try:
            from app.services.providers.rembg_provider import _is_rembg_usable
            if not _is_rembg_usable():
                pytest.skip("rembg not usable (runtime dependency issue)")
        except ImportError:
            pytest.skip("rembg not installed")

        user = User.query.filter_by(username="provideruser").first()
        image = create_image_with_file(user.id, db, width=128, height=128)

        resp = logged_in_client.post(
            "/api/v1/utilities/remove-background",
            json={
                "image_id": image.id,
                "provider": "rembg",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "version" in data
        assert data["has_alpha"] is True

    def test_batch_upscale_with_pillow(self, logged_in_client, db):
        """Batch upscale should work with pillow_upscale provider."""
        user = User.query.filter_by(username="provideruser").first()
        img1 = create_image_with_file(user.id, db, width=128, height=128, filename="batch_p1.png")
        img2 = create_image_with_file(user.id, db, width=64, height=64, filename="batch_p2.png")

        resp = logged_in_client.post(
            "/api/v1/utilities/batch/upscale",
            json={
                "image_ids": [img1.id, img2.id],
                "scale": 2.0,
                "provider": "pillow_upscale",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 2
        for r in data["results"]:
            assert r["status"] == "success"

    def test_history_tracked_for_real_providers(self, logged_in_client, db):
        """History should track operations from real providers."""
        user = User.query.filter_by(username="provideruser").first()
        image = create_image_with_file(user.id, db, width=128, height=128)

        logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={
                "image_id": image.id,
                "scale": 2.0,
                "provider": "pillow_upscale",
            },
        )

        resp = logged_in_client.get("/api/v1/utilities/history")
        data = resp.get_json()
        assert data["total"] >= 1
        ops = data["operations"]
        assert any(op["provider"] == "pillow_upscale" for op in ops)


# ============================================================
# PROVIDER AVAILABILITY TESTS
# ============================================================

class TestProviderAvailability:
    """Test that providers are properly registered and available."""

    def test_all_providers_registered(self):
        """All expected providers should be registered."""
        providers = list_providers()
        assert "stub" in providers
        assert "pillow_upscale" in providers
        # rembg may not be usable due to runtime deps
        # assert "rembg" in providers

    def test_stub_always_available(self):
        """Stub provider should always be available."""
        provider = get_provider("stub")
        assert provider.is_configured() is True

    def test_pillow_always_available(self):
        """Pillow upscale should always be available."""
        provider = get_provider("pillow_upscale")
        assert provider.is_configured() is True

    def test_unknown_provider_raises(self):
        """Unknown provider should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider("nonexistent_provider_xyz")
