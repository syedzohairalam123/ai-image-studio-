"""Tests for the gallery and collections system.

Covers: search, filter, sort, multi-select, bulk ops,
collection CRUD, ownership, mobile.
"""

import pytest
from pathlib import Path

from app.config import TestingConfig
from app.extensions import db as _db
from app.models.user import User
from app.models.image import Image
from app.models.generation import Generation
from app.models.tag import Tag
from app.models.collection import Collection


@pytest.fixture
def logged_in_client(client, db):
    """Register and login a test user."""
    client.post("/signup", data={
        "username": "gallery_tester",
        "email": "gallery@test.com",
        "password": "TestPass123!",
        "confirm_password": "TestPass123!",
    }, follow_redirects=True)
    client.post("/login", data={
        "email": "gallery@test.com",
        "password": "TestPass123!",
    }, follow_redirects=True)
    return client


@pytest.fixture
def test_images(logged_in_client, db):
    """Create multiple test images for gallery testing."""
    from app.config import BASE_DIR
    user = User.query.filter_by(username="gallery_tester").first()

    image_ids = []
    styles = ["photo", "art", "anime", "3d", "photo"]
    prompts = [
        "A serene mountain landscape",
        "Digital art cyberpunk city",
        "Anime character portrait",
        "3D rendered product",
        "Sunset over the ocean",
    ]

    for i in range(5):
        gen = Generation(
            user_id=user.id,
            prompt=prompts[i],
            provider="stub",
            model="stable-diffusion",
            parameters={"style": styles[i], "width": 512, "height": 512},
            status="completed",
        )
        _db.session.add(gen)
        _db.session.flush()

        upload_dir = BASE_DIR / "uploads" / "generations" / str(user.id) / "images"
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / f"test_gallery_{i}.png"

        from PIL import Image as PILImage
        img = PILImage.new("RGB", (512, 512), color=(100 + i * 30, 150, 200))
        img.save(str(file_path), format="PNG")

        image = Image(
            generation_id=gen.id,
            user_id=user.id,
            filename=f"test_gallery_{i}.png",
            file_path=str(file_path),
            prompt=prompts[i],
            title=f"Test Image {i}",
            width=512,
            height=512,
            file_size=file_path.stat().st_size,
            is_favorite=(i % 2 == 0),
        )
        _db.session.add(image)
        _db.session.flush()
        image_ids.append(image.id)

    _db.session.commit()
    return image_ids


# ============================================================
# GALLERY LIST
# ============================================================


class TestGalleryList:
    """Test gallery listing with search, filter, sort."""

    def test_gallery_page_loads(self, logged_in_client):
        resp = logged_in_client.get("/gallery")
        assert resp.status_code == 200

    def test_gallery_api_returns_images(self, logged_in_client, test_images):
        resp = logged_in_client.get("/api/v1/gallery")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 5
        assert len(data["images"]) == 5

    def test_gallery_search_by_prompt(self, logged_in_client, test_images):
        resp = logged_in_client.get("/api/v1/gallery?search=mountain")
        data = resp.get_json()
        assert data["total"] >= 1
        assert any("mountain" in img["prompt"].lower() for img in data["images"])

    def test_gallery_search_by_title(self, logged_in_client, test_images):
        resp = logged_in_client.get("/api/v1/gallery?search=Test Image 0")
        data = resp.get_json()
        assert data["total"] >= 1

    def test_gallery_filter_favorites(self, logged_in_client, test_images):
        resp = logged_in_client.get("/api/v1/gallery?favorite=true")
        data = resp.get_json()
        assert data["total"] == 3  # indices 0, 2, 4

    def test_gallery_filter_style(self, logged_in_client, test_images):
        resp = logged_in_client.get("/api/v1/gallery?style=photo")
        data = resp.get_json()
        assert data["total"] == 2  # indices 0, 4

    def test_gallery_sort_newest(self, logged_in_client, test_images):
        resp = logged_in_client.get("/api/v1/gallery?sort=newest")
        data = resp.get_json()
        dates = [img["created_at"] for img in data["images"]]
        assert dates == sorted(dates, reverse=True)

    def test_gallery_sort_oldest(self, logged_in_client, test_images):
        resp = logged_in_client.get("/api/v1/gallery?sort=oldest")
        data = resp.get_json()
        dates = [img["created_at"] for img in data["images"]]
        assert dates == sorted(dates)

    def test_gallery_sort_favorite(self, logged_in_client, test_images):
        resp = logged_in_client.get("/api/v1/gallery?sort=favorite")
        data = resp.get_json()
        favs = [img["is_favorite"] for img in data["images"]]
        assert favs == sorted(favs, reverse=True)

    def test_gallery_pagination(self, logged_in_client, test_images):
        resp = logged_in_client.get("/api/v1/gallery?per_page=2&page=1")
        data = resp.get_json()
        assert len(data["images"]) == 2
        assert data["total"] == 5
        assert data["has_next"] is True

    def test_gallery_filter_options(self, logged_in_client, test_images):
        resp = logged_in_client.get("/api/v1/gallery/filters")
        data = resp.get_json()
        assert "photo" in data["styles"]
        assert "stable-diffusion" in data["models"]


