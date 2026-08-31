"""Phase 7 — Prompt Workspace tests: enhancement, library, templates, capabilities, seed."""

import json
import pytest
from app.extensions import db
from app.models.user import User
from app.models.generation import Generation
from app.models.saved_prompt import SavedPrompt
from app.services.prompt_service import enhance_prompt, BUILTIN_TEMPLATES


# ---- Helpers ----

def create_user(email="p7@test.com", username="p7user", password="securepass123"):
    user = User(email=email, username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, email="p7@test.com", password="securepass123"):
    return client.post("/login", data={
        "email": email, "password": password,
    }, follow_redirects=True)


def logout(client):
    return client.post("/logout", follow_redirects=True)


def switch_user(client, email, password="securepass123"):
    logout(client)
    return login(client, email=email, password=password)


def create_generation(user_id, prompt="Test prompt", status="completed",
                      style="auto", provider="stub"):
    gen = Generation(
        user_id=user_id,
        prompt=prompt,
        provider=provider,
        parameters={"style": style, "aspect_ratio": "1:1", "quality": "standard",
                     "width": 512, "height": 512},
        status=status,
    )
    db.session.add(gen)
    db.session.commit()
    return gen


def create_saved_prompt(user_id, title="My Prompt", prompt="A beautiful sunset",
                        negative_prompt=None, tags=None, style=None,
                        is_favorite=False):
    sp = SavedPrompt(
        user_id=user_id,
        title=title,
        prompt=prompt,
        negative_prompt=negative_prompt,
        tags=tags or [],
        style=style,
        is_favorite=is_favorite,
    )
    db.session.add(sp)
    db.session.commit()
    return sp


# ============================================================
# PROMPT ENHANCEMENT TESTS
# ============================================================

