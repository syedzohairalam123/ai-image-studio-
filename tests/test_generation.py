"""Generation workflow tests."""

import json
import pytest
from app.extensions import db
from app.models.user import User
from app.models.generation import Generation
from app.models.image import Image


def create_user(email="gen@test.com", username="genuser", password="securepass123"):
    user = User(email=email, username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, email="gen@test.com", password="securepass123"):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=True)


def generate(client, prompt="A beautiful sunset", **kwargs):
    payload = {"prompt": prompt, **kwargs}
    return client.post("/api/v1/generate",
                       data=json.dumps(payload),
                       content_type="application/json")


# ---- Validation Tests ----

class TestValidation:
    def test_empty_prompt_rejected(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="")
        assert resp.status_code == 400
        assert b"required" in resp.data

    def test_whitespace_only_prompt_rejected(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="   ")
        assert resp.status_code == 400

    def test_valid_generation(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A mountain landscape")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert len(data["images"]) == 1
        assert "url" in data["images"][0]

    def test_invalid_aspect_ratio(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset", aspect_ratio="5:5")
        assert resp.status_code == 400

    def test_invalid_quality(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset", quality="super_mega")
        assert resp.status_code == 400

    def test_valid_aspect_ratio(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset", aspect_ratio="16:9")
        assert resp.status_code == 200

    def test_valid_quality(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset", quality="hd")
        assert resp.status_code == 200

    def test_count_min(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset", count=1)
        assert resp.status_code == 200

    def test_count_max(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset", count=4)
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["images"]) == 4

    def test_invalid_count(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset", count=10)
        assert resp.status_code == 400

    def test_negative_prompt(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset", negative_prompt="blurry, dark")
        assert resp.status_code == 200

    def test_seed(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset", seed=42)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["images"][0]["seed"] == 42

    def test_style(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset", style="anime")
        assert resp.status_code == 200


# ---- Authentication Tests ----

class TestGenerationAuth:
    def test_unauthenticated_rejected(self, client):
        resp = generate(client, prompt="A sunset")
        assert resp.status_code == 302  # redirect to login

    def test_authenticated_can_generate(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset")
        assert resp.status_code == 200


# ---- Database Persistence Tests ----

class TestGenerationPersistence:
    def test_generation_record_created(self, client, db):
        user = create_user()
        login(client)
        resp = generate(client, prompt="A mountain")
        data = resp.get_json()

        gen = Generation.query.get(data["generation"]["id"])
        assert gen is not None
        assert gen.user_id == user.id
        assert gen.prompt == "A mountain"
        assert gen.provider == "stub"
        assert gen.status == "completed"

    def test_image_record_created(self, client, db):
        user = create_user()
        login(client)
        resp = generate(client, prompt="A sunset")
        data = resp.get_json()

        img = Image.query.get(data["images"][0]["id"])
        assert img is not None
        assert img.user_id == user.id
        assert img.generation_id == data["generation"]["id"]

    def test_generation_metadata_saved(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset", style="anime", aspect_ratio="16:9")
        data = resp.get_json()

        gen = Generation.query.get(data["generation"]["id"])
        assert gen.parameters["style"] == "anime"
        assert gen.parameters["aspect_ratio"] == "16:9"

    def test_multiple_images_from_count(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset", count=3)
        data = resp.get_json()
        assert len(data["images"]) == 3

        images = Image.query.filter_by(
            generation_id=data["generation"]["id"]
        ).all()
        assert len(images) == 3


# ---- Download Tests ----

class TestDownload:
    def test_download_own_image(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset")
        assert resp.status_code == 200
        data = resp.get_json()
        img_id = data["images"][0]["id"]

        dl_resp = client.get(f"/api/v1/images/{img_id}/download")
        assert dl_resp.status_code == 200
        assert "image" in dl_resp.content_type or "svg" in dl_resp.content_type

    def test_download_requires_auth(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset")
        data = resp.get_json()
        img_id = data["images"][0]["id"]

        # Logout
        client.post("/logout")

        dl_resp = client.get(f"/api/v1/images/{img_id}/download")
        assert dl_resp.status_code == 302  # redirect to login

    def test_download_other_user_rejected(self, client, db):
        user1 = create_user(email="u1@x.com", username="user1")
        user2 = create_user(email="u2@x.com", username="user2")

        login(client, email="u1@x.com")
        resp = generate(client, prompt="User1 image")
        data = resp.get_json()
        img_id = data["images"][0]["id"]

        # Switch to user2
        client.post("/logout")
        login(client, email="u2@x.com")

        dl_resp = client.get(f"/api/v1/images/{img_id}/download")
        assert dl_resp.status_code == 403

    def test_download_nonexistent(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/images/99999/download")
        assert resp.status_code == 404


# ---- Image File Serving Tests ----

class TestImageServing:
    def test_serve_image_file(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset")
        data = resp.get_json()
        img_id = data["images"][0]["id"]

        file_resp = client.get(f"/api/v1/images/{img_id}/file")
        assert file_resp.status_code == 200

    def test_serve_nonexistent(self, client, db):
        create_user()  # ensure tables exist
        resp = client.get("/api/v1/images/99999/file")
        assert resp.status_code == 404


# ---- History API Tests ----

class TestGenerationHistory:
    def test_list_generations(self, client, db):
        create_user()
        login(client)

        for i in range(3):
            generate(client, prompt=f"Image {i}")

        resp = client.get("/api/v1/generations")
        data = resp.get_json()
        assert len(data["generations"]) == 3
        assert data["total"] == 3

    def test_list_requires_auth(self, client):
        resp = client.get("/api/v1/generations")
        assert resp.status_code == 302


# ---- Provider Info Tests ----

class TestProviderInfo:
    def test_list_providers(self, client):
        resp = client.get("/api/v1/providers")
        data = resp.get_json()
        assert len(data["providers"]) >= 1
        stub = next(p for p in data["providers"] if p["name"] == "stub")
        assert stub["configured"] is True


# ---- Error Handling Tests ----

class TestGenerationErrors:
    def test_invalid_provider(self, client, db):
        create_user()
        login(client)
        resp = generate(client, prompt="A sunset", provider="nonexistent")
        assert resp.status_code == 400

    def test_no_json_body(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/generate")
        assert resp.status_code == 400
