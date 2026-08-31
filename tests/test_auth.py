"""Authentication tests — covers signup, login, logout, protection, validation, security."""

import pytest
from app.extensions import db
from app.models.user import User


# ---- Helpers ----

def create_user(email="test@example.com", username="testuser", password="securepass123"):
    """Create a user directly in the DB."""
    user = User(email=email, username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def signup(client, email="new@example.com", username="newuser", password="securepass123"):
    """POST to signup."""
    return client.post("/signup", data={
        "email": email,
        "username": username,
        "password": password,
    }, follow_redirects=True)


def login(client, email="test@example.com", password="securepass123"):
    """POST to login."""
    return client.post("/login", data={
        "email": email,
        "password": password,
    }, follow_redirects=True)


# ---- Signup Tests ----

class TestSignup:
    def test_signup_page_renders(self, client):
        resp = client.get("/signup")
        assert resp.status_code == 200
        assert b"Create your account" in resp.data

    def test_valid_signup(self, client, db):
        resp = signup(client)
        assert resp.status_code == 200
        assert b"Welcome to AI Studio" in resp.data
        user = User.query.filter_by(email="new@example.com").first()
        assert user is not None
        assert user.username == "newuser"

    def test_duplicate_email_signup(self, client, db):
        create_user(email="dup@example.com", username="user1")
        resp = signup(client, email="dup@example.com", username="user2")
        assert resp.status_code == 422
        assert b"already exists" in resp.data

    def test_duplicate_username_signup(self, client, db):
        create_user(email="a@example.com", username="sameuser")
        resp = signup(client, email="b@example.com", username="sameuser")
        assert resp.status_code == 422
        assert b"already taken" in resp.data

    def test_missing_email(self, client, db):
        resp = client.post("/signup", data={"username": "u", "password": "pass1234"})
        assert resp.status_code == 422

    def test_invalid_email(self, client, db):
        resp = signup(client, email="notanemail", username="user")
        assert resp.status_code == 422
        assert b"valid email" in resp.data

    def test_short_password(self, client, db):
        resp = signup(client, email="a@b.com", username="user", password="123")
        assert resp.status_code == 422
        assert b"at least 8 characters" in resp.data

    def test_short_username(self, client, db):
        resp = signup(client, email="a@b.com", username="ab")
        assert resp.status_code == 422
        assert b"at least 3 characters" in resp.data

    def test_invalid_username_chars(self, client, db):
        resp = signup(client, email="a@b.com", username="user name!")
        assert resp.status_code == 422

    def test_signup_logs_in_user(self, client, db):
        signup(client, email="auto@example.com", username="autouser")
        resp = client.get("/api/auth/status")
        data = resp.get_json()
        assert data["authenticated"] is True
        assert data["user"]["email"] == "auto@example.com"


# ---- Login Tests ----

class TestLogin:
    def test_login_page_renders(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200
        assert b"Welcome back" in resp.data

    def test_valid_login(self, client, db):
        create_user()
        resp = login(client)
        assert resp.status_code == 200
        assert b"Welcome back, testuser" in resp.data

    def test_invalid_password(self, client, db):
        create_user()
        resp = login(client, password="wrongpassword")
        assert resp.status_code == 401
        assert b"Invalid email or password" in resp.data

    def test_nonexistent_email(self, client, db):
        resp = login(client, email="nobody@example.com")
        assert resp.status_code == 401
        assert b"Invalid email or password" in resp.data

    def test_missing_fields(self, client, db):
        resp = client.post("/login", data={})
        assert resp.status_code == 422

    def test_deactivated_user(self, client, db):
        user = create_user()
        user.is_active = False
        db.session.commit()
        resp = login(client)
        assert resp.status_code == 403
        assert b"deactivated" in resp.data

    def test_login_with_remember(self, client, db):
        create_user()
        resp = client.post("/login", data={
            "email": "test@example.com",
            "password": "securepass123",
            "remember": "on",
        }, follow_redirects=True)
        assert resp.status_code == 200


# ---- Logout Tests ----

class TestLogout:
    def test_logout(self, client, db):
        create_user()
        login(client)
        resp = client.post("/logout", follow_redirects=True)
        assert resp.status_code == 200
        # Verify logged out
        status = client.get("/api/auth/status").get_json()
        assert status["authenticated"] is False

    def test_logout_requires_auth(self, client):
        resp = client.post("/logout", follow_redirects=True)
        assert resp.status_code == 200  # redirects to login


# ---- Protected Route Tests ----

class TestProtectedRoutes:
    PROTECTED = ["/history", "/favorites", "/collections", "/prompts", "/settings", "/profile"]

    def test_unauthenticated_redirects_to_login(self, client):
        for path in self.PROTECTED:
            resp = client.get(path)
            assert resp.status_code == 302
            assert "/login" in resp.headers["Location"]

    def test_authenticated_access(self, client, db):
        create_user()
        login(client)
        for path in self.PROTECTED:
            resp = client.get(path)
            assert resp.status_code == 200, f"Failed for {path}"

    def test_generate_and_gallery_public(self, client):
        """Generate, gallery, explore, styles, editor should be public."""
        public = ["/generate", "/gallery", "/explore", "/styles", "/editor", "/"]
        for path in public:
            resp = client.get(path)
            assert resp.status_code == 200, f"Failed for {path}"


# ---- Profile Tests ----

class TestProfile:
    def test_profile_page(self, client, db):
        create_user()
        login(client)
        resp = client.get("/profile")
        assert resp.status_code == 200
        assert b"testuser" in resp.data

    def test_update_username(self, client, db):
        create_user()
        login(client)
        resp = client.post("/profile", data={"username": "newname"}, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Profile updated" in resp.data
        user = User.query.filter_by(email="test@example.com").first()
        assert user.username == "newname"

    def test_duplicate_username_update(self, client, db):
        create_user()
        create_user(email="other@example.com", username="othername")
        login(client)
        resp = client.post("/profile", data={"username": "othername"})
        assert resp.status_code == 422
        assert b"already taken" in resp.data

    def test_change_password(self, client, db):
        create_user()
        login(client)
        resp = client.post("/profile/password", data={
            "current_password": "securepass123",
            "new_password": "newsecure456",
            "confirm_password": "newsecure456",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Password changed" in resp.data

    def test_wrong_current_password(self, client, db):
        create_user()
        login(client)
        resp = client.post("/profile/password", data={
            "current_password": "wrongpassword",
            "new_password": "newsecure456",
            "confirm_password": "newsecure456",
        })
        assert resp.status_code == 401

    def test_mismatched_new_passwords(self, client, db):
        create_user()
        login(client)
        resp = client.post("/profile/password", data={
            "current_password": "securepass123",
            "new_password": "newsecure456",
            "confirm_password": "different789",
        })
        assert resp.status_code == 422
        assert b"do not match" in resp.data


# ---- Forgot Password Tests ----

class TestForgotPassword:
    def test_page_renders(self, client):
        resp = client.get("/forgot-password")
        assert resp.status_code == 200
        assert b"Reset your password" in resp.data

    def test_submit_email(self, client, db):
        create_user()
        resp = client.post("/forgot-password", data={"email": "test@example.com"}, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Check your email" in resp.data

    def test_nonexistent_email_always_success(self, client, db):
        """Prevent email enumeration — always shows success."""
        resp = client.post("/forgot-password", data={"email": "nobody@example.com"}, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Check your email" in resp.data

    def test_invalid_email(self, client, db):
        resp = client.post("/forgot-password", data={"email": "invalid"})
        assert resp.status_code == 422


# ---- Auth Status API Tests ----

class TestAuthStatus:
    def test_unauthenticated(self, client):
        resp = client.get("/api/auth/status")
        data = resp.get_json()
        assert data["authenticated"] is False
        assert data["user"] is None

    def test_authenticated(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/auth/status")
        data = resp.get_json()
        assert data["authenticated"] is True
        assert data["user"]["email"] == "test@example.com"


# ---- Security Tests ----

class TestSecurity:
    def test_password_never_in_api_response(self, client, db):
        create_user()
        login(client)
        resp = client.get("/api/auth/status")
        data = resp.get_json()
        assert "password" not in str(data)
        assert "password_hash" not in str(data)

    def test_password_never_in_signup_response(self, client, db):
        resp = signup(client)
        assert "password" not in resp.data.decode()
        assert "password_hash" not in resp.data.decode()

    def test_user_cannot_access_other_profile(self, client, db):
        """Ownership check: profile shows only own data."""
        user1 = create_user(email="user1@example.com", username="user1", password="pass12345")
        user2 = create_user(email="user2@example.com", username="user2", password="pass12345")
        login(client, email="user1@example.com", password="pass12345")
        resp = client.get("/profile")
        assert b"user1" in resp.data
        assert b"user2@example.com" not in resp.data

    def test_password_hash_is_hashed(self, db):
        """Verify password is never stored as plaintext."""
        user = create_user()
        assert user.password_hash != "securepass123"
        assert "scrypt" in user.password_hash or "pbkdf2" in user.password_hash

    def test_login_sets_session(self, client, db):
        create_user()
        login(client)
        # Verify session works by checking authenticated status
        resp = client.get("/api/auth/status")
        data = resp.get_json()
        assert data["authenticated"] is True

    def test_session_persists(self, client, db):
        create_user()
        login(client)
        # Make another request — should still be authenticated
        resp = client.get("/api/auth/status")
        data = resp.get_json()
        assert data["authenticated"] is True

    def test_404_handler_safe(self, client):
        """404 should not leak information."""
        resp = client.get("/nonexistent-page-xyz")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data
        assert "traceback" not in str(data).lower()
        assert "filesystem" not in str(data).lower()
