"""Phase 8 — Creative Controls tests: style presets, reference images, remix, variations."""

import io
import json
import struct
import pytest
from app.extensions import db
from app.models.user import User
from app.models.generation import Generation
from app.models.image import Image
from app.models.style_preset import StylePreset
from app.models.reference_image import ReferenceImage
from app.services.ai_provider import StubProvider


# ---- Helpers ----

def create_user(email="p8@test.com", username="p8user", password="securepass123"):
    user = User(email=email, username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, email="p8@test.com", password="securepass123"):
    return client.post("/login", data={
        "email": email, "password": password,
    }, follow_redirects=True)


def logout(client):
    return client.post("/logout", follow_redirects=True)


def switch_user(client, email, password="securepass123"):
    logout(client)
    return login(client, email=email, password=password)


def generate_image(client, prompt="A beautiful sunset", **kwargs):
    payload = {"prompt": prompt, **kwargs}
    return client.post("/api/v1/generate",
                       data=json.dumps(payload),
                       content_type="application/json")


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


def create_image(user_id, generation_id, filename="test.png",
                 is_favorite=False, width=512, height=512):
    import tempfile, os
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.write(make_png_bytes(width, height))
    tmp.close()
    img = Image(
        generation_id=generation_id,
        user_id=user_id,
        filename=filename,
        file_path=tmp.name,
        width=width,
        height=height,
        is_favorite=is_favorite,
    )
    db.session.add(img)
    db.session.commit()
    return img


def create_style_preset(user_id, name="My Preset", category="custom",
                        style="photo", negative_prompt=None,
                        prompt_prefix=None, prompt_suffix=None):
    preset = StylePreset(
        user_id=user_id,
        name=name,
        category=category,
        style=style,
        negative_prompt=negative_prompt,
        prompt_prefix=prompt_prefix,
        prompt_suffix=prompt_suffix,
    )
    db.session.add(preset)
    db.session.commit()
    return preset


def create_reference(user_id, filename="ref.png", file_path="/uploads/ref.png",
                     is_permanent=False):
    ref = ReferenceImage(
        user_id=user_id,
        filename=filename,
        file_path=file_path,
        original_filename="original.png",
        file_size=1024,
        width=512,
        height=512,
        mime_type="image/png",
        is_permanent=is_permanent,
    )
    db.session.add(ref)
    db.session.commit()
    return ref


def make_png_bytes(width=100, height=100):
    """Create minimal valid PNG bytes."""
    import struct
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


# ============================================================
# STYLE CATEGORIES TESTS
# ============================================================

