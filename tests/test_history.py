"""Phase 6 — Generation History, Favorites, Image Detail, Ownership, Soft Delete tests."""

import json
import pytest
from app.extensions import db
from app.models.user import User
from app.models.generation import Generation
from app.models.image import Image


# ---- Helpers ----

def create_user(email="p6@test.com", username="p6user", password="securepass123"):
    user = User(email=email, username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, email="p6@test.com", password="securepass123"):
    return client.post("/login", data={
        "email": email, "password": password,
    }, follow_redirects=True)


def logout(client):
    return client.post("/logout", follow_redirects=True)


def switch_user(client, email, password="securepass123"):
    """Logout current user and login as a different user."""
    logout(client)
    return login(client, email=email, password=password)


def generate_image(client, prompt="A beautiful sunset", **kwargs):
    payload = {"prompt": prompt, **kwargs}
    return client.post("/api/v1/generate",
                       data=json.dumps(payload),
                       content_type="application/json")


def create_generation(user_id, prompt="Test prompt", status="completed",
                      style="auto", model="stub-model", provider="stub"):
    """Create a generation directly in the DB for testing."""
    gen = Generation(
        user_id=user_id,
        prompt=prompt,
        provider=provider,
        model=model,
        parameters={"style": style, "aspect_ratio": "1:1", "quality": "standard",
                     "width": 512, "height": 512},
        status=status,
    )
    db.session.add(gen)
    db.session.commit()
    return gen


def create_image(user_id, generation_id, filename="test.png",
                 is_favorite=False, width=512, height=512):
    """Create an image directly in the DB."""
    img = Image(
        generation_id=generation_id,
        user_id=user_id,
        filename=filename,
        file_path=f"/uploads/{filename}",
        width=width,
        height=height,
        is_favorite=is_favorite,
    )
    db.session.add(img)
    db.session.commit()
    return img


# ============================================================
# HISTORY PERSISTENCE TESTS
# ============================================================

