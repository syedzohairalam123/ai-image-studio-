"""Tests for the image editor functionality.

Covers: crop, rotate, local adjustments, mask, AI edit,
version creation, before/after, original preservation, mobile.
"""

import json
import pytest
from pathlib import Path

from app.config import TestingConfig
from app.extensions import db as _db
from app.models.user import User
from app.models.image import Image
from app.models.generation import Generation
from app.models.image_version import ImageVersion


@pytest.fixture
def logged_in_client(client, db):
    """Register and login a test user, return authenticated client."""
    # Register via form
    client.post("/signup", data={
        "username": "editor_tester",
        "email": "editor@test.com",
        "password": "TestPass123!",
        "confirm_password": "TestPass123!",
    }, follow_redirects=True)

    # Login via form
    client.post("/login", data={
        "email": "editor@test.com",
        "password": "TestPass123!",
    }, follow_redirects=True)

    return client


@pytest.fixture
def test_image(logged_in_client, db):
    """Create a test image in the database."""
    user = User.query.filter_by(username="editor_tester").first()
    gen = Generation(
        user_id=user.id,
        prompt="test image",
        provider="stub",
        status="completed",
    )
    db.session.add(gen)
    db.session.flush()

    # Create a placeholder image file (use absolute path like StorageService)
    from app.config import BASE_DIR
    upload_dir = BASE_DIR / "uploads" / "generations" / str(user.id) / "images"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / "test_original.png"

    # Create a simple test image
    from PIL import Image as PILImage
    img = PILImage.new("RGB", (512, 512), color=(100, 150, 200))
    img.save(str(file_path), format="PNG")

    image = Image(
        generation_id=gen.id,
        user_id=user.id,
        filename="test_original.png",
        file_path=str(file_path),
        width=512,
        height=512,
        file_size=file_path.stat().st_size,
    )
    db.session.add(image)
    db.session.flush()

    return image.id


class TestEditorRoutes:
    """Test editor API routes."""

    def test_editor_page_loads(self, logged_in_client):
        """Test that the editor page loads."""
        resp = logged_in_client.get("/editor")
        assert resp.status_code == 200
        assert b"Image Editor" in resp.data

    def test_get_image_info(self, logged_in_client, test_image):
        """Test getting image info for editor."""
        resp = logged_in_client.get(f"/api/v1/editor/images/{test_image}/info")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "image" in data
        assert "versions" in data
        assert data["image"]["width"] == 512

    def test_get_capabilities(self, logged_in_client):
        """Test getting AI editing capabilities."""
        resp = logged_in_client.get("/api/v1/editor/capabilities")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "capabilities" in data


class TestLocalEditing:
    """Test local image editing operations."""

    def test_brightness_adjustment(self, logged_in_client, test_image):
        """Test brightness adjustment."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "brightness",
                "params": {"factor": 1.5},
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "version" in data
        assert data["version"]["edit_type"] == "local_brightness"

    def test_contrast_adjustment(self, logged_in_client, test_image):
        """Test contrast adjustment."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "contrast",
                "params": {"factor": 1.3},
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"]["edit_type"] == "local_contrast"

    def test_saturation_adjustment(self, logged_in_client, test_image):
        """Test saturation adjustment."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "saturation",
                "params": {"factor": 0.5},
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"]["edit_type"] == "local_saturation"

    def test_rotate_operation(self, logged_in_client, test_image):
        """Test rotation."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "rotate",
                "params": {"angle": 90, "expand": True},
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"]["edit_type"] == "local_rotate"

    def test_flip_operation(self, logged_in_client, test_image):
        """Test flip horizontal."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "flip",
                "params": {"direction": "horizontal"},
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"]["edit_type"] == "local_flip"

    def test_resize_operation(self, logged_in_client, test_image):
        """Test resize."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "resize",
                "params": {"width": 256, "height": 256, "maintain_ratio": True},
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"]["edit_type"] == "local_resize"

    def test_crop_operation(self, logged_in_client, test_image):
        """Test crop."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "crop",
                "params": {"x": 50, "y": 50, "width": 200, "height": 200},
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"]["edit_type"] == "local_crop"

    def test_invalid_operation(self, logged_in_client, test_image):
        """Test invalid operation returns error."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "invalid_op",
                "params": {},
            },
        )
        assert resp.status_code == 400

    def test_missing_image_id(self, logged_in_client):
        """Test missing image_id returns error."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "operation": "brightness",
                "params": {"factor": 1.0},
            },
        )
        assert resp.status_code == 400

    def test_nonexistent_image(self, logged_in_client):
        """Test editing nonexistent image returns error."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": 99999,
                "operation": "brightness",
                "params": {"factor": 1.0},
            },
        )
        assert resp.status_code == 400