class TestPromptEnhancement:
    """Test the prompt enhancement service."""

    def test_enhance_returns_original_and_enhanced(self):
        result = enhance_prompt("a cat sitting on a windowsill")
        assert "original" in result
        assert "enhanced" in result
        assert result["original"] == "a cat sitting on a windowsill"
        assert result["enhanced"] != ""

    def test_enhance_includes_original_in_result(self):
        result = enhance_prompt("futuristic city")
        assert result["original"] == "futuristic city"
        assert result["enhanced"].startswith("futuristic city")

    def test_enhance_empty_prompt(self):
        result = enhance_prompt("")
        assert result["original"] == ""
        assert result["enhanced"] == ""

    def test_enhance_returns_dimensions(self):
        result = enhance_prompt("a forest scene")
        assert "dimensions" in result
        assert isinstance(result["dimensions"], dict)

    def test_enhance_detects_environment_keyword(self):
        result = enhance_prompt("a magical forest with trees")
        assert "environment" in result["dimensions"]

    def test_enhance_with_style_photo(self):
        result = enhance_prompt("portrait of a woman", style="photo")
        assert "Canon" in result["enhanced"] or "photorealistic" in result["enhanced"]

    def test_enhance_with_style_anime(self):
        result = enhance_prompt("a school girl", style="anime")
        assert "anime" in result["enhanced"].lower()

    def test_enhance_with_style_3d(self):
        result = enhance_prompt("robot character", style="3d")
        assert "3D render" in result["enhanced"]

    def test_enhance_with_auto_style(self):
        result = enhance_prompt("a mountain landscape", style="auto")
        assert result["style_modifier"] == ""

    def test_enhance_preserves_original(self):
        """Original prompt should never be modified."""
        original = "specific unique prompt xyz123"
        result = enhance_prompt(original)
        assert result["original"] == original

    def test_enhance_api_endpoint(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/prompts/enhance",
                          data=json.dumps({"prompt": "futuristic city", "style": "photo"}),
                          content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "enhanced" in data
        assert data["original"] == "futuristic city"

    def test_enhance_requires_auth(self, client):
        resp = client.post("/api/v1/prompts/enhance",
                          data=json.dumps({"prompt": "test"}),
                          content_type="application/json")
        assert resp.status_code == 302

    def test_enhance_requires_prompt(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/prompts/enhance",
                          data=json.dumps({"prompt": ""}),
                          content_type="application/json")
        assert resp.status_code == 400

    def test_enhance_no_redundancy(self):
        """Enhancement should not repeat words already in the prompt."""
        result = enhance_prompt("golden hour warm lighting in a forest")
        # Should not add redundant lighting terms
        assert result["enhanced"].count("golden hour") <= 1


# ============================================================
# PROMPT LIBRARY CRUD TESTS
# ============================================================

class TestPromptLibraryCRUD:
    """Test saved prompt CRUD operations."""

    def test_create_prompt(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/prompts",
                          data=json.dumps({
                              "title": "Sunset Vibes",
                              "prompt": "A beautiful sunset over the ocean",
                              "tags": ["sunset", "ocean"],
                              "style": "photo",
                          }),
                          content_type="application/json")
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["title"] == "Sunset Vibes"
        assert data["prompt"] == "A beautiful sunset over the ocean"
        assert "sunset" in data["tags"]
        assert data["style"] == "photo"

    def test_create_prompt_with_negative(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/prompts",
                          data=json.dumps({
                              "title": "Clean Portrait",
                              "prompt": "portrait of a person",
                              "negative_prompt": "blurry, distorted",
                          }),
                          content_type="application/json")
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["negative_prompt"] == "blurry, distorted"

    def test_create_requires_title(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/prompts",
                          data=json.dumps({"prompt": "test"}),
                          content_type="application/json")
        assert resp.status_code == 400

    def test_create_requires_prompt(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/prompts",
                          data=json.dumps({"title": "test"}),
                          content_type="application/json")
        assert resp.status_code == 400

    def test_create_requires_auth(self, client):
        resp = client.post("/api/v1/prompts",
                          data=json.dumps({"title": "t", "prompt": "p"}),
                          content_type="application/json")
        assert resp.status_code == 302

    def test_list_prompts(self, client, db):
        user = create_user()
        login(client)
        create_saved_prompt(user.id, title="Prompt 1", prompt="sunset")
        create_saved_prompt(user.id, title="Prompt 2", prompt="ocean")

        resp = client.get("/api/v1/prompts")
        data = resp.get_json()
        assert data["total"] == 2
        assert len(data["prompts"]) == 2

    def test_list_prompts_empty(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/prompts")
        data = resp.get_json()
        assert data["total"] == 0

    def test_get_prompt(self, client, db):
        user = create_user()
        login(client)
        sp = create_saved_prompt(user.id, title="Get Me")
        resp = client.get(f"/api/v1/prompts/{sp.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["title"] == "Get Me"

    def test_get_nonexistent_prompt(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/prompts/99999")
        assert resp.status_code == 404

    def test_update_prompt(self, client, db):
        user = create_user()
        login(client)
        sp = create_saved_prompt(user.id, title="Old Title")
        resp = client.put(f"/api/v1/prompts/{sp.id}",
                         data=json.dumps({"title": "New Title"}),
                         content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["title"] == "New Title"

    def test_update_prompt_content(self, client, db):
        user = create_user()
        login(client)
        sp = create_saved_prompt(user.id, prompt="old prompt")
        resp = client.put(f"/api/v1/prompts/{sp.id}",
                         data=json.dumps({"prompt": "new prompt"}),
                         content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["prompt"] == "new prompt"

    def test_update_nonexistent(self, client, db):
        create_user()
        login(client)
        resp = client.put("/api/v1/prompts/99999",
                         data=json.dumps({"title": "x"}),
                         content_type="application/json")
        assert resp.status_code == 404

    def test_delete_prompt(self, client, db):
        user = create_user()
        login(client)
        sp = create_saved_prompt(user.id)
        resp = client.delete(f"/api/v1/prompts/{sp.id}")
        assert resp.status_code == 200
        # Verify deleted
        assert SavedPrompt.query.get(sp.id) is None

    def test_delete_nonexistent(self, client, db):
        create_user()
        login(client)
        resp = client.delete("/api/v1/prompts/99999")
        assert resp.status_code == 404

    def test_search_prompts(self, client, db):
        user = create_user()
        login(client)
        create_saved_prompt(user.id, title="Mountain Scene", prompt="mountains")
        create_saved_prompt(user.id, title="Ocean View", prompt="ocean waves")

        resp = client.get("/api/v1/prompts?search=mountain")
        data = resp.get_json()
        assert data["total"] == 1
        assert data["prompts"][0]["title"] == "Mountain Scene"

    def test_filter_favorites(self, client, db):
        user = create_user()
        login(client)
        create_saved_prompt(user.id, title="Fav", is_favorite=True)
        create_saved_prompt(user.id, title="Not Fav", is_favorite=False)

        resp = client.get("/api/v1/prompts?favorite=true")
        data = resp.get_json()
        assert data["total"] == 1
        assert data["prompts"][0]["title"] == "Fav"

    def test_filter_by_tag(self, client, db):
        user = create_user()
        login(client)
        create_saved_prompt(user.id, title="A", tags=["sunset", "photo"])
        create_saved_prompt(user.id, title="B", tags=["portrait"])

        resp = client.get("/api/v1/prompts?tag=sunset")
        data = resp.get_json()
        assert data["total"] == 1

    def test_sort_oldest(self, client, db):
        user = create_user()
        login(client)
        p1 = create_saved_prompt(user.id, title="First")
        p2 = create_saved_prompt(user.id, title="Second")

        resp = client.get("/api/v1/prompts?sort=oldest")
        data = resp.get_json()
        titles = [p["title"] for p in data["prompts"]]
        assert titles.index("First") < titles.index("Second")

    def test_sort_title(self, client, db):
        user = create_user()
        login(client)
        create_saved_prompt(user.id, title="Zebra")
        create_saved_prompt(user.id, title="Alpha")

        resp = client.get("/api/v1/prompts?sort=title")
        data = resp.get_json()
        titles = [p["title"] for p in data["prompts"]]
        assert titles.index("Alpha") < titles.index("Zebra")

    def test_pagination(self, client, db):
        user = create_user()
        login(client)
        for i in range(5):
            create_saved_prompt(user.id, title=f"Prompt {i}")

        resp = client.get("/api/v1/prompts?page=1&per_page=2")
        data = resp.get_json()
        assert len(data["prompts"]) == 2
        assert data["total"] == 5
        assert data["has_next"] is True

    def test_ownership_isolation(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")

        create_saved_prompt(user1.id, title="User1 Prompt")
        create_saved_prompt(user2.id, title="User2 Prompt")

        login(client, email="u1@x.com")
        resp = client.get("/api/v1/prompts").get_json()
        assert resp["total"] == 1
        assert resp["prompts"][0]["title"] == "User1 Prompt"

    def test_owner_cannot_access_others_prompt(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        sp = create_saved_prompt(user2.id, title="Secret")

        login(client, email="u1@x.com")
        resp = client.get(f"/api/v1/prompts/{sp.id}")
        assert resp.status_code == 404

    def test_owner_cannot_delete_others_prompt(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        sp = create_saved_prompt(user2.id)

        login(client, email="u1@x.com")
        resp = client.delete(f"/api/v1/prompts/{sp.id}")
        assert resp.status_code == 404
        assert SavedPrompt.query.get(sp.id) is not None


# ============================================================
# FAVORITE PROMPTS TESTS
# ============================================================

class TestFavoritePrompts:
    """Test favorite toggle on prompts."""

    def test_toggle_favorite(self, client, db):
        user = create_user()
        login(client)
        sp = create_saved_prompt(user.id, is_favorite=False)

        resp = client.post(f"/api/v1/prompts/{sp.id}/favorite")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_favorite"] is True

        resp = client.post(f"/api/v1/prompts/{sp.id}/favorite")
        assert resp.status_code == 200
        assert resp.get_json()["is_favorite"] is False

    def test_favorite_nonexistent(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/prompts/99999/favorite")
        assert resp.status_code == 404

    def test_favorite_requires_auth(self, client):
        resp = client.post("/api/v1/prompts/1/favorite")
        assert resp.status_code == 302


# ============================================================
# DUPLICATE PROMPT TESTS
# ============================================================

class TestDuplicatePrompt:
    """Test duplicating prompts."""

    def test_duplicate(self, client, db):
        user = create_user()
        login(client)
        sp = create_saved_prompt(user.id, title="Original", tags=["tag1"])

        resp = client.post(f"/api/v1/prompts/{sp.id}/duplicate")
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["title"] == "Original (copy)"
        assert data["prompt"] == sp.prompt
        assert data["is_favorite"] is False
        assert data["id"] != sp.id

    def test_duplicate_nonexistent(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/prompts/99999/duplicate")
        assert resp.status_code == 404

    def test_duplicate_preserves_tags(self, client, db):
        user = create_user()
        login(client)
        sp = create_saved_prompt(user.id, tags=["a", "b", "c"])
        resp = client.post(f"/api/v1/prompts/{sp.id}/duplicate")
        data = resp.get_json()
        assert set(data["tags"]) == {"a", "b", "c"}


# ============================================================
# RECENT PROMPTS TESTS
# ============================================================

class TestRecentPrompts:
    """Test recent prompts from generation history."""

    def test_recent_prompts(self, client, db):
        user = create_user()
        login(client)
        create_generation(user.id, prompt="First prompt")
        create_generation(user.id, prompt="Second prompt")
        create_generation(user.id, prompt="Third prompt")

        resp = client.get("/api/v1/prompts/recent")
        data = resp.get_json()
        assert len(data["prompts"]) == 3
        # Should be in reverse chronological order
        assert data["prompts"][0]["prompt"] == "Third prompt"

    def test_recent_deduplicates(self, client, db):
        user = create_user()
        login(client)
        create_generation(user.id, prompt="Same prompt")
        create_generation(user.id, prompt="Same prompt")
        create_generation(user.id, prompt="Different prompt")

        resp = client.get("/api/v1/prompts/recent")
        data = resp.get_json()
        assert len(data["prompts"]) == 2

    def test_recent_limit(self, client, db):
        user = create_user()
        login(client)
        for i in range(5):
            create_generation(user.id, prompt=f"Prompt {i}")

        resp = client.get("/api/v1/prompts/recent?limit=3")
        data = resp.get_json()
        assert len(data["prompts"]) == 3

    def test_recent_empty(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/prompts/recent")
        data = resp.get_json()
        assert len(data["prompts"]) == 0

    def test_recent_includes_style(self, client, db):
        user = create_user()
        login(client)
        create_generation(user.id, prompt="Styled", style="anime")

        resp = client.get("/api/v1/prompts/recent")
        data = resp.get_json()
        assert data["prompts"][0]["style"] == "anime"

    def test_recent_requires_auth(self, client):
        resp = client.get("/api/v1/prompts/recent")
        assert resp.status_code == 302


# ============================================================
# PROMPT TEMPLATES TESTS
# ============================================================

class TestPromptTemplates:
    """Test built-in prompt templates."""

    def test_list_templates(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/prompts/templates")
        data = resp.get_json()
        assert len(data["templates"]) == len(BUILTIN_TEMPLATES)
        assert len(data["templates"]) > 0

    def test_templates_have_required_fields(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/prompts/templates").get_json()
        for t in resp["templates"]:
            assert "id" in t
            assert "title" in t
            assert "prompt" in t
            assert "tags" in t

    def test_builtin_template_categories(self):
        """Verify all expected template categories exist."""
        ids = [t["id"] for t in BUILTIN_TEMPLATES]
        expected = ["portrait", "product", "landscape", "architecture",
                    "character", "poster", "cinematic", "fantasy", "sci_fi", "thumbnail"]
        for exp in expected:
            assert exp in ids, f"Missing template: {exp}"

    def test_templates_require_auth(self, client):
        resp = client.get("/api/v1/prompts/templates")
        assert resp.status_code == 302


# ============================================================
# NEGATIVE PROMPT TESTS
# ============================================================

class TestNegativePrompt:
    """Test negative prompt handling."""

    def test_negative_prompt_saved_with_generation(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/generate",
                          data=json.dumps({
                              "prompt": "A sunset",
                              "negative_prompt": "blurry, low quality",
                          }),
                          content_type="application/json")
        assert resp.status_code == 200
        gen = Generation.query.get(resp.get_json()["generation"]["id"])
        assert gen.negative_prompt == "blurry, low quality"

    def test_negative_prompt_optional(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/generate",
                          data=json.dumps({"prompt": "A sunset"}),
                          content_type="application/json")
        assert resp.status_code == 200
        gen = Generation.query.get(resp.get_json()["generation"]["id"])
        assert gen.negative_prompt is None

    def test_negative_prompt_saved_with_library_prompt(self, client, db):
        user = create_user()
        login(client)
        sp = create_saved_prompt(user.id, negative_prompt="ugly, deformed")
        resp = client.get(f"/api/v1/prompts/{sp.id}")
        data = resp.get_json()
        assert data["negative_prompt"] == "ugly, deformed"


# ============================================================
# SEED TESTS
# ============================================================

class TestSeed:
    """Test seed handling and randomization."""

    def test_seed_persisted_in_generation(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/generate",
                          data=json.dumps({"prompt": "A sunset", "seed": 42}),
                          content_type="application/json")
        assert resp.status_code == 200
        gen = Generation.query.get(resp.get_json()["generation"]["id"])
        assert gen.parameters["seed"] == 42

    def test_seed_returned_in_image(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/generate",
                          data=json.dumps({"prompt": "A sunset", "seed": 42}),
                          content_type="application/json")
        data = resp.get_json()
        assert data["images"][0]["seed"] == 42

    def test_random_seed_endpoint(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/prompts/random-seed")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "seed" in data
        assert isinstance(data["seed"], int)
        assert 0 <= data["seed"] <= 2147483647

    def test_random_seed_requires_auth(self, client):
        resp = client.get("/api/v1/prompts/random-seed")
        assert resp.status_code == 302

    def test_seed_optional(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/generate",
                          data=json.dumps({"prompt": "A sunset"}),
                          content_type="application/json")
        assert resp.status_code == 200


# ============================================================
# PROVIDER CAPABILITIES TESTS
# ============================================================

class TestProviderCapabilities:
    """Test provider capabilities endpoint."""

    def test_capabilities_endpoint(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/prompts/capabilities")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "capabilities" in data
        assert "seed" in data["capabilities"]
        assert "negative_prompt" in data["capabilities"]

    def test_capabilities_unknown_provider(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/prompts/capabilities?provider=nonexistent")
        assert resp.status_code == 200
        data = resp.get_json()
        # Falls back to stub
        assert data["provider"] == "stub"

    def test_capabilities_requires_auth(self, client):
        resp = client.get("/api/v1/prompts/capabilities")
        assert resp.status_code == 302


# ============================================================
# UNSUPPORTED FEATURE BEHAVIOR TESTS
# ============================================================

class TestUnsupportedFeatures:
    """Test that unsupported features are handled gracefully."""

    def test_invalid_style_ignored(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/generate",
                          data=json.dumps({"prompt": "A sunset", "style": "nonexistent"}),
                          content_type="application/json")
        # Should still generate (style is not validated strictly)
        assert resp.status_code == 200

    def test_invalid_seed_ignored(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/generate",
                          data=json.dumps({"prompt": "A sunset", "seed": "not_a_number"}),
                          content_type="application/json")
        # Invalid seed should be treated as None
        assert resp.status_code == 200

    def test_negative_prompt_with_unsupporting_provider(self, client, db):
        """Negative prompt should be passed even if provider doesn't use it."""
        create_user()
        login(client)
        resp = client.post("/api/v1/generate",
                          data=json.dumps({
                              "prompt": "A sunset",
                              "negative_prompt": "blurry",
                          }),
                          content_type="application/json")
        assert resp.status_code == 200

    def test_empty_tags_list(self, client, db):
        user = create_user()
        login(client)
        sp = create_saved_prompt(user.id, tags=[])
        resp = client.get(f"/api/v1/prompts/{sp.id}")
        assert resp.get_json()["tags"] == []

    def test_large_tags_list(self, client, db):
        user = create_user()
        login(client)
        tags = [f"tag{i}" for i in range(50)]
        resp = client.post("/api/v1/prompts",
                          data=json.dumps({
                              "title": "Many Tags",
                              "prompt": "test",
                              "tags": tags,
                          }),
                          content_type="application/json")
        assert resp.status_code == 201
        assert len(resp.get_json()["tags"]) == 50


# ============================================================
# EDGE CASES
# ============================================================

class TestEdgeCases:
    """Various edge cases and boundary conditions."""

    def test_create_prompt_title_max_length(self, client, db):
        create_user()
        login(client)
        long_title = "x" * 256
        resp = client.post("/api/v1/prompts",
                          data=json.dumps({"title": long_title, "prompt": "test"}),
                          content_type="application/json")
        assert resp.status_code == 400

    def test_create_prompt_title_exactly_255(self, client, db):
        create_user()
        login(client)
        title = "x" * 255
        resp = client.post("/api/v1/prompts",
                          data=json.dumps({"title": title, "prompt": "test"}),
                          content_type="application/json")
        assert resp.status_code == 201

    def test_update_empty_title_rejected(self, client, db):
        user = create_user()
        login(client)
        sp = create_saved_prompt(user.id)
        resp = client.put(f"/api/v1/prompts/{sp.id}",
                         data=json.dumps({"title": ""}),
                         content_type="application/json")
        assert resp.status_code == 400

    def test_update_empty_prompt_rejected(self, client, db):
        user = create_user()
        login(client)
        sp = create_saved_prompt(user.id)
        resp = client.put(f"/api/v1/prompts/{sp.id}",
                         data=json.dumps({"prompt": ""}),
                         content_type="application/json")
        assert resp.status_code == 400

    def test_tags_must_be_list(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/prompts",
                          data=json.dumps({
                              "title": "Test",
                              "prompt": "test",
                              "tags": "not a list",
                          }),
                          content_type="application/json")
        assert resp.status_code == 400

    def test_per_page_max_cap(self, client, db):
        user = create_user()
        login(client)
        for i in range(5):
            create_saved_prompt(user.id, title=f"P{i}")
        resp = client.get("/api/v1/prompts?per_page=999").get_json()
        assert len(resp["prompts"]) <= 100

    def test_negative_none_vs_empty_string(self, client, db):
        user = create_user()
        login(client)
        sp = create_saved_prompt(user.id, negative_prompt=None)
        resp = client.get(f"/api/v1/prompts/{sp.id}")
        assert resp.get_json()["negative_prompt"] is None

        sp2 = create_saved_prompt(user.id, negative_prompt="ugly")
        resp2 = client.get(f"/api/v1/prompts/{sp2.id}")
        assert resp2.get_json()["negative_prompt"] == "ugly"