class TestHistoryPersistence:
    """Verify generations persist and are returned correctly."""

    def test_generation_appears_in_history(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Persistent image")
        assert resp.status_code == 200

        hist = client.get("/api/v1/generations")
        data = hist.get_json()
        assert data["total"] >= 1
        prompts = [g["prompt"] for g in data["generations"]]
        assert "Persistent image" in prompts

    def test_history_shows_correct_user_only(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")

        login(client, email="u1@x.com")
        generate_image(client, prompt="User1 image")

        switch_user(client, email="u2@x.com")
        generate_image(client, prompt="User2 image")

        # Switch back to user1
        switch_user(client, email="u1@x.com")
        hist = client.get("/api/v1/generations").get_json()
        prompts = [g["prompt"] for g in hist["generations"]]
        assert "User1 image" in prompts
        assert "User2 image" not in prompts

    def test_generation_to_dict_includes_style(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Styled image", style="anime")
        data = resp.get_json()
        gen = Generation.query.get(data["generation"]["id"])
        d = gen.to_dict()
        assert d["style"] == "anime"

    def test_image_to_dict_includes_favorite_field(self, db):
        user = create_user()
        gen = create_generation(user.id)
        img = create_image(user.id, gen.id)
        d = img.to_dict()
        assert "is_favorite" in d
        assert d["is_favorite"] is False

    def test_image_to_dict_includes_deleted_field(self, db):
        user = create_user()
        gen = create_generation(user.id)
        img = create_image(user.id, gen.id)
        d = img.to_dict()
        assert "is_deleted" in d
        assert d["is_deleted"] is False


# ============================================================
# SEARCH TESTS
# ============================================================

class TestSearch:
    """Search by prompt text."""

    def test_search_finds_matching_prompt(self, client, db):
        create_user()
        login(client)
        generate_image(client, prompt="Golden retriever in a park")
        generate_image(client, prompt="Sunset over mountains")

        resp = client.get("/api/v1/generations?search=golden")
        data = resp.get_json()
        assert data["total"] == 1
        assert "Golden retriever" in data["generations"][0]["prompt"]

    def test_search_case_insensitive(self, client, db):
        create_user()
        login(client)
        generate_image(client, prompt="Blue Sky Above")

        resp = client.get("/api/v1/generations?search=blue sky")
        data = resp.get_json()
        assert data["total"] == 1

    def test_search_no_results(self, client, db):
        create_user()
        login(client)
        generate_image(client, prompt="A cat")

        resp = client.get("/api/v1/generations?search=elephant")
        data = resp.get_json()
        assert data["total"] == 0

    def test_search_empty_string(self, client, db):
        create_user()
        login(client)
        generate_image(client, prompt="A dog")

        resp = client.get("/api/v1/generations?search=")
        data = resp.get_json()
        assert data["total"] >= 1


# ============================================================
# FILTER TESTS
# ============================================================

class TestFilter:
    """Filter by style, model, status, favorite, date."""

    def test_filter_by_style(self, client, db):
        create_user()
        login(client)
        generate_image(client, prompt="Image 1", style="anime")
        generate_image(client, prompt="Image 2", style="photo")

        resp = client.get("/api/v1/generations?style=anime")
        data = resp.get_json()
        assert data["total"] == 1
        assert data["generations"][0]["style"] == "anime"

    def test_filter_by_model(self, client, db):
        user = create_user()
        login(client)
        g1 = create_generation(user.id, prompt="G1", model="model-a")
        g2 = create_generation(user.id, prompt="G2", model="model-b")

        resp = client.get("/api/v1/generations?model=model-a")
        data = resp.get_json()
        assert data["total"] == 1

    def test_filter_by_status(self, client, db):
        user = create_user()
        login(client)
        create_generation(user.id, prompt="Done", status="completed")
        create_generation(user.id, prompt="Oops", status="failed")

        resp = client.get("/api/v1/generations?status=failed")
        data = resp.get_json()
        assert data["total"] == 1
        assert data["generations"][0]["status"] == "failed"

    def test_filter_by_favorite(self, client, db):
        user = create_user()
        login(client)
        gen1 = create_generation(user.id, prompt="Fav image")
        gen2 = create_generation(user.id, prompt="Normal image")
        img1 = create_image(user.id, gen1.id, is_favorite=True)
        img2 = create_image(user.id, gen2.id, is_favorite=False)

        resp = client.get("/api/v1/generations?favorite=true")
        data = resp.get_json()
        assert data["total"] == 1
        assert data["generations"][0]["prompt"] == "Fav image"

    def test_filter_by_date_from(self, client, db):
        create_user()
        login(client)
        generate_image(client, prompt="Recent image")

        resp = client.get("/api/v1/generations?date_from=2020-01-01")
        data = resp.get_json()
        assert data["total"] >= 1

    def test_filter_by_date_to(self, client, db):
        create_user()
        login(client)
        generate_image(client, prompt="Old image")

        resp = client.get("/api/v1/generations?date_to=2020-01-01")
        data = resp.get_json()
        assert data["total"] == 0

    def test_combined_filters(self, client, db):
        create_user()
        login(client)
        generate_image(client, prompt="Anime sunset", style="anime")
        generate_image(client, prompt="Photo sunset", style="photo")
        generate_image(client, prompt="Anime cat", style="anime")

        resp = client.get("/api/v1/generations?style=anime&search=sunset")
        data = resp.get_json()
        assert data["total"] == 1
        assert "Anime sunset" in data["generations"][0]["prompt"]

    def test_filter_returns_available_options(self, client, db):
        user = create_user()
        login(client)
        create_generation(user.id, prompt="G1", style="anime", model="m1")
        create_generation(user.id, prompt="G2", style="photo", model="m2")

        resp = client.get("/api/v1/generations").get_json()
        filters = resp["filters"]
        assert "anime" in filters["styles"]
        assert "photo" in filters["styles"]
        assert "m1" in filters["models"]
        assert "m2" in filters["models"]


# ============================================================
# SORT TESTS
# ============================================================

class TestSort:
    """Sort by newest and oldest."""

    def test_sort_newest_first(self, client, db):
        create_user()
        login(client)
        generate_image(client, prompt="First")
        generate_image(client, prompt="Second")

        resp = client.get("/api/v1/generations?sort=newest")
        data = resp.get_json()
        prompts = [g["prompt"] for g in data["generations"]]
        assert prompts.index("Second") < prompts.index("First")

    def test_sort_oldest_first(self, client, db):
        create_user()
        login(client)
        generate_image(client, prompt="First")
        generate_image(client, prompt="Second")

        resp = client.get("/api/v1/generations?sort=oldest")
        data = resp.get_json()
        prompts = [g["prompt"] for g in data["generations"]]
        assert prompts.index("First") < prompts.index("Second")

    def test_default_sort_is_newest(self, client, db):
        create_user()
        login(client)
        generate_image(client, prompt="First")
        generate_image(client, prompt="Second")

        resp = client.get("/api/v1/generations")
        data = resp.get_json()
        prompts = [g["prompt"] for g in data["generations"]]
        assert prompts.index("Second") < prompts.index("First")


# ============================================================
# FAVORITE TESTS
# ============================================================

class TestFavorite:
    """Toggle favorite status."""

    def test_toggle_favorite(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Fav me")
        data = resp.get_json()
        img_id = data["images"][0]["id"]

        # Toggle on
        fav_resp = client.post(f"/api/v1/images/{img_id}/favorite")
        assert fav_resp.status_code == 200
        assert fav_resp.get_json()["is_favorite"] is True

        # Toggle off
        fav_resp = client.post(f"/api/v1/images/{img_id}/favorite")
        assert fav_resp.status_code == 200
        assert fav_resp.get_json()["is_favorite"] is False

    def test_favorite_requires_auth(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Fav auth")
        img_id = resp.get_json()["images"][0]["id"]
        logout(client)

        fav_resp = client.post(f"/api/v1/images/{img_id}/favorite")
        assert fav_resp.status_code == 302

    def test_favorite_nonexistent_image(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/images/99999/favorite")
        assert resp.status_code == 404

    def test_favorites_list_endpoint(self, client, db):
        create_user()
        login(client)
        resp1 = generate_image(client, prompt="Fav 1")
        resp2 = generate_image(client, prompt="Fav 2")
        img1 = resp1.get_json()["images"][0]["id"]
        img2 = resp2.get_json()["images"][0]["id"]

        # Favorite only first
        client.post(f"/api/v1/images/{img1}/favorite")

        fav_resp = client.get("/api/v1/favorites")
        data = fav_resp.get_json()
        assert data["total"] == 1
        assert data["images"][0]["id"] == img1

    def test_favorites_requires_auth(self, client):
        resp = client.get("/api/v1/favorites")
        assert resp.status_code == 302


# ============================================================
# SOFT DELETE TESTS
# ============================================================

class TestSoftDelete:
    """Soft delete with confirmation."""

    def test_soft_delete_image(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Delete me")
        img_id = resp.get_json()["images"][0]["id"]

        del_resp = client.delete(f"/api/v1/images/{img_id}")
        assert del_resp.status_code == 200
        assert del_resp.get_json()["status"] == "success"

        # Image should no longer appear in file endpoint
        file_resp = client.get(f"/api/v1/images/{img_id}/file")
        assert file_resp.status_code == 404

    def test_deleted_image_not_in_history(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Gone image")
        data = resp.get_json()
        img_id = data["images"][0]["id"]
        gen_id = data["generation"]["id"]

        # Delete the image
        client.delete(f"/api/v1/images/{img_id}")

        # Check history — generation should be excluded (all images deleted)
        hist = client.get("/api/v1/generations").get_json()
        gen_ids = [g["id"] for g in hist["generations"]]
        assert gen_id not in gen_ids

    def test_deleted_image_not_in_favorites(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Fav deleted")
        img_id = resp.get_json()["images"][0]["id"]

        # Favorite then delete
        client.post(f"/api/v1/images/{img_id}/favorite")
        client.delete(f"/api/v1/images/{img_id}")

        fav_resp = client.get("/api/v1/favorites").get_json()
        assert fav_resp["total"] == 0

    def test_delete_requires_auth(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Auth check")
        img_id = resp.get_json()["images"][0]["id"]
        logout(client)

        del_resp = client.delete(f"/api/v1/images/{img_id}")
        assert del_resp.status_code == 302

    def test_delete_nonexistent(self, client, db):
        create_user()
        login(client)
        resp = client.delete("/api/v1/images/99999")
        assert resp.status_code == 404

    def test_restore_image(self, db):
        user = create_user()
        gen = create_generation(user.id)
        img = create_image(user.id, gen.id)

        assert img.is_deleted is False
        img.soft_delete()
        assert img.is_deleted is True
        assert img.deleted_at is not None

        img.restore()
        assert img.is_deleted is False
        assert img.deleted_at is None


# ============================================================
# OWNERSHIP / SECURITY TESTS
# ============================================================

class TestOwnership:
    """Every query must be scoped to the authenticated user."""

    def test_cannot_access_other_users_image_detail(self, client, db):
        user1 = create_user(email="own1@x.com", username="own1")
        user2 = create_user(email="own2@x.com", username="own2")

        gen = create_generation(user2.id, prompt="User2's secret image")
        img = create_image(user2.id, gen.id)

        # User1 tries to access User2's image
        login(client, email="own1@x.com")
        resp = client.get(f"/api/v1/images/{img.id}")
        assert resp.status_code == 404  # not found (no leak)

    def test_cannot_delete_other_users_image(self, client, db):
        user1 = create_user(email="own1@x.com", username="own1")
        user2 = create_user(email="own2@x.com", username="own2")

        gen = create_generation(user2.id)
        img = create_image(user2.id, gen.id)

        login(client, email="own1@x.com")
        resp = client.delete(f"/api/v1/images/{img.id}")
        assert resp.status_code == 404  # not found

    def test_cannot_favorite_other_users_image(self, client, db):
        user1 = create_user(email="own1@x.com", username="own1")
        user2 = create_user(email="own2@x.com", username="own2")

        gen = create_generation(user2.id)
        img = create_image(user2.id, gen.id)

        login(client, email="own1@x.com")
        resp = client.post(f"/api/v1/images/{img.id}/favorite")
        assert resp.status_code == 404  # not found

    def test_cannot_download_other_users_image(self, client, db):
        user1 = create_user(email="own1@x.com", username="own1")
        user2 = create_user(email="own2@x.com", username="own2")

        gen = create_generation(user2.id)
        img = create_image(user2.id, gen.id)

        login(client, email="own1@x.com")
        resp = client.get(f"/api/v1/images/{img.id}/download")
        assert resp.status_code == 403

    def test_history_does_not_leak_other_users_data(self, client, db):
        user1 = create_user(email="own1@x.com", username="own1")
        user2 = create_user(email="own2@x.com", username="own2")

        create_generation(user2.id, prompt="Secret user2 data")

        login(client, email="own1@x.com")
        resp = client.get("/api/v1/generations").get_json()
        for g in resp["generations"]:
            assert g["prompt"] != "Secret user2 data"

    def test_favorites_does_not_leak_other_users(self, client, db):
        user1 = create_user(email="own1@x.com", username="own1")
        user2 = create_user(email="own2@x.com", username="own2")

        gen2 = create_generation(user2.id, prompt="User2 fav")
        create_image(user2.id, gen2.id, is_favorite=True)

        login(client, email="own1@x.com")
        resp = client.get("/api/v1/favorites").get_json()
        assert resp["total"] == 0

    def test_nonexistent_image_returns_404_not_403(self, client, db):
        """Prevent IDOR — requesting a non-existent ID should return 404, not 403."""
        create_user()
        login(client)
        resp = client.get("/api/v1/images/12345")
        assert resp.status_code == 404


# ============================================================
# PAGINATION TESTS
# ============================================================

class TestPagination:
    """Pagination of generations, images, and favorites."""

    def test_pagination_generations(self, client, db):
        create_user()
        login(client)
        for i in range(5):
            generate_image(client, prompt=f"Image {i}")

        resp = client.get("/api/v1/generations?page=1&per_page=2").get_json()
        assert len(resp["generations"]) == 2
        assert resp["total"] == 5
        assert resp["has_next"] is True
        assert resp["has_prev"] is False
        assert resp["pages"] == 3

    def test_pagination_last_page(self, client, db):
        create_user()
        login(client)
        for i in range(5):
            generate_image(client, prompt=f"Image {i}")

        resp = client.get("/api/v1/generations?page=3&per_page=2").get_json()
        assert len(resp["generations"]) == 1
        assert resp["has_next"] is False
        assert resp["has_prev"] is True

    def test_pagination_out_of_range(self, client, db):
        create_user()
        login(client)
        generate_image(client, prompt="Only one")

        resp = client.get("/api/v1/generations?page=100&per_page=20").get_json()
        assert len(resp["generations"]) == 0

    def test_pagination_favorites(self, client, db):
        create_user()
        login(client)
        for i in range(3):
            resp = generate_image(client, prompt=f"Fav {i}")
            img_id = resp.get_json()["images"][0]["id"]
            client.post(f"/api/v1/images/{img_id}/favorite")

        resp = client.get("/api/v1/favorites?page=1&per_page=2").get_json()
        assert len(resp["images"]) == 2
        assert resp["total"] == 3

    def test_per_page_max_limit(self, client, db):
        create_user()
        login(client)
        generate_image(client, prompt="One")

        resp = client.get("/api/v1/generations?per_page=999").get_json()
        # Should cap at 100
        assert resp["per_page"] <= 100


# ============================================================
# THUMBNAIL TESTS
# ============================================================

class TestThumbnail:
    """Thumbnail serving."""

    def test_thumbnail_endpoint_exists(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Thumb test")
        img_id = resp.get_json()["images"][0]["id"]

        thumb_resp = client.get(f"/api/v1/images/{img_id}/thumbnail")
        assert thumb_resp.status_code == 200

    def test_thumbnail_nonexistent(self, client, db):
        create_user()  # ensure tables exist
        resp = client.get("/api/v1/images/99999/thumbnail")
        assert resp.status_code == 404

    def test_thumbnail_not_deleted(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Deleted thumb")
        img_id = resp.get_json()["images"][0]["id"]

        client.delete(f"/api/v1/images/{img_id}")
        thumb_resp = client.get(f"/api/v1/images/{img_id}/thumbnail")
        assert thumb_resp.status_code == 404


# ============================================================
# IMAGE DETAIL TESTS
# ============================================================

class TestImageDetail:
    """Image detail API endpoint."""

    def test_detail_requires_auth(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Detail auth")
        img_id = resp.get_json()["images"][0]["id"]
        logout(client)

        detail_resp = client.get(f"/api/v1/images/{img_id}")
        assert detail_resp.status_code == 302

    def test_detail_includes_metadata(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Detail meta", style="anime")
        data = resp.get_json()
        img_id = data["images"][0]["id"]

        detail_resp = client.get(f"/api/v1/images/{img_id}").get_json()
        assert detail_resp["image"]["id"] == img_id
        assert detail_resp["image"]["aspect_ratio"] is not None
        assert "generation" in detail_resp
        assert detail_resp["generation"]["style"] == "anime"

    def test_detail_nonexistent(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/images/99999")
        assert resp.status_code == 404

    def test_detail_image_view_requires_login(self, client, db):
        """The /images/<id> page route requires auth."""
        create_user()
        login(client)
        resp = generate_image(client, prompt="Page test")
        img_id = resp.get_json()["images"][0]["id"]
        logout(client)

        page_resp = client.get(f"/images/{img_id}")
        assert page_resp.status_code == 302  # redirect to login


# ============================================================
# PAGE RENDERING TESTS
# ============================================================

class TestPageRendering:
    """History and favorites pages render correctly."""

    def test_history_page_renders(self, client, db):
        create_user()
        login(client)
        resp = client.get("/history")
        assert resp.status_code == 200
        assert b"Generation History" in resp.data

    def test_favorites_page_renders(self, client, db):
        create_user()
        login(client)
        resp = client.get("/favorites")
        assert resp.status_code == 200
        assert b"Favorites" in resp.data

    def test_image_detail_page_renders(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Page detail")
        img_id = resp.get_json()["images"][0]["id"]
        page_resp = client.get(f"/images/{img_id}")
        assert page_resp.status_code == 200
        assert b"Image Details" in page_resp.data

    def test_history_page_requires_auth(self, client):
        resp = client.get("/history")
        assert resp.status_code == 302

    def test_favorites_page_requires_auth(self, client):
        resp = client.get("/favorites")
        assert resp.status_code == 302


# ============================================================
# MOBILE LAYOUT TESTS
# ============================================================

class TestMobileLayout:
    """Verify responsive CSS classes and patterns are in place."""

    def test_history_has_responsive_grid(self, client, db):
        create_user()
        login(client)
        resp = client.get("/history")
        assert resp.status_code == 200
        assert b"@media" in resp.data  # Has responsive CSS
        assert b"history-grid" in resp.data

    def test_favorites_has_responsive_grid(self, client, db):
        create_user()
        login(client)
        resp = client.get("/favorites")
        assert resp.status_code == 200
        assert b"@media" in resp.data
        assert b"favorites-grid" in resp.data

    def test_image_detail_has_responsive_layout(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Mobile detail")
        img_id = resp.get_json()["images"][0]["id"]
        page_resp = client.get(f"/images/{img_id}")
        assert page_resp.status_code == 200
        assert b"@media" in page_resp.data
        assert b"detail-layout" in page_resp.data


# ============================================================
# EDGE CASE TESTS
# ============================================================

class TestEdgeCases:
    """Various edge cases."""

    def test_pagination_with_search(self, client, db):
        create_user()
        login(client)
        for i in range(5):
            generate_image(client, prompt=f"Search item {i}")

        resp = client.get("/api/v1/generations?search=item&page=1&per_page=2").get_json()
        assert resp["total"] == 5
        assert len(resp["generations"]) == 2

    def test_all_statuses_listed(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/generations").get_json()
        statuses = resp["filters"]["statuses"]
        assert "completed" in statuses
        assert "failed" in statuses
        assert "pending" in statuses

    def test_image_aspect_ratio_property(self, db):
        user = create_user()
        gen = create_generation(user.id)
        img = create_image(user.id, gen.id, width=768, height=432)
        # 768:432 reduces to 16:9
        assert img.aspect_ratio == "16:9"

    def test_image_aspect_ratio_none_when_no_dimensions(self, db):
        user = create_user()
        gen = create_generation(user.id)
        img = create_image(user.id, gen.id, width=None, height=None)
        assert img.aspect_ratio is None

    def test_soft_delete_sets_timestamp(self, db):
        user = create_user()
        gen = create_generation(user.id)
        img = create_image(user.id, gen.id)

        assert img.deleted_at is None
        img.soft_delete()
        assert img.deleted_at is not None

    def test_duplicate_favorite_toggle_idempotent(self, client, db):
        create_user()
        login(client)
        resp = generate_image(client, prompt="Double fav")
        img_id = resp.get_json()["images"][0]["id"]

        # Toggle on
        client.post(f"/api/v1/images/{img_id}/favorite")
        # Toggle off
        client.post(f"/api/v1/images/{img_id}/favorite")
        # Toggle on again
        r = client.post(f"/api/v1/images/{img_id}/favorite").get_json()
        assert r["is_favorite"] is True