class TestAIEditing:
    """Test AI image editing operations."""

    def test_ai_edit_requires_prompt(self, logged_in_client, test_image):
        """Test AI edit requires a prompt."""
        resp = logged_in_client.post(
            "/api/v1/editor/ai",
            json={
                "image_id": test_image,
                "operation": "inpaint",
                "prompt": "",
                "params": {},
            },
        )
        assert resp.status_code == 400

    def test_ai_edit_invalid_operation(self, logged_in_client, test_image):
        """Test AI edit with invalid operation."""
        resp = logged_in_client.post(
            "/api/v1/editor/ai",
            json={
                "image_id": test_image,
                "operation": "invalid_ai_op",
                "prompt": "test prompt",
                "params": {},
            },
        )
        assert resp.status_code == 400

    def test_retexture_operation(self, logged_in_client, test_image):
        """Test retexture AI operation."""
        resp = logged_in_client.post(
            "/api/v1/editor/ai",
            json={
                "image_id": test_image,
                "operation": "retexture",
                "prompt": "oil painting style",
                "params": {"strength": 0.7, "provider": "stub"},
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"]["edit_type"] == "ai_retexture"

    def test_inpaint_operation(self, logged_in_client, test_image):
        """Test inpaint AI operation."""
        resp = logged_in_client.post(
            "/api/v1/editor/ai",
            json={
                "image_id": test_image,
                "operation": "inpaint",
                "prompt": "beautiful sunset sky",
                "params": {"provider": "stub"},
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"]["edit_type"] == "ai_inpaint"

    def test_outpaint_operation(self, logged_in_client, test_image):
        """Test outpaint AI operation."""
        resp = logged_in_client.post(
            "/api/v1/editor/ai",
            json={
                "image_id": test_image,
                "operation": "outpaint",
                "prompt": "extend the landscape",
                "params": {"direction": "right", "extend_percent": 25, "provider": "stub"},
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"]["edit_type"] == "ai_outpaint"

    def test_background_replace_operation(self, logged_in_client, test_image):
        """Test background replacement."""
        resp = logged_in_client.post(
            "/api/v1/editor/ai",
            json={
                "image_id": test_image,
                "operation": "background_replace",
                "prompt": "tropical beach at sunset",
                "params": {"strength": 0.5, "provider": "stub"},
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"]["edit_type"] == "ai_background_replace"


class TestVersioning:
    """Test version management system."""

    def test_version_created_on_edit(self, logged_in_client, test_image):
        """Test that a new version is created on each edit."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "brightness",
                "params": {"factor": 1.2},
            },
        )
        data = resp.get_json()

        resp = logged_in_client.get(f"/api/v1/editor/images/{test_image}/versions")
        versions = resp.get_json()["versions"]

        assert len(versions) >= 2
        assert versions[0]["edit_type"] == "original"
        assert versions[-1]["edit_type"] == "local_brightness"

    def test_original_preserved(self, logged_in_client, test_image):
        """Test that original image is preserved after edits."""
        resp = logged_in_client.get(f"/api/v1/editor/images/{test_image}/info")
        original_url = resp.get_json()["image"]["url"]

        for _ in range(3):
            logged_in_client.post(
                "/api/v1/editor/local",
                json={
                    "image_id": test_image,
                    "operation": "brightness",
                    "params": {"factor": 1.1},
                },
            )

        resp = logged_in_client.get(original_url)
        assert resp.status_code == 200

    def test_version_numbers_increment(self, logged_in_client, test_image):
        """Test that version numbers increment correctly."""
        for _ in range(3):
            logged_in_client.post(
                "/api/v1/editor/local",
                json={
                    "image_id": test_image,
                    "operation": "rotate",
                    "params": {"angle": 45, "expand": True},
                },
            )

        resp = logged_in_client.get(f"/api/v1/editor/images/{test_image}/versions")
        versions = resp.get_json()["versions"]

        version_numbers = [v["version_number"] for v in versions]
        assert version_numbers == sorted(version_numbers)
        assert len(versions) == 4  # original + 3 edits

    def test_version_file_accessible(self, logged_in_client, test_image):
        """Test that version files are accessible via API."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "flip",
                "params": {"direction": "vertical"},
            },
        )
        version_id = resp.get_json()["version"]["id"]

        resp = logged_in_client.get(f"/api/v1/editor/versions/{version_id}/file")
        assert resp.status_code == 200

    def test_version_detail(self, logged_in_client, test_image):
        """Test getting version details."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "saturation",
                "params": {"factor": 2.0},
            },
        )
        version_id = resp.get_json()["version"]["id"]

        resp = logged_in_client.get(f"/api/v1/editor/versions/{version_id}")
        assert resp.status_code == 200
        data = resp.get_json()["version"]
        assert data["edit_type"] == "local_saturation"
        assert "edit_params" in data


class TestBeforeAfter:
    """Test before/after comparison."""

    def test_comparison_data(self, logged_in_client, test_image):
        """Test getting before/after comparison data."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "brightness",
                "params": {"factor": 1.5},
            },
        )
        version_id = resp.get_json()["version"]["id"]

        resp = logged_in_client.get(f"/api/v1/editor/images/{test_image}/compare/{version_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "before" in data
        assert "after" in data
        assert data["before"]["url"] is not None
        assert data["after"]["url"] is not None


class TestRevert:
    """Test version revert functionality."""

    def test_revert_to_previous_version(self, logged_in_client, test_image):
        """Test reverting to a previous version."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "brightness",
                "params": {"factor": 2.0},
            },
        )
        v2_id = resp.get_json()["version"]["id"]

        logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "contrast",
                "params": {"factor": 0.5},
            },
        )

        resp = logged_in_client.post(f"/api/v1/editor/images/{test_image}/revert/{v2_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"]["edit_type"] == "revert"

        resp = logged_in_client.get(f"/api/v1/editor/images/{test_image}/versions")
        versions = resp.get_json()["versions"]
        assert len(versions) == 4
        assert versions[-1]["edit_type"] == "revert"


class TestMobileResponsiveness:
    """Test that editor is usable on mobile."""

    def test_editor_loads_with_mobile_user_agent(self, logged_in_client):
        """Test editor loads with mobile user agent."""
        resp = logged_in_client.get(
            "/editor",
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)"},
        )
        assert resp.status_code == 200
        assert b"editor.css" in resp.data
        assert b"editor-toolbar" in resp.data


class TestMaskingSystem:
    """Test masking functionality."""

    def test_ai_edit_with_mask_data(self, logged_in_client, test_image):
        """Test AI edit with base64 mask data."""
        import base64
        mask_data = (
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAY"
            "AAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
        )

        resp = logged_in_client.post(
            "/api/v1/editor/ai",
            json={
                "image_id": test_image,
                "operation": "inpaint",
                "prompt": "replace with flowers",
                "params": {"provider": "stub"},
                "mask": mask_data,
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"]["edit_type"] == "ai_inpaint"


class TestChainEditing:
    """Test multiple sequential edits."""

    def test_sequential_local_edits(self, logged_in_client, test_image):
        """Test applying multiple sequential local edits."""
        operations = [
            ("brightness", {"factor": 1.2}),
            ("contrast", {"factor": 1.3}),
            ("saturation", {"factor": 0.8}),
        ]

        for op, params in operations:
            resp = logged_in_client.post(
                "/api/v1/editor/local",
                json={
                    "image_id": test_image,
                    "operation": op,
                    "params": params,
                },
            )
            assert resp.status_code == 200

        resp = logged_in_client.get(f"/api/v1/editor/images/{test_image}/versions")
        versions = resp.get_json()["versions"]
        assert len(versions) == 4  # original + 3 edits

    def test_mixed_local_and_ai_edits(self, logged_in_client, test_image):
        """Test mixing local and AI edits."""
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "brightness",
                "params": {"factor": 1.2},
            },
        )
        assert resp.status_code == 200

        resp = logged_in_client.post(
            "/api/v1/editor/ai",
            json={
                "image_id": test_image,
                "operation": "retexture",
                "prompt": "watercolor painting style",
                "params": {"provider": "stub"},
            },
        )
        assert resp.status_code == 200

        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={
                "image_id": test_image,
                "operation": "rotate",
                "params": {"angle": 45, "expand": True},
            },
        )
        assert resp.status_code == 200

        resp = logged_in_client.get(f"/api/v1/editor/images/{test_image}/versions")
        versions = resp.get_json()["versions"]
        assert len(versions) == 4
        assert versions[0]["edit_type"] == "original"
        assert versions[1]["edit_type"] == "local_brightness"
        assert versions[2]["edit_type"] == "ai_retexture"
        assert versions[3]["edit_type"] == "local_rotate"


class TestNewFilterOperations:
    """New local filters: blur, sharpen, grayscale, sepia, invert, vignette,
    duotone, edge_detect, pixelate, posterize, warmth, gamma, vibrance,
    denoise."""

    @pytest.mark.parametrize("operation,params", [
        ("blur", {"radius": 3}),
        ("sharpen", {"factor": 1.8}),
        ("grayscale", {}),
        ("sepia", {}),
        ("invert", {}),
        ("vignette", {"strength": 0.5}),
        ("duotone", {"shadow_color": "#1a1a2e", "highlight_color": "#f4d35e"}),
        ("edge_detect", {}),
        ("pixelate", {"block_size": 10}),
        ("posterize", {"levels": 3}),
        ("warmth", {"amount": 40}),
        ("gamma", {"gamma": 1.6}),
        ("vibrance", {"amount": 50}),
        ("denoise", {"strength": 5}),
    ])
    def test_new_filter_applies_successfully(self, logged_in_client, test_image, operation, params):
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={"image_id": test_image, "operation": operation, "params": params},
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        assert data["status"] == "success"
        assert "version" in data

    def test_invalid_operation_still_rejected(self, logged_in_client, test_image):
        resp = logged_in_client.post(
            "/api/v1/editor/local",
            json={"image_id": test_image, "operation": "not_a_real_op", "params": {}},
        )
        assert resp.status_code == 400