# ============================================================
# BULK OPERATIONS
# ============================================================


class TestBulkOperations:
    """Test bulk favorite, delete, collection, tags."""

    def test_bulk_favorite(self, logged_in_client, test_images):
        resp = logged_in_client.post("/api/v1/gallery/bulk/favorite", json={
            "image_ids": test_images[:3],
            "favorite": True,
        })
        assert resp.status_code == 200
        assert resp.get_json()["affected"] == 3

    def test_bulk_unfavorite(self, logged_in_client, test_images):
        resp = logged_in_client.post("/api/v1/gallery/bulk/favorite", json={
            "image_ids": test_images[:2],
            "favorite": False,
        })
        assert resp.status_code == 200
        assert resp.get_json()["affected"] == 2

    def test_bulk_delete(self, logged_in_client, test_images):
        resp = logged_in_client.post("/api/v1/gallery/bulk/delete", json={
            "image_ids": test_images[-2:],
        })
        assert resp.status_code == 200
        assert resp.get_json()["affected"] == 2

        # Verify deleted
        resp = logged_in_client.get("/api/v1/gallery")
        assert resp.get_json()["total"] == 3

    def test_bulk_add_to_collection(self, logged_in_client, test_images):
        # Create a collection
        resp = logged_in_client.post("/api/v1/collections", json={"name": "Test"})
        coll_id = resp.get_json()["collection"]["id"]

        resp = logged_in_client.post("/api/v1/gallery/bulk/collection", json={
            "image_ids": test_images[:3],
            "collection_id": coll_id,
        })
        assert resp.status_code == 200
        assert resp.get_json()["added"] == 3

    def test_bulk_add_tags(self, logged_in_client, test_images):
        resp = logged_in_client.post("/api/v1/gallery/bulk/tags", json={
            "image_ids": test_images[:2],
            "tags": ["landscape", "sunset"],
        })
        assert resp.status_code == 200

        # Verify tags exist
        resp = logged_in_client.get("/api/v1/tags")
        tags = resp.get_json()["tags"]
        tag_names = [t["name"] for t in tags]
        assert "landscape" in tag_names
        assert "sunset" in tag_names

    def test_bulk_empty_ids(self, logged_in_client):
        resp = logged_in_client.post("/api/v1/gallery/bulk/favorite", json={
            "image_ids": [],
            "favorite": True,
        })
        assert resp.status_code == 400


# ============================================================
# COLLECTIONS CRUD
# ============================================================


