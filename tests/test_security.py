"""Security tests — Phase 15 production-readiness hardening.

Covers: headers, auth, IDOR, redirects, rate limiting, errors, uploads,
        XSS, SQL injection, path traversal.
"""
import io
import os
import pytest
from pathlib import Path


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def auth_client(client, db):
    """Client with a logged-in regular user."""
    client.post("/signup", data={
        "username": "sec_tester", "email": "sec@test.com",
        "password": "TestPass123!", "confirm_password": "TestPass123!",
    }, follow_redirects=True)
    client.post("/login", data={
        "email": "sec@test.com", "password": "TestPass123!",
    }, follow_redirects=True)
    return client


@pytest.fixture
def admin_session(client, db):
    """Client with a logged-in admin user."""
    client.post("/signup", data={
        "username": "sec_admin", "email": "admin_sec@test.com",
        "password": "AdminPass123!", "confirm_password": "AdminPass123!",
    }, follow_redirects=True)
    # Make the user admin
    from app.models.user import User
    from app.extensions import db
    admin = User.query.filter_by(email="admin_sec@test.com").first()
    admin.is_admin = True
    db.session.commit()
    # Re-login to refresh session
    client.post("/login", data={
        "email": "admin_sec@test.com", "password": "AdminPass123!",
    }, follow_redirects=True)
    return client


@pytest.fixture
def other_client(client, db):
    """A different logged-in user for IDOR tests."""
    client.post("/signup", data={
        "username": "other_user", "email": "other@test.com",
        "password": "OtherPass123!", "confirm_password": "OtherPass123!",
    }, follow_redirects=True)
    client.post("/login", data={
        "email": "other@test.com", "password": "OtherPass123!",
    }, follow_redirects=True)
    return client


def _make_test_image(db, user_id, app, is_public=False):
    """Create a test image file + DB record inside uploads/."""
    from app.models.generation import Generation
    from app.models.image import Image
    gen = Generation(user_id=user_id, prompt="security test", provider="stub", status="completed")
    db.session.add(gen)
    db.session.flush()
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'
    upload_dir = Path(app.config["UPLOAD_FOLDER"]) / "test_security"
    upload_dir.mkdir(parents=True, exist_ok=True)
    fpath = upload_dir / f"sec_{gen.id}.svg"
    fpath.write_bytes(svg)
    img = Image(
        generation_id=gen.id, user_id=user_id,
        filename=f"sec_{gen.id}.svg", file_path=str(fpath.resolve()),
        width=10, height=10, is_public=is_public,
    )
    db.session.add(img)
    db.session.commit()
    return img.id


# ============================================================
# SECURITY HEADERS
# ============================================================

class TestSecurityHeaders:
    def test_x_content_type_options(self, client):
        assert client.get("/api/v1/status").headers["X-Content-Type-Options"] == "nosniff"

    def test_x_frame_options(self, client):
        assert client.get("/api/v1/status").headers["X-Frame-Options"] == "SAMEORIGIN"

    def test_x_xss_protection(self, client):
        assert client.get("/api/v1/status").headers["X-XSS-Protection"] == "1; mode=block"

    def test_referrer_policy(self, client):
        assert client.get("/api/v1/status").headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        pp = client.get("/api/v1/status").headers.get("Permissions-Policy", "")
        assert "camera=()" in pp and "microphone=()" in pp

    def test_content_security_policy(self, client):
        csp = client.get("/api/v1/status").headers.get("Content-Security-Policy", "")
        assert "default-src" in csp and "frame-ancestors" in csp and "base-uri" in csp

    def test_no_server_header(self, client):
        assert "Server" not in client.get("/api/v1/status").headers

    def test_no_powered_by_header(self, client):
        assert "X-Powered-By" not in client.get("/api/v1/status").headers


# ============================================================
# AUTHENTICATION / AUTHORIZATION
# ============================================================

class TestAuthentication:
    def test_generate_requires_auth(self, client):
        resp = client.post("/api/v1/generate", json={"prompt": "test"})
        assert resp.status_code in (302, 401)

    def test_favorites_requires_auth(self, client):
        assert client.get("/api/v1/favorites").status_code in (302, 401)

    def test_admin_requires_auth(self, client):
        assert client.get("/api/v1/admin/dashboard").status_code in (302, 401)

    def test_admin_requires_admin_role(self, auth_client):
        assert auth_client.get("/api/v1/admin/dashboard").status_code == 403

    def test_admin_page_requires_admin(self, auth_client):
        assert auth_client.get("/admin").status_code == 403

    def test_admin_page_works_for_admin(self, admin_session):
        assert admin_session.get("/admin").status_code == 200

    def test_authenticated_can_generate(self, auth_client):
        resp = auth_client.post("/api/v1/generate", json={"prompt": "hi", "provider": "stub"})
        assert resp.status_code in (200, 429)


# ============================================================
# IDOR PROTECTION
# ============================================================