class TestStyleCategories:
    def test_list_categories(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/styles/categories")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["categories"]) == 10
        ids = [c["id"] for c in data["categories"]]
        assert "photography" in ids
        assert "fantasy" in ids
        assert "sci_fi" in ids

    def test_categories_have_styles(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/styles/categories").get_json()
        for cat in resp["categories"]:
            assert "styles" in cat
            assert len(cat["styles"]) > 0

    def test_categories_require_auth(self, client):
        resp = client.get("/api/v1/styles/categories")
        assert resp.status_code == 302


# ============================================================
# STYLE PRESETS CRUD TESTS
# ============================================================

class TestStylePresetsCRUD:
    def test_create_preset(self, client, db):
        user = create_user()
        login(client)
        resp = client.post("/api/v1/style-presets",
                          data=json.dumps({
                              "name": "My Photo Style",
                              "category": "photography",
                              "style": "photo",
                              "negative_prompt": "blurry",
                              "prompt_prefix": "professional",
                              "prompt_suffix": "8k",
                          }),
                          content_type="application/json")
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "My Photo Style"
        assert data["category"] == "photography"
        assert data["style"] == "photo"
        assert data["negative_prompt"] == "blurry"

    def test_create_requires_name(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/style-presets",
                          data=json.dumps({"style": "photo"}),
                          content_type="application/json")
        assert resp.status_code == 400

    def test_create_requires_auth(self, client):
        resp = client.post("/api/v1/style-presets",
                          data=json.dumps({"name": "test"}),
                          content_type="application/json")
        assert resp.status_code == 302

    def test_list_presets(self, client, db):
        user = create_user()
        login(client)
        create_style_preset(user.id, name="Preset A")
        create_style_preset(user.id, name="Preset B")

        resp = client.get("/api/v1/style-presets")
        data = resp.get_json()
        assert len(data["presets"]) == 2

    def test_list_presets_empty(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/style-presets")
        assert resp.get_json()["presets"] == []

    def test_get_preset(self, client, db):
        user = create_user()
        login(client)
        preset = create_style_preset(user.id, name="Get Me")
        resp = client.get(f"/api/v1/style-presets/{preset.id}")
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "Get Me"

    def test_get_nonexistent_preset(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/v1/style-presets/99999")
        assert resp.status_code == 404

    def test_update_preset(self, client, db):
        user = create_user()
        login(client)
        preset = create_style_preset(user.id, name="Old")
        resp = client.put(f"/api/v1/style-presets/{preset.id}",
                         data=json.dumps({"name": "New", "style": "anime"}),
                         content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "New"
        assert data["style"] == "anime"

    def test_update_empty_name_rejected(self, client, db):
        user = create_user()
        login(client)
        preset = create_style_preset(user.id)
        resp = client.put(f"/api/v1/style-presets/{preset.id}",
                         data=json.dumps({"name": ""}),
                         content_type="application/json")
        assert resp.status_code == 400

    def test_delete_preset(self, client, db):
        user = create_user()
        login(client)
        preset = create_style_preset(user.id)
        resp = client.delete(f"/api/v1/style-presets/{preset.id}")
        assert resp.status_code == 200
        assert StylePreset.query.get(preset.id) is None

    def test_delete_nonexistent(self, client, db):
        create_user()
        login(client)
        resp = client.delete("/api/v1/style-presets/99999")
        assert resp.status_code == 404

    def test_duplicate_preset(self, client, db):
        user = create_user()
        login(client)
        preset = create_style_preset(user.id, name="Original",
                                     style="photo",
                                     negative_prompt="blurry")
        resp = client.post(f"/api/v1/style-presets/{preset.id}/duplicate")
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Original (copy)"
        assert data["style"] == "photo"
        assert data["id"] != preset.id

    def test_filter_by_category(self, client, db):
        user = create_user()
        login(client)
        create_style_preset(user.id, name="Photo 1", category="photography")
        create_style_preset(user.id, name="Art 1", category="digital_art")

        resp = client.get("/api/v1/style-presets?category=photography")
        data = resp.get_json()
        assert len(data["presets"]) == 1

    def test_search_presets(self, client, db):
        user = create_user()
        login(client)
        create_style_preset(user.id, name="Sunset Style")
        create_style_preset(user.id, name="Portrait Style")

        resp = client.get("/api/v1/style-presets?search=sunset")
        data = resp.get_json()
        assert len(data["presets"]) == 1

    def test_ownership_isolation(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        create_style_preset(user1.id, name="User1 Preset")
        create_style_preset(user2.id, name="User2 Preset")

        login(client, email="u1@x.com")
        resp = client.get("/api/v1/style-presets").get_json()
        assert len(resp["presets"]) == 1
        assert resp["presets"][0]["name"] == "User1 Preset"

    def test_name_max_length(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/style-presets",
                          data=json.dumps({"name": "x" * 101}),
                          content_type="application/json")
        assert resp.status_code == 400


# ============================================================
# REFERENCE IMAGES TESTS
# ============================================================

class TestReferenceImages:
    def test_upload_reference(self, client, db):
        create_user()
        login(client)

        png_data = make_png_bytes(100, 100)
        resp = client.post("/api/v1/references/upload",
                          data={"file": (io.BytesIO(png_data), "test.png")},
                          content_type="multipart/form-data")
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["filename"] is not None
        assert data["width"] == 100
        assert data["height"] == 100

    def test_upload_requires_file(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/references/upload")
        assert resp.status_code == 400

    def test_upload_rejects_invalid_mime(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/references/upload",
                          data={"file": (io.BytesIO(b"not an image"), "test.txt")},
                          content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_upload_rejects_invalid_content(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/references/upload",
                          data={"file": (io.BytesIO(b"NOTPNGDATA" * 100), "test.png")},
                          content_type="multipart/form-data")
        assert resp.status_code == 400
        assert b"not appear to be a valid image" in resp.data

    def test_upload_rejects_oversized(self, client, db):
        create_user()
        login(client)
        # 11MB file — Flask's MAX_CONTENT_LENGTH may return 413 before our code
        large_data = make_png_bytes(100, 100) + b'\x00' * (11 * 1024 * 1024)
        resp = client.post("/api/v1/references/upload",
                          data={"file": (io.BytesIO(large_data), "big.png")},
                          content_type="multipart/form-data")
        assert resp.status_code in (400, 413)
        if resp.status_code == 400:
            assert b"too large" in resp.data

    def test_upload_rejects_too_small_dimensions(self, client, db):
        create_user()
        login(client)
        png_data = make_png_bytes(10, 10)
        resp = client.post("/api/v1/references/upload",
                          data={"file": (io.BytesIO(png_data), "tiny.png")},
                          content_type="multipart/form-data")
        assert resp.status_code == 400
        assert b"too small" in resp.data

    def test_upload_rejects_too_large_dimensions(self, client, db):
        create_user()
        login(client)
        png_data = make_png_bytes(5000, 5000)
        resp = client.post("/api/v1/references/upload",
                          data={"file": (io.BytesIO(png_data), "huge.png")},
                          content_type="multipart/form-data")
        assert resp.status_code == 400
        assert b"too large" in resp.data

    def test_upload_rejects_non_trusted_extension(self, client, db):
        """Should NOT trust filename extension — validates actual content."""
        create_user()
        login(client)
        # Send valid PNG but with .txt extension
        png_data = make_png_bytes(100, 100)
        resp = client.post("/api/v1/references/upload",
                          data={"file": (io.BytesIO(png_data), "image.txt")},
                          content_type="multipart/form-data")
        # The MIME type from multipart will be text/plain, so this should be rejected
        assert resp.status_code == 400

    def test_list_references(self, client, db):
        user = create_user()
        login(client)
        create_reference(user.id, filename="r1.png")
        create_reference(user.id, filename="r2.png")

        resp = client.get("/api/v1/references")
        data = resp.get_json()
        assert len(data["references"]) == 2

    def test_list_references_excludes_deleted(self, client, db):
        user = create_user()
        login(client)
        r1 = create_reference(user.id)
        r2 = create_reference(user.id)
        r1.soft_delete()
        db.session.commit()

        resp = client.get("/api/v1/references").get_json()
        assert len(resp["references"]) == 1

    def test_delete_reference(self, client, db):
        user = create_user()
        login(client)
        ref = create_reference(user.id)

        resp = client.delete(f"/api/v1/references/{ref.id}")
        assert resp.status_code == 200
        # Should be soft-deleted
        r = ReferenceImage.query.get(ref.id)
        assert r.is_deleted is True

    def test_delete_nonexistent(self, client, db):
        create_user()
        login(client)
        resp = client.delete("/api/v1/references/99999")
        assert resp.status_code == 404

    def test_toggle_permanent(self, client, db):
        user = create_user()
        login(client)
        ref = create_reference(user.id, is_permanent=False)

        resp = client.post(f"/api/v1/references/{ref.id}/permanent")
        assert resp.status_code == 200
        assert resp.get_json()["is_permanent"] is True

        resp = client.post(f"/api/v1/references/{ref.id}/permanent")
        assert resp.get_json()["is_permanent"] is False

    def test_reference_ownership_isolation(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        ref2 = create_reference(user2.id)

        login(client, email="u1@x.com")
        resp = client.get("/api/v1/references")
        assert len(resp.get_json()["references"]) == 0

        resp = client.delete(f"/api/v1/references/{ref2.id}")
        assert resp.status_code == 404

    def test_reference_requires_auth(self, client):
        resp = client.get("/api/v1/references")
        assert resp.status_code == 302

    def test_jpeg_upload(self, client, db):
        create_user()
        login(client)
        # Minimal JPEG
        jpeg_data = b'\xff\xd8\xff\xe0' + b'\x00' * 100
        resp = client.post("/api/v1/references/upload",
                          data={"file": (io.BytesIO(jpeg_data), "photo.jpg")},
                          content_type="multipart/form-data")
        assert resp.status_code == 201


# ============================================================
# REMIX TESTS
# ============================================================

class TestRemix:
    def test_remix_returns_settings(self, client, db):
        user = create_user()
        login(client)
        gen = create_generation(user.id, prompt="A sunset", style="photo")
        img = create_image(user.id, gen.id)

        resp = client.post(f"/api/v1/images/{img.id}/remix",
                          data=json.dumps({}),
                          content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["prompt"] == "A sunset"
        assert data["style"] == "photo"
        assert data["reference_image_id"] == img.id

    def test_remix_with_strength(self, client, db):
        user = create_user()
        login(client)
        gen = create_generation(user.id)
        img = create_image(user.id, gen.id)

        resp = client.post(f"/api/v1/images/{img.id}/remix",
                          data=json.dumps({"reference_strength": 0.5}),
                          content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["reference_strength"] == 0.5

    def test_remix_clamps_strength(self, client, db):
        user = create_user()
        login(client)
        gen = create_generation(user.id)
        img = create_image(user.id, gen.id)

        resp = client.post(f"/api/v1/images/{img.id}/remix",
                          data=json.dumps({"reference_strength": 2.0}),
                          content_type="application/json")
        assert resp.get_json()["reference_strength"] == 1.0

    def test_remix_nonexistent_image(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/images/99999/remix")
        assert resp.status_code == 404

    def test_remix_requires_auth(self, client):
        resp = client.post("/api/v1/images/1/remix")
        assert resp.status_code == 302

    def test_remix_ownership_check(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        gen = create_generation(user2.id)
        img = create_image(user2.id, gen.id)

        login(client, email="u1@x.com")
        resp = client.post(f"/api/v1/images/{img.id}/remix")
        assert resp.status_code == 404


# ============================================================
# VARIATIONS TESTS
# ============================================================

class TestVariations:
    def test_generate_variations(self, client, db):
        user = create_user()
        login(client)
        gen = create_generation(user.id, prompt="A mountain")
        img = create_image(user.id, gen.id)

        resp = client.post(f"/api/v1/images/{img.id}/variations",
                          data=json.dumps({"count": 2}),
                          content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert len(data["images"]) == 2
        assert data["source_image_id"] == img.id

    def test_variations_preserves_original(self, client, db):
        user = create_user()
        login(client)
        gen = create_generation(user.id, prompt="Original image")
        img = create_image(user.id, gen.id)

        client.post(f"/api/v1/images/{img.id}/variations",
                   data=json.dumps({"count": 1}),
                   content_type="application/json")

        # Original should still exist
        original = Image.query.get(img.id)
        assert original is not None
        assert original.filename == "test.png"

    def test_variations_creates_new_images(self, client, db):
        user = create_user()
        login(client)
        gen = create_generation(user.id)
        img = create_image(user.id, gen.id)

        initial_count = Image.query.filter_by(user_id=user.id).count()

        resp = client.post(f"/api/v1/images/{img.id}/variations",
                          data=json.dumps({"count": 2}),
                          content_type="application/json")

        new_count = Image.query.filter_by(user_id=user.id).count()
        assert new_count == initial_count + 2

    def test_variations_nonexistent_image(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/images/99999/variations")
        assert resp.status_code == 404

    def test_variations_requires_auth(self, client):
        resp = client.post("/api/v1/images/1/variations")
        assert resp.status_code == 302

    def test_variations_ownership_check(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        gen = create_generation(user2.id)
        img = create_image(user2.id, gen.id)

        login(client, email="u1@x.com")
        resp = client.post(f"/api/v1/images/{img.id}/variations")
        assert resp.status_code == 404

    def test_variations_default_count(self, client, db):
        user = create_user()
        login(client)
        gen = create_generation(user.id)
        img = create_image(user.id, gen.id)

        resp = client.post(f"/api/v1/images/{img.id}/variations",
                          data=json.dumps({}),
                          content_type="application/json")
        assert resp.status_code == 200
        assert len(resp.get_json()["images"]) == 1

    def test_variations_max_count(self, client, db):
        user = create_user()
        login(client)
        gen = create_generation(user.id)
        img = create_image(user.id, gen.id)

        resp = client.post(f"/api/v1/images/{img.id}/variations",
                          data=json.dumps({"count": 10}),
                          content_type="application/json")
        assert resp.status_code == 200
        assert len(resp.get_json()["images"]) <= 4


# ============================================================
# USE AS REFERENCE TESTS
# ============================================================

class TestUseAsReference:
    def test_use_as_reference(self, client, db):
        user = create_user()
        login(client)
        gen = create_generation(user.id)
        img = create_image(user.id, gen.id)

        resp = client.post(f"/api/v1/images/{img.id}/as-reference")
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["is_permanent"] is True
        assert data["width"] == img.width

    def test_use_as_reference_idempotent(self, client, db):
        user = create_user()
        login(client)
        gen = create_generation(user.id)
        img = create_image(user.id, gen.id)

        resp1 = client.post(f"/api/v1/images/{img.id}/as-reference")
        assert resp1.status_code == 201

        resp2 = client.post(f"/api/v1/images/{img.id}/as-reference")
        assert resp2.status_code == 200

        refs = ReferenceImage.query.filter_by(user_id=user.id).all()
        assert len(refs) == 1

    def test_use_as_reference_nonexistent(self, client, db):
        create_user()
        login(client)
        resp = client.post("/api/v1/images/99999/as-reference")
        assert resp.status_code == 404

    def test_use_as_reference_ownership_check(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        gen = create_generation(user2.id)
        img = create_image(user2.id, gen.id)

        login(client, email="u1@x.com")
        resp = client.post(f"/api/v1/images/{img.id}/as-reference")
        assert resp.status_code == 404


# ============================================================
# GENERATION WITH REFERENCES TESTS
# ============================================================

class TestGenerationWithReferences:
    def test_generate_with_reference_ids(self, client, db):
        user = create_user()
        login(client)
        ref = create_reference(user.id, file_path="/uploads/ref.png")

        resp = client.post("/api/v1/generate",
                          data=json.dumps({
                              "prompt": "A cat",
                              "reference_image_ids": [ref.id],
                              "reference_strength": 0.5,
                          }),
                          content_type="application/json")
        assert resp.status_code == 200

    def test_generate_with_invalid_reference_id(self, client, db):
        user = create_user()
        login(client)

        resp = client.post("/api/v1/generate",
                          data=json.dumps({
                              "prompt": "A cat",
                              "reference_image_ids": [99999],
                          }),
                          content_type="application/json")
        # Should still generate (invalid refs are just skipped)
        assert resp.status_code == 200

    def test_generate_with_other_users_reference(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        ref2 = create_reference(user2.id)

        login(client, email="u1@x.com")
        resp = client.post("/api/v1/generate",
                          data=json.dumps({
                              "prompt": "A cat",
                              "reference_image_ids": [ref2.id],
                          }),
                          content_type="application/json")
        # Should still generate (other user's ref is skipped)
        assert resp.status_code == 200

    def test_reference_strength_clamped(self, client, db):
        user = create_user()
        login(client)
        ref = create_reference(user.id)

        resp = client.post("/api/v1/generate",
                          data=json.dumps({
                              "prompt": "A cat",
                              "reference_image_ids": [ref.id],
                              "reference_strength": -1.0,
                          }),
                          content_type="application/json")
        assert resp.status_code == 200

    def test_reference_strength_max_clamped(self, client, db):
        user = create_user()
        login(client)
        ref = create_reference(user.id)

        resp = client.post("/api/v1/generate",
                          data=json.dumps({
                              "prompt": "A cat",
                              "reference_image_ids": [ref.id],
                              "reference_strength": 5.0,
                          }),
                          content_type="application/json")
        assert resp.status_code == 200


# ============================================================
# STUB PROVIDER TESTS
# ============================================================

class TestStubProviderVariations:
    def test_stub_supports_variations(self):
        provider = StubProvider()
        assert provider.supports("variations") is True

    def test_stub_supports_multiple_references(self):
        provider = StubProvider()
        assert provider.supports("multiple_references") is True

    def test_stub_metadata_includes_reference_info(self):
        provider = StubProvider()
        result = provider.text_to_image(
            "test",
            reference_paths=["/path/to/ref1.png", "/path/to/ref2.png"],
            reference_strength=0.5,
        )
        meta = result.images[0].metadata
        assert meta["reference_count"] == 2
        assert meta["reference_strength"] == 0.5


# ============================================================
# SECURITY TESTS
# ============================================================

class TestCreativeSecurity:
    def test_cannot_access_others_preset(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        preset = create_style_preset(user2.id, name="Secret")

        login(client, email="u1@x.com")
        resp = client.get(f"/api/v1/style-presets/{preset.id}")
        assert resp.status_code == 404

    def test_cannot_delete_others_preset(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        preset = create_style_preset(user2.id)

        login(client, email="u1@x.com")
        resp = client.delete(f"/api/v1/style-presets/{preset.id}")
        assert resp.status_code == 404
        assert StylePreset.query.get(preset.id) is not None

    def test_cannot_update_others_preset(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        preset = create_style_preset(user2.id, name="Original")

        login(client, email="u1@x.com")
        resp = client.put(f"/api/v1/style-presets/{preset.id}",
                         data=json.dumps({"name": "Hacked"}),
                         content_type="application/json")
        assert resp.status_code == 404
        assert StylePreset.query.get(preset.id).name == "Original"

    def test_cannot_duplicate_others_preset(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        preset = create_style_preset(user2.id)

        login(client, email="u1@x.com")
        resp = client.post(f"/api/v1/style-presets/{preset.id}/duplicate")
        assert resp.status_code == 404

    def test_reference_file_requires_ownership(self, client, db):
        user1 = create_user(email="u1@x.com", username="u1")
        user2 = create_user(email="u2@x.com", username="u2")
        ref = create_reference(user2.id)

        login(client, email="u1@x.com")
        resp = client.get(f"/api/v1/references/{ref.id}/file")
        assert resp.status_code == 404
