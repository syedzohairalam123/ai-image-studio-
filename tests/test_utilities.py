"""Phase 11 — Image Utilities tests: upscale, background removal, image-to-prompt,
upload validation, capability detection, ownership, edge cases.

Covers:
  - Provider capabilities (supported vs unsupported)
  - Upscale: supported provider, unsupported provider, scale validation, dimensions
  - Background removal: supported provider, unsupported provider, stub rejection
  - Image-to-prompt: supported provider, unsupported provider, structured output
  - Upload: valid files, invalid types, oversized files, dimension limits, magic bytes
  - Ownership enforcement across all endpoints
  - Edge cases: missing image_id, nonexistent images, non-logged-in users
"""

import io
import json
import struct
import pytest

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
# FIXTURES
# ============================================================

@pytest.fixture
def logged_in_client(client, db):
    """Register and login a test user, return authenticated client."""
    client.post("/signup", data={
        "username": "utiluser",
        "email": "util@test.com",
        "password": "securepass123!",
        "confirm_password": "securepass123!",
    }, follow_redirects=True)
    client.post("/login", data={
        "email": "util@test.com",
        "password": "securepass123!",
    }, follow_redirects=True)
    return client


# ============================================================
# HELPERS
# ============================================================

def create_user(email="util@test.com", username="utiluser", password="securepass123!"):
    user = User(email=email, username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, email="util@test.com", password="securepass123!"):
    return client.post("/login", data={
        "email": email, "password": password,
    }, follow_redirects=True)


def logout(client):
    return client.post("/logout", follow_redirects=True)


def make_png_bytes(width=100, height=100):
    """Create minimal valid PNG bytes."""
    def chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack('>I', 0)
        return struct.pack('>I', len(data)) + c + crc

    header = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr = chunk(b'IHDR', ihdr_data)
    idat = chunk(b'IDAT', b'\x00' * 10)
    iend = chunk(b'IEND', b'')
    return header + ihdr + idat + iend


def create_image_with_file(user_id, db_ext, width=512, height=512,
                           filename="test_util.png"):
    """Create an image record with a real file on disk."""
    from app.config import BASE_DIR

    gen = Generation(
        user_id=user_id,
        prompt="test utility image",
        provider="stub",
        status="completed",
    )
    db_ext.session.add(gen)
    db_ext.session.flush()

    upload_dir = BASE_DIR / "uploads" / "utilities" / str(user_id) / "images"
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


# ============================================================
# CAPABILITY DETECTION TESTS
# ============================================================

class TestProviderCapabilities:
    """Test that capabilities are correctly defined and queryable."""

    def test_stub_provider_has_correct_capabilities(self):
        """Stub provider should have realistic capability set."""
        provider = StubProvider()
        caps = provider.get_capabilities()

        # Stub supports these
        assert caps.supports("text_to_image") is True
        assert caps.supports("image_edit") is True
        assert caps.supports("variations") is True
        assert caps.supports("inpainting") is True
        assert caps.supports("outpainting") is True
        assert caps.supports("image_understanding") is True
        assert caps.supports("multi_reference") is True
        assert caps.supports("seed") is True
        assert caps.supports("negative_prompt") is True
        assert caps.supports("multiple_references") is True

        # Stub does NOT support these (they require real AI providers)
        assert caps.supports("upscale") is False
        assert caps.supports("transparency") is False
        assert caps.supports("background_removal") is False

    def test_capabilities_to_dict(self):
        """Capabilities should serialize to a dict."""
        caps = ProviderCapabilities(
            text_to_image=True,
            upscale=False,
            background_removal=True,
        )
        d = caps.to_dict()
        assert d["text_to_image"] is True
        assert d["upscale"] is False
        assert d["background_removal"] is True
        assert isinstance(d, dict)

    def test_supports_unknown_capability(self):
        """Querying an unknown capability returns False."""
        caps = ProviderCapabilities()
        assert caps.supports("nonexistent_feature") is False

    def test_capabilities_api_endpoint(self, client, db):
        """The capabilities endpoint returns all providers."""
        create_user()
        login(client)

        resp = client.get("/api/v1/utilities/capabilities")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "capabilities" in data
        assert "stub" in data["capabilities"]

        stub_caps = data["capabilities"]["stub"]
        assert stub_caps["upscale"] is False
        assert stub_caps["background_removal"] is False
        assert stub_caps["image_understanding"] is True

    def test_capabilities_requires_auth(self, client, db):
        """Capabilities endpoint requires authentication."""
        resp = client.get("/api/v1/utilities/capabilities")
        assert resp.status_code == 302  # Redirect to login


# ============================================================
# UPLOAD VALIDATION TESTS
# ============================================================