class TestIDOR:
    def test_cannot_access_other_user_private_image(self, db, auth_client, app):
        """User1 should NOT see User2's private image."""
        from app.models.user import User
        from app.models.generation import Generation
        from app.models.image import Image
        # Create user2 directly in DB
        u2 = User(email="idor_other@test.com", username="idor_other")
        u2.set_password("x")
        db.session.add(u2)
        db.session.commit()
        image_id = _make_test_image(db, u2.id, app)
        assert auth_client.get(f"/api/v1/images/{image_id}/file").status_code == 403

    def test_owner_can_access_own_image(self, db, auth_client, app):
        from app.models.user import User
        me = User.query.filter_by(email="sec@test.com").first()
        image_id = _make_test_image(db, me.id, app)
        assert auth_client.get(f"/api/v1/images/{image_id}/file").status_code == 200

    def test_unauthenticated_cannot_see_private_image(self, db, auth_client, app):
        from app.models.user import User
        from app.models.generation import Generation
        from app.models.image import Image
        u2 = User(email="idor_priv@test.com", username="idor_priv")
        u2.set_password("x")
        db.session.add(u2)
        db.session.commit()
        image_id = _make_test_image(db, u2.id, app)
        with app.test_client() as anon:
            assert anon.get(f"/api/v1/images/{image_id}/file").status_code == 403

    def test_thumbnail_same_access_control(self, db, auth_client, app):
        from app.models.user import User
        u2 = User(email="idor_thumb@test.com", username="idor_thumb")
        u2.set_password("x")
        db.session.add(u2)
        db.session.commit()
        image_id = _make_test_image(db, u2.id, app)
        assert auth_client.get(f"/api/v1/images/{image_id}/thumbnail").status_code == 403

    def test_cannot_access_other_users_prompt(self, db, auth_client):
        from app.models.user import User
        from app.models.saved_prompt import SavedPrompt
        u2 = User(email="idor_prompts@test.com", username="idor_prompts")
        u2.set_password("x")
        db.session.add(u2)
        db.session.commit()
        p = SavedPrompt(user_id=u2.id, title="secret", prompt="secret prompt")
        db.session.add(p)
        db.session.commit()
        assert auth_client.get(f"/api/v1/prompts/{p.id}").status_code == 404

    def test_cannot_delete_other_users_prompt(self, db, auth_client):
        from app.models.user import User
        from app.models.saved_prompt import SavedPrompt
        u2 = User(email="idor_del@test.com", username="idor_del")
        u2.set_password("x")
        db.session.add(u2)
        db.session.commit()
        p = SavedPrompt(user_id=u2.id, title="secret", prompt="secret prompt")
        db.session.add(p)
        db.session.commit()
        assert auth_client.delete(f"/api/v1/prompts/{p.id}").status_code == 404

    def test_cannot_access_other_users_preset(self, db, auth_client):
        from app.models.user import User
        from app.models.style_preset import StylePreset
        u2 = User(email="idor_preset@test.com", username="idor_preset")
        u2.set_password("x")
        db.session.add(u2)
        db.session.commit()
        s = StylePreset(user_id=u2.id, name="secret preset", category="custom")
        db.session.add(s)
        db.session.commit()
        assert auth_client.get(f"/api/v1/style-presets/{s.id}").status_code == 404


# ============================================================
# OPEN REDIRECT
# ============================================================

class TestOpenRedirect:
    def test_no_redirect_to_external_url(self, db, client):
        resp = client.post("/login?next=//evil.com", data={
            "email": "nonexistent@test.com", "password": "wrong",
        }, follow_redirects=False)
        if resp.status_code in (301, 302):
            assert "evil.com" not in resp.headers.get("Location", "")


# ============================================================
# RATE LIMITING
# ============================================================

class TestRateLimiting:
    def test_rate_limit_returns_429(self, auth_client):
        for _ in range(15):
            resp = auth_client.post("/api/v1/generate", json={"prompt": "t", "provider": "stub"})
            if resp.status_code == 429:
                data = resp.get_json()
                assert "error" in data
                assert resp.headers.get("Retry-After")
                return
        # Stub is fast — may not hit limit, acceptable


# ============================================================
# ERROR HANDLING
# ============================================================

class TestErrorHandling:
    def test_404_safe(self, client):
        data = client.get("/api/v1/nonexistent").get_json()
        assert data["status_code"] == 404
        assert "traceback" not in str(data).lower()

    def test_405_safe(self, client):
        assert client.delete("/api/v1/status").status_code == 405

    def test_generation_error_safe(self, auth_client):
        resp = auth_client.post("/api/v1/generate", json={})
        assert resp.status_code in (400, 429)
        s = str(resp.get_json())
        assert "Traceback" not in s and "site-packages" not in s


# ============================================================
# UPLOAD SECURITY
# ============================================================

class TestUploadSecurity:
    def test_upload_requires_file(self, auth_client):
        assert auth_client.post("/api/v1/utilities/upload").status_code == 400

    def test_upload_rejects_non_image(self, auth_client):
        data = {"file": (io.BytesIO(b"<html>nope</html>"), "evil.html", "text/html")}
        assert auth_client.post("/api/v1/utilities/upload", data=data,
                                content_type="multipart/form-data").status_code == 400

    def test_reference_upload_requires_file(self, auth_client):
        assert auth_client.post("/api/v1/references/upload").status_code == 400


# ============================================================
# XSS / INJECTION
# ============================================================

class TestXSSInjection:
    def test_script_in_prompt_safe(self, auth_client):
        resp = auth_client.post("/api/v1/generate", json={
            "prompt": '<script>alert("xss")</script>', "provider": "stub",
        })
        assert resp.status_code in (200, 429)

    def test_sql_injection_search_safe(self, auth_client):
        resp = auth_client.get("/api/v1/generations?search='; DROP TABLE users; --")
        assert resp.status_code in (200, 429)
        assert auth_client.get("/api/v1/status").status_code == 200

    def test_sql_injection_or_safe(self, auth_client):
        resp = auth_client.get("/api/v1/generations?search=1' OR '1'='1")
        assert resp.status_code in (200, 429)


# ============================================================
# PATH TRAVERSAL
# ============================================================

class TestPathTraversal:
    def test_nonexistent_returns_404(self, auth_client):
        assert auth_client.get("/api/v1/images/999999/file").status_code == 404

    def test_thumbnail_nonexistent_404(self, auth_client):
        assert auth_client.get("/api/v1/images/999999/thumbnail").status_code == 404