class TestCollections:
    """Test collection create, read, update, delete."""

    def test_create_collection(self, logged_in_client):
        resp = logged_in_client.post("/api/v1/collections", json={
            "name": "My Collection",
            "description": "A test collection",
        })
        assert resp.status_code == 201
        data = resp.get_json()["collection"]
        assert data["name"] == "My Collection"
        assert data["description"] == "A test collection"

    def test_list_collections(self, logged_in_client):
        logged_in_client.post("/api/v1/collections", json={"name": "First"})
        logged_in_client.post("/api/v1/collections", json={"name": "Second"})

        resp = logged_in_client.get("/api/v1/collections")
        assert resp.status_code == 200
        assert len(resp.get_json()["collections"]) == 2

    def test_get_collection_detail(self, logged_in_client, test_images):
        resp = logged_in_client.post("/api/v1/collections", json={"name": "Detail Test"})
        coll_id = resp.get_json()["collection"]["id"]

        # Add an image
        logged_in_client.post(f"/api/v1/collections/{coll_id}/images", json={
            "image_id": test_images[0],
        })

        resp = logged_in_client.get(f"/api/v1/collections/{coll_id}")
        assert resp.status_code == 200
        assert len(resp.get_json()["collection"]["images"]) == 1

    def test_update_collection(self, logged_in_client):
        resp = logged_in_client.post("/api/v1/collections", json={"name": "Original"})
        coll_id = resp.get_json()["collection"]["id"]

        resp = logged_in_client.patch(f"/api/v1/collections/{coll_id}", json={
            "name": "Updated",
            "description": "New description",
        })
        assert resp.status_code == 200
        assert resp.get_json()["collection"]["name"] == "Updated"

    def test_delete_collection(self, logged_in_client):
        resp = logged_in_client.post("/api/v1/collections", json={"name": "Delete Me"})
        coll_id = resp.get_json()["collection"]["id"]

        resp = logged_in_client.delete(f"/api/v1/collections/{coll_id}")
        assert resp.status_code == 200

        # Verify deleted
        resp = logged_in_client.get("/api/v1/collections")
        assert len(resp.get_json()["collections"]) == 0

    def test_add_image_to_collection(self, logged_in_client, test_images):
        resp = logged_in_client.post("/api/v1/collections", json={"name": "Test"})
        coll_id = resp.get_json()["collection"]["id"]

        resp = logged_in_client.post(f"/api/v1/collections/{coll_id}/images", json={
            "image_id": test_images[0],
        })
        assert resp.status_code == 200

    def test_remove_image_from_collection(self, logged_in_client, test_images):
        resp = logged_in_client.post("/api/v1/collections", json={"name": "Test"})
        coll_id = resp.get_json()["collection"]["id"]

        logged_in_client.post(f"/api/v1/collections/{coll_id}/images", json={
            "image_id": test_images[0],
        })

        resp = logged_in_client.delete(f"/api/v1/collections/{coll_id}/images/{test_images[0]}")
        assert resp.status_code == 200

    def test_collection_empty_name(self, logged_in_client):
        resp = logged_in_client.post("/api/v1/collections", json={"name": ""})
        assert resp.status_code == 400

    def test_collection_page_loads(self, logged_in_client):
        resp = logged_in_client.get("/collections")
        assert resp.status_code == 200

    def test_collection_detail_page_loads(self, logged_in_client):
        resp = logged_in_client.post("/api/v1/collections", json={"name": "Page Test"})
        coll_id = resp.get_json()["collection"]["id"]

        resp = logged_in_client.get(f"/collections/{coll_id}")
        assert resp.status_code == 200


# ============================================================
# TAGS
# ============================================================