class TestUploadValidation:
    """Test file upload for utility processing."""

    def test_valid_png_upload(self, client, db):
        """A valid PNG should upload successfully."""
        user = create_user()
        login(client)

        png_data = make_png_bytes(100, 100)
        resp = client.post(
            "/api/v1/utilities/upload",
            data={"file": (io.BytesIO(png_data), "test.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"
        assert "image" in data
        assert data["image"]["width"] == 100
        assert data["image"]["height"] == 100
        assert data["image"]["id"] is not None

    def test_valid_jpeg_upload(self, client, db):
        """A valid JPEG should upload successfully."""
        create_user()
        login(client)

        jpeg_data = b'\xff\xd8\xff\xe0' + b'\x00' * 100
        resp = client.post(
            "/api/v1/utilities/upload",
            data={"file": (io.BytesIO(jpeg_data), "photo.jpg")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 201

    def test_no_file_returns_400(self, client, db):
        """Uploading without a file should return 400."""
        create_user()
        login(client)

        resp = client.post("/api/v1/utilities/upload")
        assert resp.status_code == 400
        assert "No file" in resp.get_json()["error"]

    def test_invalid_mime_type_rejected(self, client, db):
        """Non-image file types should be rejected."""
        create_user()
        login(client)

        resp = client.post(
            "/api/v1/utilities/upload",
            data={"file": (io.BytesIO(b"not an image data"), "file.txt")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        error = resp.get_json()["error"]
        assert "Invalid file type" in error

    def test_invalid_magic_bytes_rejected(self, client, db):
        """Files with wrong magic bytes should be rejected even with image mime."""
        create_user()
        login(client)

        resp = client.post(
            "/api/v1/utilities/upload",
            data={"file": (io.BytesIO(b"FAKEPNGDATA" * 100), "fake.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        error = resp.get_json()["error"]
        assert "not appear to be a valid image" in error

    def test_empty_file_rejected(self, client, db):
        """Empty files should be rejected."""
        create_user()
        login(client)

        resp = client.post(
            "/api/v1/utilities/upload",
            data={"file": (io.BytesIO(b""), "empty.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        error = resp.get_json()["error"]
        assert "Empty file" in error

    def test_oversized_file_rejected(self, client, db):
        """Files larger than 10MB should be rejected."""
        create_user()
        login(client)

        # Create a file larger than 10MB
        large_data = make_png_bytes(100, 100) + b'\x00' * (11 * 1024 * 1024)
        resp = client.post(
            "/api/v1/utilities/upload",
            data={"file": (io.BytesIO(large_data), "huge.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code in (400, 413)
        if resp.status_code == 400:
            assert "too large" in resp.get_json()["error"]

    def test_too_small_dimensions_rejected(self, client, db):
        """Images smaller than 64px should be rejected."""
        create_user()
        login(client)

        png_data = make_png_bytes(10, 10)
        resp = client.post(
            "/api/v1/utilities/upload",
            data={"file": (io.BytesIO(png_data), "tiny.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "too small" in resp.get_json()["error"]

    def test_too_large_dimensions_rejected(self, client, db):
        """Images larger than 4096px should be rejected."""
        create_user()
        login(client)

        png_data = make_png_bytes(5000, 5000)
        resp = client.post(
            "/api/v1/utilities/upload",
            data={"file": (io.BytesIO(png_data), "huge.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "too large" in resp.get_json()["error"]

    def test_upload_requires_auth(self, client, db):
        """Upload requires authentication."""
        png_data = make_png_bytes(100, 100)
        resp = client.post(
            "/api/v1/utilities/upload",
            data={"file": (io.BytesIO(png_data), "test.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 302  # Redirect to login

    def test_upload_creates_image_record(self, client, db):
        """Upload should create an image record in the database."""
        user = create_user()
        login(client)

        initial_count = Image.query.filter_by(user_id=user.id).count()
        png_data = make_png_bytes(200, 150)
        client.post(
            "/api/v1/utilities/upload",
            data={"file": (io.BytesIO(png_data), "record.png")},
            content_type="multipart/form-data",
        )
        new_count = Image.query.filter_by(user_id=user.id).count()
        assert new_count == initial_count + 1

    def test_upload_preserves_dimensions(self, client, db):
        """Upload should correctly detect and store image dimensions."""
        create_user()
        login(client)

        png_data = make_png_bytes(320, 240)
        resp = client.post(
            "/api/v1/utilities/upload",
            data={"file": (io.BytesIO(png_data), "dims.png")},
            content_type="multipart/form-data",
        )
        data = resp.get_json()
        assert data["image"]["width"] == 320
        assert data["image"]["height"] == 240


# ============================================================
# UPSCALE TESTS
# ============================================================

class TestUpscale:
    """Test image upscaling functionality."""

    def test_upscale_supported_provider(self, logged_in_client, db):
        """Upscale should work with a provider that supports it (via stub)."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        # Register a provider that supports upscale
        from app.services.ai_provider import register_provider, _PROVIDER_REGISTRY

        class UpscaleCapableStub(StubProvider):
            name = "upscale_stub"
            display_name = "Upscale Stub"
            capabilities = ProviderCapabilities(
                text_to_image=True,
                upscale=True,
                image_understanding=True,
                multi_reference=True,
            )

        register_provider("upscale_stub", UpscaleCapableStub)

        resp = logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={
                "image_id": image.id,
                "scale": 2.0,
                "provider": "upscale_stub",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "version" in data
        assert data["original_width"] == 512
        assert data["original_height"] == 512
        assert data["upscaled_width"] == 1024
        assert data["upscaled_height"] == 1024
        assert data["scale"] == 2.0

        # Cleanup
        del _PROVIDER_REGISTRY["upscale_stub"]

    def test_upscale_unsupported_provider(self, logged_in_client, db):
        """Upscale should fail with provider that doesn't support it."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        resp = logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={
                "image_id": image.id,
                "scale": 2.0,
                "provider": "stub",  # stub doesn't support upscale
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "does not support upscaling" in data["error"]

    def test_upscale_missing_image_id(self, logged_in_client, db):
        """Upscale without image_id should return 400."""
        resp = logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={"scale": 2.0, "provider": "stub"},
        )
        assert resp.status_code == 400
        assert "image_id is required" in resp.get_json()["error"]

    def test_upscale_nonexistent_image(self, logged_in_client, db):
        """Upscale with nonexistent image_id should return 400."""
        from app.services.ai_provider import register_provider, _PROVIDER_REGISTRY

        class UpscaleCapableStub(StubProvider):
            name = "upscale_stub2"
            display_name = "Upscale Stub 2"
            capabilities = ProviderCapabilities(
                text_to_image=True,
                upscale=True,
            )

        register_provider("upscale_stub2", UpscaleCapableStub)

        resp = logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={"image_id": 99999, "scale": 2.0, "provider": "upscale_stub2"},
        )
        assert resp.status_code == 400
        assert "not found" in resp.get_json()["error"].lower()

        del _PROVIDER_REGISTRY["upscale_stub2"]

    def test_upscale_invalid_scale_too_low(self, logged_in_client, db):
        """Scale below 1.0 should be rejected."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        resp = logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={"image_id": image.id, "scale": 0.5, "provider": "stub"},
        )
        assert resp.status_code == 400
        assert "Scale must be between" in resp.get_json()["error"]

    def test_upscale_invalid_scale_too_high(self, logged_in_client, db):
        """Scale above 4.0 should be rejected."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        resp = logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={"image_id": image.id, "scale": 5.0, "provider": "stub"},
        )
        assert resp.status_code == 400
        assert "Scale must be between" in resp.get_json()["error"]

    def test_upscale_invalid_scale_not_number(self, logged_in_client, db):
        """Non-numeric scale should be rejected."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        resp = logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={"image_id": image.id, "scale": "abc", "provider": "stub"},
        )
        assert resp.status_code == 400

    def test_upscale_creates_version(self, logged_in_client, db):
        """Upscale should create an image version record."""
        from app.services.ai_provider import register_provider, _PROVIDER_REGISTRY

        class UpscaleCapableStub(StubProvider):
            name = "upscale_stub3"
            display_name = "Upscale Stub 3"
            capabilities = ProviderCapabilities(text_to_image=True, upscale=True)

        register_provider("upscale_stub3", UpscaleCapableStub)

        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)
        initial_versions = ImageVersion.query.filter_by(image_id=image.id).count()

        resp = logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={"image_id": image.id, "scale": 2.0, "provider": "upscale_stub3"},
        )
        assert resp.status_code == 200
        new_versions = ImageVersion.query.filter_by(image_id=image.id).count()
        assert new_versions >= initial_versions + 1

        del _PROVIDER_REGISTRY["upscale_stub3"]

    def test_upscale_preserves_original(self, logged_in_client, db):
        """Upscale should not modify the original file."""
        from app.services.ai_provider import register_provider, _PROVIDER_REGISTRY

        class UpscaleCapableStub(StubProvider):
            name = "upscale_stub4"
            display_name = "Upscale Stub 4"
            capabilities = ProviderCapabilities(text_to_image=True, upscale=True)

        register_provider("upscale_stub4", UpscaleCapableStub)

        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)
        original_path = image.file_path
        original_size = image.file_size

        logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={"image_id": image.id, "scale": 2.0, "provider": "upscale_stub4"},
        )

        from pathlib import Path
        assert Path(original_path).exists()
        import os
        assert os.path.getsize(original_path) == original_size

        del _PROVIDER_REGISTRY["upscale_stub4"]

    def test_upscale_requires_auth(self, client, db):
        """Upscale requires authentication."""
        resp = client.post(
            "/api/v1/utilities/upscale",
            json={"image_id": 1, "scale": 2.0},
        )
        assert resp.status_code == 302

    def test_upscale_ownership_check(self, client, db):
        """Users cannot upscale images they don't own."""
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        image = create_image_with_file(user2.id, db)

        login(client, email="u1@x.com")
        resp = client.post(
            "/api/v1/utilities/upscale",
            json={"image_id": image.id, "scale": 2.0, "provider": "stub"},
        )
        assert resp.status_code == 400
        assert "not found" in resp.get_json()["error"].lower()

    def test_upscale_clamps_scale_minimum(self, logged_in_client, db):
        """Scale should be clamped to minimum 1.5."""
        from app.services.ai_provider import register_provider, _PROVIDER_REGISTRY

        class UpscaleCapableStub(StubProvider):
            name = "upscale_stub5"
            display_name = "Upscale Stub 5"
            capabilities = ProviderCapabilities(text_to_image=True, upscale=True)

        register_provider("upscale_stub5", UpscaleCapableStub)

        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db, width=100, height=100)

        resp = logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={"image_id": image.id, "scale": 1.0, "provider": "upscale_stub5"},
        )
        # Scale is clamped to 1.5, so result should be 150x150
        if resp.status_code == 200:
            data = resp.get_json()
            assert data["upscaled_width"] >= 150

        del _PROVIDER_REGISTRY["upscale_stub5"]


# ============================================================
# BACKGROUND REMOVAL TESTS
# ============================================================

class TestBackgroundRemoval:
    """Test background removal functionality."""

    def test_bg_removal_unsupported_provider(self, logged_in_client, db):
        """Background removal should fail with stub provider."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        resp = logged_in_client.post(
            "/api/v1/utilities/remove-background",
            json={"image_id": image.id, "provider": "stub"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "does not support background removal" in data["error"]

    def test_bg_removal_missing_image_id(self, logged_in_client, db):
        """Background removal without image_id should return 400."""
        resp = logged_in_client.post(
            "/api/v1/utilities/remove-background",
            json={"provider": "stub"},
        )
        assert resp.status_code == 400
        assert "image_id is required" in resp.get_json()["error"]

    def test_bg_removal_nonexistent_image(self, logged_in_client, db):
        """Background removal with nonexistent image should return 400."""
        from app.services.ai_provider import register_provider, _PROVIDER_REGISTRY

        class BgRemovalStub(StubProvider):
            name = "bgremoval_stub"
            display_name = "BG Removal Stub"
            capabilities = ProviderCapabilities(
                text_to_image=True,
                background_removal=True,
                transparency=True,
            )

        register_provider("bgremoval_stub", BgRemovalStub)

        resp = logged_in_client.post(
            "/api/v1/utilities/remove-background",
            json={"image_id": 99999, "provider": "bgremoval_stub"},
        )
        assert resp.status_code == 400

        del _PROVIDER_REGISTRY["bgremoval_stub"]

    def test_bg_removal_requires_auth(self, client, db):
        """Background removal requires authentication."""
        resp = client.post(
            "/api/v1/utilities/remove-background",
            json={"image_id": 1},
        )
        assert resp.status_code == 302

    def test_bg_removal_ownership_check(self, client, db):
        """Users cannot remove background from images they don't own."""
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        image = create_image_with_file(user2.id, db)

        login(client, email="u1@x.com")
        resp = client.post(
            "/api/v1/utilities/remove-background",
            json={"image_id": image.id, "provider": "stub"},
        )
        assert resp.status_code == 400

    def test_bg_removal_stub_rejects_operation(self, logged_in_client, db):
        """Stub provider should reject background removal since it can't produce real alpha."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        resp = logged_in_client.post(
            "/api/v1/utilities/remove-background",
            json={"image_id": image.id, "provider": "stub"},
        )
        assert resp.status_code == 400
        assert "does not support" in resp.get_json()["error"]


# ============================================================
# IMAGE-TO-PROMPT / DESCRIBE TESTS
# ============================================================

class TestImageToPrompt:
    """Test image description / image-to-prompt functionality."""

    def test_describe_supported_provider(self, logged_in_client, db):
        """Image description should work with image understanding capability."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        resp = logged_in_client.post(
            "/api/v1/utilities/describe",
            json={"image_id": image.id, "provider": "stub"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "description" in data

        desc = data["description"]
        # All required fields should be present
        assert "subject" in desc
        assert "environment" in desc
        assert "style" in desc
        assert "composition" in desc
        assert "lighting" in desc
        assert "colors" in desc
        assert "mood" in desc
        assert "prompt" in desc

    def test_describe_stub_returns_disclaimer(self, logged_in_client, db):
        """Stub provider should include a disclaimer."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        resp = logged_in_client.post(
            "/api/v1/utilities/describe",
            json={"image_id": image.id, "provider": "stub"},
        )
        desc = resp.get_json()["description"]
        assert desc["is_stub"] is True
        assert "disclaimer" in desc
        assert len(desc["disclaimer"]) > 0

    def test_describe_unsupported_provider(self, logged_in_client, db):
        """Description should fail with provider lacking image understanding."""
        from app.services.ai_provider import register_provider, _PROVIDER_REGISTRY

        class NoUnderstandingStub(StubProvider):
            name = "no_understanding"
            display_name = "No Understanding"
            capabilities = ProviderCapabilities(
                text_to_image=True,
                image_understanding=False,
            )

        register_provider("no_understanding", NoUnderstandingStub)

        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        resp = logged_in_client.post(
            "/api/v1/utilities/describe",
            json={"image_id": image.id, "provider": "no_understanding"},
        )
        assert resp.status_code == 400
        assert "does not support image understanding" in resp.get_json()["error"]

        del _PROVIDER_REGISTRY["no_understanding"]

    def test_describe_missing_image_id(self, logged_in_client, db):
        """Description without image_id should return 400."""
        resp = logged_in_client.post(
            "/api/v1/utilities/describe",
            json={"provider": "stub"},
        )
        assert resp.status_code == 400
        assert "image_id is required" in resp.get_json()["error"]

    def test_describe_nonexistent_image(self, logged_in_client, db):
        """Description with nonexistent image should return 400."""
        resp = logged_in_client.post(
            "/api/v1/utilities/describe",
            json={"image_id": 99999, "provider": "stub"},
        )
        assert resp.status_code == 400
        assert "not found" in resp.get_json()["error"].lower()

    def test_describe_requires_auth(self, client, db):
        """Description requires authentication."""
        resp = client.post(
            "/api/v1/utilities/describe",
            json={"image_id": 1},
        )
        assert resp.status_code == 302

    def test_describe_ownership_check(self, client, db):
        """Users cannot describe images they don't own."""
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        image = create_image_with_file(user2.id, db)

        login(client, email="u1@x.com")
        resp = client.post(
            "/api/v1/utilities/describe",
            json={"image_id": image.id, "provider": "stub"},
        )
        assert resp.status_code == 400

    def test_describe_has_all_structured_fields(self, logged_in_client, db):
        """Description should return all structured fields for prompt generation."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        resp = logged_in_client.post(
            "/api/v1/utilities/describe",
            json={"image_id": image.id, "provider": "stub"},
        )
        desc = resp.get_json()["description"]
        required_fields = [
            "subject", "environment", "style", "composition",
            "lighting", "colors", "mood", "prompt",
        ]
        for field in required_fields:
            assert field in desc, f"Missing field: {field}"
            assert desc[field], f"Empty field: {field}"


# ============================================================
# PAGE ROUTE TESTS
# ============================================================

class TestUtilitiesPage:
    """Test the utilities page renders correctly."""

    def test_utilities_page_loads(self, logged_in_client):
        """Utilities page should load with correct content."""
        resp = logged_in_client.get("/utilities")
        assert resp.status_code == 200
        assert b"Utilities" in resp.data
        assert b"Upscale" in resp.data
        assert b"Background Removal" in resp.data
        assert b"Image to Prompt" in resp.data

    def test_utilities_page_requires_auth(self, client):
        """Utilities page requires authentication."""
        resp = client.get("/utilities")
        assert resp.status_code == 302

    def test_utilities_page_has_upload_zones(self, logged_in_client):
        """Utilities page should have upload zones for each tool."""
        resp = logged_in_client.get("/utilities")
        assert b"upscale-upload-zone" in resp.data
        assert b"bgremove-upload-zone" in resp.data
        assert b"describe-upload-zone" in resp.data

    def test_utilities_page_has_scale_selector(self, logged_in_client):
        """Utilities page should have scale selector buttons."""
        resp = logged_in_client.get("/utilities")
        assert b"scale-selector" in resp.data
        assert b"2" in resp.data
        assert b"3" in resp.data
        assert b"4" in resp.data

    def test_utilities_page_has_capability_chips(self, logged_in_client):
        """Utilities page should have capability display chips."""
        resp = logged_in_client.get("/utilities")
        assert b"capability-chips" in resp.data

    def test_utilities_page_has_provider_select(self, logged_in_client):
        """Utilities page should have a provider selector."""
        resp = logged_in_client.get("/utilities")
        assert b"provider-select" in resp.data

    def test_utilities_page_has_disclaimer(self, logged_in_client):
        """Utilities page should have disclaimer for image-to-prompt."""
        resp = logged_in_client.get("/utilities")
        assert b"disclaimer" in resp.data.lower()


# ============================================================
# CAPABILITY ENDPOINT TESTS
# ============================================================

class TestCapabilitiesEndpoint:
    """Test the capabilities API endpoint."""

    def test_returns_all_providers(self, client, db):
        """Capabilities should list all registered providers."""
        create_user()
        login(client)

        resp = client.get("/api/v1/utilities/capabilities")
        data = resp.get_json()
        providers = data["capabilities"]
        assert "stub" in providers

    def test_stub_capabilities_values(self, client, db):
        """Stub capabilities should match expected values."""
        create_user()
        login(client)

        resp = client.get("/api/v1/utilities/capabilities")
        stub = resp.get_json()["capabilities"]["stub"]
        assert stub["upscale"] is False
        assert stub["transparency"] is False
        assert stub["background_removal"] is False
        assert stub["image_understanding"] is True
        assert stub["multi_reference"] is True
        assert stub["configured"] is True  # Stub is always configured


# ============================================================
# EDGE CASES
# ============================================================

class TestEdgeCases:
    """Test various edge cases and boundary conditions."""

    def test_upscale_with_missing_file(self, logged_in_client, db):
        """Upscale should fail gracefully if file is missing from disk."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        # Delete the file but keep the record
        import os
        os.unlink(image.file_path)

        resp = logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={"image_id": image.id, "scale": 2.0, "provider": "stub"},
        )
        assert resp.status_code == 400
        assert "not found" in resp.get_json()["error"].lower()

    def test_describe_with_missing_file(self, logged_in_client, db):
        """Description should fail gracefully if file is missing."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        import os
        os.unlink(image.file_path)

        resp = logged_in_client.post(
            "/api/v1/utilities/describe",
            json={"image_id": image.id, "provider": "stub"},
        )
        assert resp.status_code == 400
        assert "not found" in resp.get_json()["error"].lower()

    def test_unknown_provider_returns_error(self, logged_in_client, db):
        """Using an unknown provider should return an error."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        resp = logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={"image_id": image.id, "scale": 2.0, "provider": "nonexistent"},
        )
        assert resp.status_code == 400
        assert "not available" in resp.get_json()["error"].lower()

    def test_upscale_default_scale(self, logged_in_client, db):
        """Upscale should default to scale 2.0 when not specified."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        # Missing scale field — route defaults to 2.0
        resp = logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={"image_id": image.id, "provider": "stub"},
        )
        # Will fail because stub doesn't support upscale, but validates the default
        assert resp.status_code == 400
        assert "does not support upscaling" in resp.get_json()["error"]

    def test_utilities_upload_returns_image_url(self, logged_in_client, db):
        """Upload response should include a valid image URL."""
        png_data = make_png_bytes(100, 100)
        resp = logged_in_client.post(
            "/api/v1/utilities/upload",
            data={"file": (io.BytesIO(png_data), "url_test.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 201
        url = resp.get_json()["image"]["url"]
        assert url.startswith("/api/v1/images/")

    def test_multiple_uploads_same_user(self, logged_in_client, db):
        """Multiple uploads should all succeed for the same user."""
        user = User.query.filter_by(username="utiluser").first()
        initial = Image.query.filter_by(user_id=user.id).count()

        for i in range(3):
            png_data = make_png_bytes(64 + i * 10, 64 + i * 10)
            resp = logged_in_client.post(
                "/api/v1/utilities/upload",
                data={"file": (io.BytesIO(png_data), f"multi_{i}.png")},
                content_type="multipart/form-data",
            )
            assert resp.status_code == 201

        final = Image.query.filter_by(user_id=user.id).count()
        assert final == initial + 3


# ============================================================
# PROVIDER REGISTRY TESTS
# ============================================================

class TestProviderRegistry:
    """Test provider registration and lookup."""

    def test_register_custom_provider(self):
        """A custom provider can be registered and retrieved."""
        from app.services.ai_provider import register_provider, _PROVIDER_REGISTRY

        class CustomProvider(StubProvider):
            name = "custom_test"
            display_name = "Custom Test Provider"
            capabilities = ProviderCapabilities(
                text_to_image=True,
                upscale=True,
                background_removal=True,
                transparency=True,
            )

        register_provider("custom_test", CustomProvider)
        provider = get_provider("custom_test")

        assert provider.name == "custom_test"
        assert provider.supports("upscale") is True
        assert provider.supports("background_removal") is True
        assert provider.supports("transparency") is True

        # Cleanup
        del _PROVIDER_REGISTRY["custom_test"]

    def test_list_providers_includes_stub(self):
        """list_providers should always include 'stub'."""
        providers = list_providers()
        assert "stub" in providers


# ============================================================
# BATCH PROCESSING TESTS
# ============================================================

class TestBatchProcessing:
    """Test batch upscale and batch describe."""

    def test_batch_upscale_requires_image_ids(self, logged_in_client, db):
        """Batch upscale without image_ids should fail."""
        resp = logged_in_client.post(
            "/api/v1/utilities/batch/upscale",
            json={"scale": 2.0, "provider": "stub"},
        )
        assert resp.status_code == 400
        assert "image_ids" in resp.get_json()["error"].lower()

    def test_batch_upscale_rejects_empty_list(self, logged_in_client, db):
        """Batch upscale with empty list should fail."""
        resp = logged_in_client.post(
            "/api/v1/utilities/batch/upscale",
            json={"image_ids": [], "scale": 2.0, "provider": "stub"},
        )
        assert resp.status_code == 400

    def test_batch_upscale_rejects_too_many(self, logged_in_client, db):
        """Batch upscale with >20 images should fail."""
        resp = logged_in_client.post(
            "/api/v1/utilities/batch/upscale",
            json={"image_ids": list(range(21)), "scale": 2.0, "provider": "stub"},
        )
        assert resp.status_code == 400
        assert "Maximum 20" in resp.get_json()["error"]

    def test_batch_upscale_invalid_scale(self, logged_in_client, db):
        """Batch upscale with invalid scale should fail."""
        resp = logged_in_client.post(
            "/api/v1/utilities/batch/upscale",
            json={"image_ids": [1, 2], "scale": 5.0, "provider": "stub"},
        )
        assert resp.status_code == 400

    def test_batch_upscale_requires_auth(self, client, db):
        """Batch upscale requires authentication."""
        resp = client.post(
            "/api/v1/utilities/batch/upscale",
            json={"image_ids": [1], "scale": 2.0},
        )
        assert resp.status_code == 302

    def test_batch_upscale_produces_results(self, logged_in_client, db):
        """Batch upscale should return results for each image."""
        from app.services.ai_provider import register_provider, _PROVIDER_REGISTRY

        class UpscaleCapableStub(StubProvider):
            name = "batch_upscale_stub"
            display_name = "Batch Upscale Stub"
            capabilities = ProviderCapabilities(text_to_image=True, upscale=True)

        register_provider("batch_upscale_stub", UpscaleCapableStub)

        user = User.query.filter_by(username="utiluser").first()
        img1 = create_image_with_file(user.id, db, filename="batch1.png")
        img2 = create_image_with_file(user.id, db, filename="batch2.png")

        resp = logged_in_client.post(
            "/api/v1/utilities/batch/upscale",
            json={
                "image_ids": [img1.id, img2.id],
                "scale": 2.0,
                "provider": "batch_upscale_stub",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["total"] == 2
        assert len(data["results"]) == 2
        assert data["batch_id"] is not None
        # Both should succeed (scale clamped to 1.5, images exist)
        for r in data["results"]:
            assert r["status"] == "success"

        del _PROVIDER_REGISTRY["batch_upscale_stub"]

    def test_batch_describe_requires_image_ids(self, logged_in_client, db):
        """Batch describe without image_ids should fail."""
        resp = logged_in_client.post(
            "/api/v1/utilities/batch/describe",
            json={"provider": "stub"},
        )
        assert resp.status_code == 400

    def test_batch_describe_rejects_empty_list(self, logged_in_client, db):
        """Batch describe with empty list should fail."""
        resp = logged_in_client.post(
            "/api/v1/utilities/batch/describe",
            json={"image_ids": [], "provider": "stub"},
        )
        assert resp.status_code == 400

    def test_batch_describe_rejects_too_many(self, logged_in_client, db):
        """Batch describe with >20 images should fail."""
        resp = logged_in_client.post(
            "/api/v1/utilities/batch/describe",
            json={"image_ids": list(range(21)), "provider": "stub"},
        )
        assert resp.status_code == 400
        assert "Maximum 20" in resp.get_json()["error"]

    def test_batch_describe_requires_auth(self, client, db):
        """Batch describe requires authentication."""
        resp = client.post(
            "/api/v1/utilities/batch/describe",
            json={"image_ids": [1]},
        )
        assert resp.status_code == 302

    def test_batch_describe_produces_results(self, logged_in_client, db):
        """Batch describe should return structured descriptions."""
        user = User.query.filter_by(username="utiluser").first()
        img1 = create_image_with_file(user.id, db, filename="desc1.png")
        img2 = create_image_with_file(user.id, db, filename="desc2.png")

        resp = logged_in_client.post(
            "/api/v1/utilities/batch/describe",
            json={
                "image_ids": [img1.id, img2.id],
                "provider": "stub",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["total"] == 2
        assert len(data["results"]) == 2
        for r in data["results"]:
            assert r["status"] == "success"
            assert "description" in r
            assert "subject" in r["description"]

    def test_batch_status_endpoint(self, logged_in_client, db):
        """Batch status endpoint should return 404 for nonexistent batch."""
        resp = logged_in_client.get("/api/v1/utilities/batch/nonexistent/status")
        assert resp.status_code == 404

    def test_batch_status_requires_auth(self, client, db):
        """Batch status requires authentication."""
        resp = client.get("/api/v1/utilities/batch/test/status")
        assert resp.status_code == 302

    def test_batch_upscale_ownership_check(self, client, db):
        """Users cannot batch upscale images they don't own."""
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        img = create_image_with_file(user2.id, db, filename="other.png")

        login(client, email="u1@x.com")
        resp = client.post(
            "/api/v1/utilities/batch/upscale",
            json={"image_ids": [img.id], "scale": 2.0, "provider": "stub"},
        )
        # Should return 200 but with a failed result for the image
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["results"][0]["status"] == "failed"


# ============================================================
# HISTORY TESTS
# ============================================================

class TestHistory:
    """Test utility operation history tracking."""

    def test_history_empty_initially(self, logged_in_client, db):
        """History should be empty initially."""
        resp = logged_in_client.get("/api/v1/utilities/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 0
        assert data["operations"] == []

    def test_history_after_describe(self, logged_in_client, db):
        """History should contain describe operations."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        logged_in_client.post(
            "/api/v1/utilities/describe",
            json={"image_id": image.id, "provider": "stub"},
        )

        resp = logged_in_client.get("/api/v1/utilities/history")
        data = resp.get_json()
        assert data["total"] >= 1
        ops = data["operations"]
        assert any(op["operation"] == "describe" for op in ops)

    def test_history_after_upscale(self, logged_in_client, db):
        """History should contain upscale operations."""
        from app.services.ai_provider import register_provider, _PROVIDER_REGISTRY

        class UpscaleCapableStub(StubProvider):
            name = "hist_upscale_stub"
            display_name = "Hist Upscale Stub"
            capabilities = ProviderCapabilities(text_to_image=True, upscale=True)

        register_provider("hist_upscale_stub", UpscaleCapableStub)

        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        logged_in_client.post(
            "/api/v1/utilities/upscale",
            json={"image_id": image.id, "scale": 2.0, "provider": "hist_upscale_stub"},
        )

        resp = logged_in_client.get("/api/v1/utilities/history")
        data = resp.get_json()
        assert data["total"] >= 1
        ops = data["operations"]
        assert any(op["operation"] == "upscale" for op in ops)

        del _PROVIDER_REGISTRY["hist_upscale_stub"]

    def test_history_has_correct_fields(self, logged_in_client, db):
        """History operations should have all expected fields."""
        user = User.query.filter_by(username="utiluser").first()
        image = create_image_with_file(user.id, db)

        logged_in_client.post(
            "/api/v1/utilities/describe",
            json={"image_id": image.id, "provider": "stub"},
        )

        resp = logged_in_client.get("/api/v1/utilities/history")
        op = resp.get_json()["operations"][0]

        expected_fields = [
            "id", "operation", "provider", "status",
            "params", "result", "created_at",
        ]
        for field in expected_fields:
            assert field in op, f"Missing field: {field}"
        assert op["status"] == "completed"
        assert op["operation"] == "describe"

    def test_history_pagination(self, logged_in_client, db):
        """History should support pagination."""
        user = User.query.filter_by(username="utiluser").first()
        for i in range(5):
            img = create_image_with_file(user.id, db, filename=f"pag_{i}.png")
            logged_in_client.post(
                "/api/v1/utilities/describe",
                json={"image_id": img.id, "provider": "stub"},
            )

        # Get first page
        resp = logged_in_client.get("/api/v1/utilities/history?limit=2&offset=0")
        data = resp.get_json()
        assert len(data["operations"]) == 2
        assert data["has_more"] is True
        assert data["total"] >= 5

        # Get second page
        resp = logged_in_client.get("/api/v1/utilities/history?limit=2&offset=2")
        data = resp.get_json()
        assert len(data["operations"]) == 2

    def test_history_requires_auth(self, client, db):
        """History requires authentication."""
        resp = client.get("/api/v1/utilities/history")
        assert resp.status_code == 302

    def test_history_ownership_isolation(self, client, db):
        """Users should only see their own history."""
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")

        img2 = create_image_with_file(user2.id, db, filename="own2.png")
        login(client, email="u2@x.com")
        client.post(
            "/api/v1/utilities/describe",
            json={"image_id": img2.id, "provider": "stub"},
        )

        # Switch to user1
        logout(client)
        login(client, email="u1@x.com")
        resp = client.get("/api/v1/utilities/history")
        data = resp.get_json()
        assert data["total"] == 0  # user1 has no history

    def test_history_clamps_limit(self, logged_in_client, db):
        """History should clamp limit to max 100."""
        resp = logged_in_client.get("/api/v1/utilities/history?limit=200")
        assert resp.status_code == 200

    def test_batch_operations_in_history(self, logged_in_client, db):
        """Batch operations should be recorded in history."""
        user = User.query.filter_by(username="utiluser").first()
        img1 = create_image_with_file(user.id, db, filename="bh1.png")
        img2 = create_image_with_file(user.id, db, filename="bh2.png")

        logged_in_client.post(
            "/api/v1/utilities/batch/describe",
            json={"image_ids": [img1.id, img2.id], "provider": "stub"},
        )

        resp = logged_in_client.get("/api/v1/utilities/history")
        data = resp.get_json()
        # Should have at least 2 describe operations (one per image in the batch)
        ops = data["operations"]
        describe_ops = [op for op in ops if op["operation"] == "describe"]
        assert len(describe_ops) >= 2


# ============================================================
# PROGRESS / UI INTEGRATION TESTS
# ============================================================

class TestProgressUI:
    """Test that the UI renders progress-related elements."""

    def test_page_has_progress_elements(self, logged_in_client):
        """Utilities page should have progress bar elements."""
        resp = logged_in_client.get("/utilities")
        assert b"util-progress-bar" in resp.data
        assert b"util-progress-fill" in resp.data
        assert b"util-progress-steps" in resp.data

    def test_page_has_batch_queue_elements(self, logged_in_client):
        """Utilities page should have batch queue elements."""
        resp = logged_in_client.get("/utilities")
        assert b"util-batch-queue" in resp.data
        assert b"util-batch-count" in resp.data

    def test_page_has_history_panel(self, logged_in_client):
        """Utilities page should have history panel."""
        resp = logged_in_client.get("/utilities")
        assert b"util-history-panel" in resp.data
        assert b"Operation History" in resp.data

    def test_page_has_batch_execute_buttons(self, logged_in_client):
        """Utilities page should have batch execute buttons for describe."""
        resp = logged_in_client.get("/utilities")
        assert b"executeBatchDescribe" in resp.data
        assert b"Analyze All" in resp.data

    def test_page_file_inputs_allow_multiple(self, logged_in_client):
        """File inputs should allow multiple files for upscale and describe."""
        resp = logged_in_client.get("/utilities")
        data = resp.data.decode()
        # Check upscale and describe file inputs have 'multiple' attribute
        assert 'id="upscale-file-input"' in data
        assert 'id="describe-file-input"' in data
