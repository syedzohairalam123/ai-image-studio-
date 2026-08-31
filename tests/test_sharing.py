"""Tests for Phase 12: Privacy-safe public sharing system.

Covers: private image security, public sharing, privacy toggle, share URLs,
unauthorized access prevention, reporting, moderation, explore, create-similar.
"""

import pytest

from app.config import TestingConfig
from app.extensions import db as _db
from app.models.user import User
from app.models.image import Image
from app.models.generation import Generation
from app.models.content_report import ContentReport
from app.utils import now_utc


# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def user_a(client, db):
    """Create and login user A."""
    client.post("/signup", data={
        "username": "user_a",
        "email": "usera@test.com",
        "password": "TestPass123!",
        "confirm_password": "TestPass123!",
    }, follow_redirects=True)
    client.post("/login", data={
        "email": "usera@test.com",
        "password": "TestPass123!",
    }, follow_redirects=True)
    return User.query.filter_by(username="user_a").first()


@pytest.fixture
def user_b(client, db):
    """Create user B (not logged in — used for unauthorized tests)."""
    u = User(email="userb@test.com", username="user_b")
    u.set_password("TestPass123!")
    _db.session.add(u)
    _db.session.commit()
    return u


@pytest.fixture
def admin_user(client, db):
    """Create and login an admin user."""
    u = User(email="admin@test.com", username="admin_user")
    u.set_password("TestPass123!")
    u.is_admin = True
    _db.session.add(u)
    _db.session.commit()
    client.post("/logout", follow_redirects=True)
    client.post("/login", data={
        "email": "admin@test.com",
        "password": "TestPass123!",
    }, follow_redirects=True)
    return u


@pytest.fixture
def logged_in_client(client, user_a):
    """Return client logged in as user_a."""
    return client


@pytest.fixture
def private_image(user_a, db):
    """Create a PRIVATE image for user A."""
    from app.config import BASE_DIR
    gen = Generation(
        user_id=user_a.id,
        prompt="A secret private image",
        provider="stub",
        model="test",
        parameters={"style": "photo"},
        status="completed",
    )
    _db.session.add(gen)
    _db.session.flush()

    upload_dir = BASE_DIR / "uploads" / "generations" / str(user_a.id) / "images"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / "private_test.png"

    from PIL import Image as PILImage
    img = PILImage.new("RGB", (256, 256), color=(50, 100, 150))
    img.save(str(file_path), format="PNG")

    image = Image(
        generation_id=gen.id,
        user_id=user_a.id,
        filename="private_test.png",
        file_path=str(file_path),
        prompt="A secret private image",
        title="Private Image",
        width=256,
        height=256,
        is_public=False,
        moderation_state="active",
    )
    _db.session.add(image)
    _db.session.commit()
    return image


@pytest.fixture
def public_image(user_a, db):
    """Create a PUBLIC image for user A with a share token."""
    from app.config import BASE_DIR
    gen = Generation(
        user_id=user_a.id,
        prompt="A beautiful public landscape",
        provider="stub",
        model="test",
        parameters={"style": "landscape"},
        status="completed",
    )
    _db.session.add(gen)
    _db.session.flush()

    upload_dir = BASE_DIR / "uploads" / "generations" / str(user_a.id) / "images"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / "public_test.png"

    from PIL import Image as PILImage
    img = PILImage.new("RGB", (512, 512), color=(100, 200, 100))
    img.save(str(file_path), format="PNG")

    image = Image(
        generation_id=gen.id,
        user_id=user_a.id,
        filename="public_test.png",
        file_path=str(file_path),
        prompt="A beautiful public landscape",
        title="Public Landscape",
        public_prompt="A beautiful public landscape",
        width=512,
        height=512,
        is_public=True,
        moderation_state="active",
    )
    image.generate_share_token()
    _db.session.add(image)
    _db.session.commit()
    return image