class TestTags:
    """Test tag CRUD operations."""

    def test_create_tag(self, logged_in_client):
        resp = logged_in_client.post("/api/v1/tags", json={
            "name": "landscape",
            "color": "#FF5733",
        })
        assert resp.status_code == 201
        assert resp.get_json()["tag"]["name"] == "landscape"

    def test_list_tags(self, logged_in_client):
        logged_in_client.post("/api/v1/tags", json={"name": "tag1"})
        logged_in_client.post("/api/v1/tags", json={"name": "tag2"})

        resp = logged_in_client.get("/api/v1/tags")
        assert resp.status_code == 200
        assert len(resp.get_json()["tags"]) == 2

    def test_delete_tag(self, logged_in_client):
        resp = logged_in_client.post("/api/v1/tags", json={"name": "delete_me"})
        tag_id = resp.get_json()["tag"]["id"]

        resp = logged_in_client.delete(f"/api/v1/tags/{tag_id}")
        assert resp.status_code == 200

    def test_duplicate_tag_returns_existing(self, logged_in_client):
        resp1 = logged_in_client.post("/api/v1/tags", json={"name": "unique"})
        resp2 = logged_in_client.post("/api/v1/tags", json={"name": "unique"})
        assert resp1.get_json()["tag"]["id"] == resp2.get_json()["tag"]["id"]

    def test_filter_by_tag(self, logged_in_client, test_images):
        # Create tag and add to images
        resp = logged_in_client.post("/api/v1/tags", json={"name": "filtered"})
        tag_id = resp.get_json()["tag"]["id"]

        logged_in_client.post("/api/v1/gallery/bulk/tags", json={
            "image_ids": test_images[:2],
            "tags": ["filtered"],
        })

        resp = logged_in_client.get(f"/api/v1/gallery?tag_id={tag_id}")
        data = resp.get_json()
        assert data["total"] == 2


# ============================================================
# OWNERSHIP / SECURITY
# ============================================================


class TestOwnership:
    """Test that users can only see their own images."""

    def test_cannot_see_other_users_gallery(self, logged_in_client, test_images):
        # Create another user
        from app.models.user import User as UserModel
        other = UserModel(email="other@test.com", username="other_user")
        other.set_password("TestPass123!")
        _db.session.add(other)
        _db.session.commit()

        # Logout first, then login as other user
        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "other@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)

        resp = logged_in_client.get("/api/v1/gallery")
        assert resp.get_json()["total"] == 0

    def test_cannot_access_others_collection(self, logged_in_client, test_images):
        # Create collection as gallery_tester
        resp = logged_in_client.post("/api/v1/collections", json={"name": "My Coll"})
        coll_id = resp.get_json()["collection"]["id"]

        # Login as other user
        from app.models.user import User as UserModel
        other = UserModel(email="other2@test.com", username="other2")
        other.set_password("TestPass123!")
        _db.session.add(other)
        _db.session.commit()

        logged_in_client.post("/logout", follow_redirects=True)
        logged_in_client.post("/login", data={
            "email": "other2@test.com",
            "password": "TestPass123!",
        }, follow_redirects=True)

        resp = logged_in_client.get(f"/api/v1/collections/{coll_id}")
        assert resp.status_code == 404


# ============================================================
# EMPTY GALLERY
# ============================================================


class TestEmptyGallery:
    """Test gallery behavior with no images."""

    def test_empty_gallery(self, logged_in_client):
        resp = logged_in_client.get("/api/v1/gallery")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 0
        assert data["images"] == []

    def test_empty_collections(self, logged_in_client):
        resp = logged_in_client.get("/api/v1/collections")
        assert resp.status_code == 200
        assert resp.get_json()["collections"] == []


# ============================================================
# MOBILE
# ============================================================


class TestMobile:
    """Test mobile responsiveness."""

    def test_gallery_loads_on_mobile(self, logged_in_client):
        resp = logged_in_client.get("/gallery", headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)",
        })
        assert resp.status_code == 200
        assert b"gallery.css" in resp.data

    def test_collections_loads_on_mobile(self, logged_in_client):
        resp = logged_in_client.get("/collections", headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)",
        })
        assert resp.status_code == 200
