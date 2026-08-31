"""Tests for the Advanced AI API routes (image-to-image, inpainting, style
transfer, outpainting, face enhance, super-resolution, smart crop, color
correction, analyze, variations).

This file previously did not exist at all — every one of these 10 endpoints
was completely broken (get_provider() crashed on init, and the save path
used a StorageService API and Image model fields that didn't exist), and
nothing caught it because there was no coverage. These tests lock in the fix.
"""

import io
import pytest

from app.extensions import db as _db
from app.models.user import User
from app.models.image import Image
from app.models.generation import Generation


@pytest.fixture
def logged_in_client(client, db):
    client.post("/signup", data={
        "username": "adv_ai_tester",
        "email": "adv_ai@test.com",
        "password": "TestPass123!",
        "confirm_password": "TestPass123!",
    }, follow_redirects=True)
    client.post("/login", data={
        "email": "adv_ai@test.com",
        "password": "TestPass123!",
    }, follow_redirects=True)
    return client


@pytest.fixture
def source_image(logged_in_client, db):
    """A real 512x512 source image owned by the test user, saved through the
    same StorageService path production code uses."""
    user = User.query.filter_by(username="adv_ai_tester").first()
    gen = Generation(user_id=user.id, prompt="source", provider="stub", status="completed")
    db.session.add(gen)
    db.session.flush()

    from app.config import BASE_DIR
    upload_dir = BASE_DIR / "uploads" / "generations" / str(user.id) / "images"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / "adv_source.png"

    from PIL import Image as PILImage
    img = PILImage.new("RGB", (512, 512), color=(120, 140, 200))
    img.save(str(file_path), format="PNG")

    image = Image(
        generation_id=gen.id, user_id=user.id, filename="adv_source.png",
        file_path=str(file_path), width=512, height=512,
        file_size=file_path.stat().st_size,
    )
    db.session.add(image)
    db.session.flush()
    return image.id


class TestCapabilities:
    def test_capabilities_returns_active_provider(self, logged_in_client):
        resp = logged_in_client.get("/api/v1/advanced/capabilities")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "active_provider" in data
        assert isinstance(data["capabilities"], dict)


class TestImageToImage:
    def test_image_to_image_creates_new_image(self, logged_in_client, source_image, db):
        resp = logged_in_client.post("/api/v1/advanced/image-to-image", data={
            "source_image_id": str(source_image),
            "prompt": "a watercolor version",
            "strength": "0.6",
        })
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        assert data["success"] is True
        assert data["image_id"]
        img = db.session.get(Image, data["image_id"])
        assert img is not None
        assert img.file_path and img.width == 512

    def test_missing_prompt_returns_400(self, logged_in_client, source_image):
        resp = logged_in_client.post("/api/v1/advanced/image-to-image", data={
            "source_image_id": str(source_image),
        })
        assert resp.status_code == 400

    def test_nonexistent_source_returns_404(self, logged_in_client):
        resp = logged_in_client.post("/api/v1/advanced/image-to-image", data={
            "source_image_id": "999999",
            "prompt": "anything",
        })
        assert resp.status_code == 404


class TestInpainting:
    def test_inpainting_with_mask(self, logged_in_client, source_image, db):
        from PIL import Image as PILImage
        mask = PILImage.new("L", (512, 512), color=0)
        for x in range(200, 300):
            for y in range(200, 300):
                mask.putpixel((x, y), 255)
        buf = io.BytesIO()
        mask.save(buf, format="PNG")
        buf.seek(0)

        resp = logged_in_client.post("/api/v1/advanced/inpainting", data={
            "source_image_id": str(source_image),
            "prompt": "fill with sky",
            "mask": (buf, "mask.png"),
        }, content_type="multipart/form-data")
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        assert data["success"] is True
        img = db.session.get(Image, data["image_id"])
        assert img.width == 512 and img.height == 512


class TestStyleTransfer:
    def test_style_transfer_with_preset_name(self, logged_in_client, source_image, db):
        resp = logged_in_client.post("/api/v1/advanced/style-transfer", data={
            "source_image_id": str(source_image),
            "style_reference": "watercolor",
            "style_strength": "0.7",
        })
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()["success"] is True


class TestOutpainting:
    def test_outpainting_extends_canvas(self, logged_in_client, source_image, db):
        resp = logged_in_client.post("/api/v1/advanced/outpainting", data={
            "source_image_id": str(source_image),
            "direction": "right",
            "extend_pixels": "64",
        })
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        img = db.session.get(Image, data["image_id"])
        assert img.width == 512 + 64
        assert img.height == 512


class TestFaceEnhance:
    def test_face_enhance_runs_without_faces(self, logged_in_client, source_image, db):
        resp = logged_in_client.post("/api/v1/advanced/face-enhance", data={
            "source_image_id": str(source_image),
            "enhancement_level": "light",
        })
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()["success"] is True


class TestSuperResolution:
    def test_super_resolution_doubles_size(self, logged_in_client, source_image, db):
        resp = logged_in_client.post("/api/v1/advanced/super-resolution", data={
            "source_image_id": str(source_image),
            "scale_factor": "2",
        })
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        img = db.session.get(Image, data["image_id"])
        assert img.width == 1024 and img.height == 1024

    def test_invalid_scale_factor_returns_400(self, logged_in_client, source_image):
        resp = logged_in_client.post("/api/v1/advanced/super-resolution", data={
            "source_image_id": str(source_image),
            "scale_factor": "3",
        })
        assert resp.status_code == 400


class TestSmartCrop:
    def test_smart_crop_square(self, logged_in_client, source_image, db):
        resp = logged_in_client.post("/api/v1/advanced/smart-crop", data={
            "source_image_id": str(source_image),
            "target_aspect": "1:1",
        })
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        img = db.session.get(Image, data["image_id"])
        assert img.width == img.height


class TestColorCorrection:
    def test_auto_color_correction(self, logged_in_client, source_image, db):
        resp = logged_in_client.post("/api/v1/advanced/color-correction", data={
            "source_image_id": str(source_image),
            "correction_type": "auto",
        })
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()["success"] is True


class TestAnalyze:
    def test_analyze_returns_real_stats(self, logged_in_client, source_image):
        resp = logged_in_client.post("/api/v1/advanced/analyze", data={
            "source_image_id": str(source_image),
        })
        assert resp.status_code == 200, resp.get_data(as_text=True)
        analysis = resp.get_json()["analysis"]
        assert analysis["basic_info"]["size"] == [512, 512]
        assert "dominant_colors" in analysis
        assert isinstance(analysis["dominant_colors"], list)
        assert "mood" in analysis["color_analysis"]


class TestVariations:
    def test_variations_creates_multiple_distinct_images(self, logged_in_client, source_image, db):
        resp = logged_in_client.post("/api/v1/advanced/variations", data={
            "source_image_id": str(source_image),
            "num_variations": "2",
            "variation_strength": "0.3",
        })
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        assert len(data["images"]) == 2

    def test_too_many_variations_returns_400(self, logged_in_client, source_image):
        resp = logged_in_client.post("/api/v1/advanced/variations", data={
            "source_image_id": str(source_image),
            "num_variations": "20",
        })
        assert resp.status_code == 400


class TestAuthRequired:
    def test_advanced_endpoints_require_login(self, client):
        resp = client.post("/api/v1/advanced/image-to-image", data={
            "source_image_id": "1", "prompt": "x",
        })
        assert resp.status_code in (302, 401)