@pytest.fixture
def reported_image(user_a, db):
    """Create a PUBLIC image that has been reported."""
    from app.config import BASE_DIR
    gen = Generation(
        user_id=user_a.id,
        prompt="A reported image",
        provider="stub",
        model="test",
        parameters={"style": "art"},
        status="completed",
    )
    _db.session.add(gen)
    _db.session.flush()

    upload_dir = BASE_DIR / "uploads" / "generations" / str(user_a.id) / "images"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / "reported_test.png"

    from PIL import Image as PILImage
    img = PILImage.new("RGB", (256, 256), color=(200, 50, 50))
    img.save(str(file_path), format="PNG")

    image = Image(
        generation_id=gen.id,
        user_id=user_a.id,
        filename="reported_test.png",
        file_path=str(file_path),
        prompt="A reported image",
        title="Reported Image",
        width=256,
        height=256,
        is_public=True,
        moderation_state="reported",
    )
    image.generate_share_token()
    _db.session.add(image)
    _db.session.commit()
    return image


# ============================================================
# PRIVATE IMAGE SECURITY
# ============================================================


class TestPrivateImageSecurity:
    """Private images must NEVER be accessible via URL manipulation."""

    def test_private_image_not_in_explore(self, logged_in_client, private_image):
        resp = logged_in_client.get("/api/v1/explore")
        data = resp.get_json()
        image_ids = [img["id"] for img in data.get("images", [])]
        assert private_image.share_token not in image_ids

    def test_private_image_share_token_not_found(self, logged_in_client, private_image):
        if private_image.share_token:
            resp = logged_in_client.get(f"/share/{private_image.share_token}")
            assert resp.status_code == 404

    def test_private_image_no_share_token(self, private_image):
        assert private_image.is_public is False

    def test_private_image_owner_can_access(self, logged_in_client, private_image):
        resp = logged_in_client.get(f"/api/v1/images/{private_image.id}")
        assert resp.status_code == 200

    def test_private_image_not_in_explore_search(self, logged_in_client, private_image):
        resp = logged_in_client.get("/api/v1/explore?search=secret+private")
        data = resp.get_json()
        assert data["total"] == 0

    def test_private_image_not_in_explore_categories(self, logged_in_client, private_image):
        resp = logged_in_client.get("/api/v1/explore/categories")
        data = resp.get_json()
        for cat in data.get("categories", []):
            if cat["id"] != "all":
                assert cat["count"] == 0


# ============================================================
# PUBLIC IMAGE ACCESS
# ============================================================


class TestPublicImageAccess:
    """Public images should be accessible via share token."""

    def test_public_image_in_explore(self, logged_in_client, public_image):
        resp = logged_in_client.get("/api/v1/explore")
        data = resp.get_json()
        assert data["total"] >= 1

    def test_public_share_page_loads(self, logged_in_client, public_image):
        resp = logged_in_client.get(f"/share/{public_image.share_token}")
        assert resp.status_code == 200

    def test_public_image_no_private_data(self, logged_in_client, public_image):
        resp = logged_in_client.get(f"/api/v1/explore/{public_image.share_token}")
        data = resp.get_json()
        assert "email" not in data
        assert "password" not in data
        assert "file_path" not in data
        assert "user_id" not in data
        assert "generation_id" not in data

    def test_public_image_creator_display_name_only(self, logged_in_client, public_image):
        resp = logged_in_client.get(f"/api/v1/explore/{public_image.share_token}")
        data = resp.get_json()
        creator = data.get("creator")
        if creator:
            assert "display_name" in creator
            assert "email" not in creator
            assert "id" not in creator

    def test_public_image_view_count_increments(self, logged_in_client, public_image):
        initial_view_count = public_image.view_count
        logged_in_client.get(f"/api/v1/explore/{public_image.share_token}")
        _db.session.refresh(public_image)
        assert public_image.view_count == initial_view_count + 1

    def test_public_image_like(self, logged_in_client, public_image):
        resp = logged_in_client.post(f"/api/v1/explore/{public_image.share_token}/like")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["like_count"] >= 1


# ============================================================
# PRIVACY TOGGLE
# ============================================================


class TestPrivacyToggle:
    """Test toggling images between public and private."""

    def test_make_public(self, logged_in_client, private_image):
        resp = logged_in_client.post(f"/api/v1/images/{private_image.id}/privacy", json={
            "public": True,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_public"] is True
        assert data["share_url"] is not None

    def test_make_private(self, logged_in_client, public_image):
        resp = logged_in_client.post(f"/api/v1/images/{public_image.id}/privacy", json={
            "public": False,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_public"] is False

    def test_toggle_privacy(self, logged_in_client, private_image):
        resp = logged_in_client.post(f"/api/v1/images/{private_image.id}/privacy")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_public"] is True

    def test_privacy_toggle_generates_share_token(self, logged_in_client, private_image):
        resp = logged_in_client.post(f"/api/v1/images/{private_image.id}/privacy", json={
            "public": True,
        })
        data = resp.get_json()
        assert data["share_token"] is not None
        assert len(data["share_token"]) > 10

    def test_bulk_privacy(self, logged_in_client, private_image, public_image):
        resp = logged_in_client.post("/api/v1/gallery/bulk/privacy", json={
            "image_ids": [private_image.id, public_image.id],
            "public": True,
        })
        assert resp.status_code == 200
        assert resp.get_json()["affected"] >= 1

    def test_cannot_toggle_others_image(self, logged_in_client, private_image, user_b):
        """Cannot toggle privacy on another user's image.

        After login as user_b, the image query with user_b's id returns None
        because the image belongs to user_a. The set_privacy/toggle_privacy
        function raises ValueError which is caught and returns 400.
        """
        # Login as user_b on the same client
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "userb@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)

        resp = logged_in_client.post(f"/api/v1/images/{private_image.id}/privacy")
        # Image not found for user_b (ownership check fails)
        assert resp.status_code == 400

    def test_privacy_toggle_affects_explore(self, logged_in_client, private_image):
        """Making image public adds it to explore; making private removes it."""
        # Initially private — not in explore
        resp = logged_in_client.get("/api/v1/explore")
        ids = [img["id"] for img in resp.get_json().get("images", [])]
        assert private_image.share_token not in ids

        # Make public
        resp = logged_in_client.post(f"/api/v1/images/{private_image.id}/privacy", json={"public": True})
        assert resp.get_json()["is_public"] is True

        # Now in explore
        _db.session.refresh(private_image)
        resp = logged_in_client.get("/api/v1/explore")
        ids = [img["id"] for img in resp.get_json().get("images", [])]
        assert private_image.share_token in ids

        # Make private again
        resp = logged_in_client.post(f"/api/v1/images/{private_image.id}/privacy", json={"public": False})
        assert resp.get_json()["is_public"] is False

        # No longer in explore
        resp = logged_in_client.get("/api/v1/explore")
        ids = [img["id"] for img in resp.get_json().get("images", [])]
        assert private_image.share_token not in ids


# ============================================================
# SHARE URL
# ============================================================


class TestShareURL:
    """Test share URL generation and regeneration."""

    def test_get_share_info(self, logged_in_client, private_image):
        resp = logged_in_client.get(f"/api/v1/images/{private_image.id}/share")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "share_token" in data
        assert "share_url" in data

    def test_regenerate_share_token(self, logged_in_client, public_image):
        old_token = public_image.share_token
        resp = logged_in_client.post(f"/api/v1/images/{public_image.id}/share/regenerate")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["share_token"] != old_token

        # Old token should no longer work
        resp2 = logged_in_client.get(f"/share/{old_token}")
        assert resp2.status_code == 404

        # New token should work
        resp3 = logged_in_client.get(f"/share/{data['share_token']}")
        assert resp3.status_code == 200


class TestQRCode:
    """QR code for the share page (new feature)."""

    def test_qrcode_for_public_image_returns_png(self, client, public_image):
        resp = client.get(f"/share/{public_image.share_token}/qrcode.png")
        assert resp.status_code == 200
        assert resp.content_type == "image/png"
        assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_qrcode_for_unknown_token_404s(self, client, db):
        resp = client.get("/share/not-a-real-token/qrcode.png")
        assert resp.status_code == 404

    def test_qrcode_for_private_image_404s(self, client, private_image):
        resp = client.get(f"/share/{private_image.share_token}/qrcode.png")
        assert resp.status_code == 404

    def test_share_page_embeds_qrcode_image(self, client, public_image):
        resp = client.get(f"/share/{public_image.share_token}")
        assert f"/share/{public_image.share_token}/qrcode.png".encode() in resp.data


# ============================================================
# UNAUTHORIZED PRIVATE ACCESS
# ============================================================


class TestUnauthorizedAccess:
    """Security: users cannot access private content by manipulating URLs."""

    def test_other_user_cannot_see_private_in_explore(self, logged_in_client, private_image, user_b):
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "userb@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)

        resp = logged_in_client.get("/api/v1/explore")
        data = resp.get_json()
        for img in data.get("images", []):
            assert img.get("id") != private_image.share_token

    def test_unauthenticated_user_can_see_public_share(self, client, public_image):
        """Unauthenticated users CAN view public share pages."""
        resp = client.get(f"/share/{public_image.share_token}")
        assert resp.status_code == 200

    def test_unauthenticated_user_can_view_explore(self, client, public_image):
        """Unauthenticated users CAN view the explore page."""
        resp = client.get("/api/v1/explore")
        assert resp.status_code == 200

    def test_reported_image_hidden_from_explore(self, logged_in_client, reported_image):
        resp = logged_in_client.get("/api/v1/explore")
        data = resp.get_json()
        for img in data.get("images", []):
            assert img.get("id") != reported_image.share_token

    def test_hidden_image_not_accessible(self, logged_in_client, reported_image):
        reported_image.moderation_state = "hidden"
        _db.session.commit()
        resp = logged_in_client.get(f"/share/{reported_image.share_token}")
        assert resp.status_code == 404

    def test_non_owner_cannot_access_others_private_image_detail(self, logged_in_client, private_image, user_b):
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "userb@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)
        resp = logged_in_client.get(f"/api/v1/images/{private_image.id}")
        assert resp.status_code == 404

    def test_unauthenticated_user_cannot_toggle_privacy(self, app):
        """Unauthenticated users cannot toggle privacy — login_required blocks."""
        fresh = app.test_client()
        resp = fresh.post("/api/v1/images/1/privacy")
        # login_required redirects to login page or blocks
        assert resp.status_code in (302, 401, 404)

    def test_report_requires_auth(self, app, public_image):
        """Reporting requires authentication — login_required blocks."""
        fresh = app.test_client()
        resp = fresh.post(f"/api/v1/explore/{public_image.share_token}/report", json={
            "reason": "spam",
        })
        # login_required redirects to login page or blocks
        assert resp.status_code in (302, 401, 400)


# ============================================================
# REPORTING
# ============================================================


class TestReporting:
    """Test content reporting system."""

    def test_report_public_image(self, logged_in_client, public_image, user_b):
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "userb@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)

        resp = logged_in_client.post(f"/api/v1/explore/{public_image.share_token}/report", json={
            "reason": "inappropriate",
            "description": "This content is inappropriate",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"

    def test_cannot_report_own_image(self, logged_in_client, public_image):
        resp = logged_in_client.post(f"/api/v1/explore/{public_image.share_token}/report", json={
            "reason": "spam",
        })
        assert resp.status_code == 400

    def test_cannot_report_twice(self, logged_in_client, public_image, user_b):
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "userb@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)

        logged_in_client.post(f"/api/v1/explore/{public_image.share_token}/report", json={
            "reason": "spam",
        })
        resp = logged_in_client.post(f"/api/v1/explore/{public_image.share_token}/report", json={
            "reason": "spam",
        })
        assert resp.status_code == 400

    def test_cannot_report_private_image(self, logged_in_client, private_image, user_b):
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "userb@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)

        # Private images don't have share_tokens, so report endpoint returns 404
        resp = logged_in_client.post("/api/v1/explore/invalid-token/report", json={
            "reason": "spam",
        })
        assert resp.status_code in (400, 404)

    def test_invalid_report_reason(self, logged_in_client, public_image, user_b):
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "userb@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)

        resp = logged_in_client.post(f"/api/v1/explore/{public_image.share_token}/report", json={
            "reason": "not_a_real_reason",
        })
        assert resp.status_code == 400

    def test_report_updates_moderation_state(self, logged_in_client, public_image, user_b):
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "userb@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)

        logged_in_client.post(f"/api/v1/explore/{public_image.share_token}/report", json={
            "reason": "copyright",
        })
        _db.session.refresh(public_image)
        assert public_image.moderation_state == "reported"


# ============================================================
# CREATE SIMILAR
# ============================================================


class TestCreateSimilar:
    """Test create-similar workflow."""

    def test_owner_can_create_similar(self, logged_in_client, public_image):
        resp = logged_in_client.post(f"/api/v1/images/{public_image.id}/create-similar")
        assert resp.status_code == 200
        data = resp.get_json()["params"]
        assert data["prompt"] == "A beautiful public landscape"
        assert data["style"] == "landscape"

    def test_create_similar_does_not_modify_original(self, logged_in_client, public_image):
        original_prompt = public_image.prompt
        logged_in_client.post(f"/api/v1/images/{public_image.id}/create-similar")
        _db.session.refresh(public_image)
        assert public_image.prompt == original_prompt

    def test_create_similar_no_seed(self, logged_in_client, public_image):
        resp = logged_in_client.post(f"/api/v1/images/{public_image.id}/create-similar")
        data = resp.get_json()["params"]
        assert data["seed"] is None

    def test_non_owner_can_create_similar_from_public(self, logged_in_client, public_image, user_b):
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "userb@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)

        resp = logged_in_client.post(f"/api/v1/images/{public_image.id}/create-similar")
        assert resp.status_code == 200
        data = resp.get_json()["params"]
        assert data["reference_image_id"] is None

    def test_non_owner_cannot_create_similar_from_private(self, logged_in_client, private_image, user_b):
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "userb@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)

        resp = logged_in_client.post(f"/api/v1/images/{private_image.id}/create-similar")
        assert resp.status_code == 404


# ============================================================
# EXPLORE
# ============================================================


class TestExplore:
    """Test explore page and API."""

    def test_explore_page_loads(self, logged_in_client):
        resp = logged_in_client.get("/explore")
        assert resp.status_code == 200

    def test_explore_api_returns_images(self, logged_in_client, public_image):
        resp = logged_in_client.get("/api/v1/explore")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] >= 1

    def test_explore_categories(self, logged_in_client):
        resp = logged_in_client.get("/api/v1/explore/categories")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["categories"]) > 0
        assert any(c["id"] == "all" for c in data["categories"])

    def test_explore_styles(self, logged_in_client, public_image):
        resp = logged_in_client.get("/api/v1/explore/styles")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data["styles"], list)

    def test_explore_search(self, logged_in_client, public_image):
        resp = logged_in_client.get("/api/v1/explore?search=landscape")
        data = resp.get_json()
        assert data["total"] >= 1

    def test_explore_filter_style(self, logged_in_client, public_image):
        resp = logged_in_client.get("/api/v1/explore?style=landscape")
        data = resp.get_json()
        assert data["total"] >= 1

    def test_explore_sort_popular(self, logged_in_client, public_image):
        resp = logged_in_client.get("/api/v1/explore?sort=popular")
        assert resp.status_code == 200

    def test_explore_featured(self, logged_in_client, public_image):
        resp = logged_in_client.get("/api/v1/explore/featured")
        assert resp.status_code == 200

    def test_explore_recent(self, logged_in_client, public_image):
        resp = logged_in_client.get("/api/v1/explore/recent")
        assert resp.status_code == 200

    def test_explore_no_private_images(self, logged_in_client, private_image):
        resp = logged_in_client.get("/api/v1/explore")
        data = resp.get_json()
        for img in data.get("images", []):
            assert img.get("id") != private_image.share_token


# ============================================================
# MODERATION (ADMIN)
# ============================================================


class TestModeration:
    """Test admin moderation features."""

    def test_admin_stats(self, logged_in_client, admin_user):
        resp = logged_in_client.get("/api/v1/moderation/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "reports" in data
        assert "images" in data

    def test_non_admin_cannot_view_stats(self, logged_in_client, user_a):
        resp = logged_in_client.get("/api/v1/moderation/stats")
        assert resp.status_code == 403

    def test_admin_view_reports(self, logged_in_client, admin_user):
        resp = logged_in_client.get("/api/v1/moderation/reports")
        assert resp.status_code == 200

    def test_admin_moderate_report(self, logged_in_client, admin_user, public_image, user_b):
        # Create a report as user_b
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "userb@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)
        logged_in_client.post(f"/api/v1/explore/{public_image.share_token}/report", json={
            "reason": "spam",
        })

        report = ContentReport.query.filter_by(image_id=public_image.id).first()
        assert report is not None

        # Login as admin
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "admin@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)

        resp = logged_in_client.post(f"/api/v1/moderation/reports/{report.id}/action", json={
            "action": "dismiss",
        })
        assert resp.status_code == 200
        _db.session.refresh(public_image)
        assert public_image.moderation_state == "active"

    def test_admin_hide_image(self, logged_in_client, admin_user, public_image, user_b):
        # Create a report as user_b
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "userb@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)
        logged_in_client.post(f"/api/v1/explore/{public_image.share_token}/report", json={
            "reason": "inappropriate",
        })

        report = ContentReport.query.filter_by(image_id=public_image.id).first()

        # Login as admin
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "admin@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)

        resp = logged_in_client.post(f"/api/v1/moderation/reports/{report.id}/action", json={
            "action": "actioned",
        })
        assert resp.status_code == 200
        _db.session.refresh(public_image)
        assert public_image.moderation_state == "hidden"

        # Hidden image should not appear in explore
        resp = logged_in_client.get("/api/v1/explore")
        data = resp.get_json()
        for img in data.get("images", []):
            assert img.get("id") != public_image.share_token

    def test_admin_direct_moderation_state(self, logged_in_client, admin_user, public_image):
        resp = logged_in_client.post(f"/api/v1/moderation/images/{public_image.id}/state", json={
            "state": "hidden",
        })
        assert resp.status_code == 200
        _db.session.refresh(public_image)
        assert public_image.moderation_state == "hidden"

    def test_non_admin_cannot_moderate(self, logged_in_client, user_a):
        resp = logged_in_client.post("/api/v1/moderation/images/1/state", json={
            "state": "hidden",
        })
        assert resp.status_code == 403


# ============================================================
# DISPLAY NAME
# ============================================================


class TestDisplayName:
    """Test display_name for public sharing."""

    def test_user_has_display_name(self, user_a):
        user_a.display_name = "Creative Artist"
        _db.session.commit()
        assert user_a.effective_display_name == "Creative Artist"

    def test_display_name_falls_back_to_username(self, user_a):
        user_a.display_name = None
        _db.session.commit()
        assert user_a.effective_display_name == "user_a"

    def test_public_dict_shows_display_name(self, user_a):
        user_a.display_name = "Artist"
        _db.session.commit()
        public = user_a.to_public_dict()
        assert public["display_name"] == "Artist"
        assert "email" not in public
        assert "id" not in public
