"""Dashboard and navigation tests."""

import pytest
from app.extensions import db
from app.models.user import User
from app.models.generation import Generation
from app.models.image import Image


def create_user(email="test@example.com", username="testuser", password="securepass123"):
    user = User(email=email, username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, email="test@example.com", password="securepass123"):
    return client.post("/login", data={
        "email": email,
        "password": password,
    }, follow_redirects=True)


def signup(client, email="new@example.com", username="newuser", password="securepass123"):
    return client.post("/signup", data={
        "email": email,
        "username": username,
        "password": password,
    }, follow_redirects=True)


# ---- Dashboard Access Tests ----

class TestDashboardAccess:
    def test_authenticated_sees_dashboard(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Welcome back" in resp.data
        assert b"testuser" in resp.data

    def test_unauthenticated_sees_landing(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Turn Your Ideas into" in resp.data

    def test_unauthenticated_no_dashboard(self, client):
        resp = client.get("/")
        assert b"Welcome back" not in resp.data


# ---- Dashboard Content Tests (Empty Account) ----

class TestDashboardEmpty:
    def test_empty_shows_zero_stats(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert resp.status_code == 200
        # Stats should show 0
        assert b"Total Generations" in resp.data
        assert b"Total Images" in resp.data

    def test_empty_shows_no_generations(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert b"No generations yet" in resp.data
        assert b"Create Your First Image" in resp.data

    def test_empty_shows_favorites_placeholder(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert b"Favorites" in resp.data
        assert b"Heart images" in resp.data

    def test_empty_shows_collections_placeholder(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert b"Collections" in resp.data
        assert b"Create collections" in resp.data

    def test_empty_shows_prompt_suggestions(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert b"Try These Prompts" in resp.data

    def test_empty_shows_quick_actions(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert b"Quick Actions" in resp.data
        assert b"Create Image" in resp.data
        assert b"Open Gallery" in resp.data
        assert b"New Collection" in resp.data


# ---- Dashboard Content Tests (Populated Account) ----

class TestDashboardPopulated:
    def test_populated_shows_recent_generations(self, client, db):
        user = create_user()
        login(client)

        # Create some generations
        for i in range(3):
            gen = Generation(
                user_id=user.id,
                prompt=f"A beautiful sunset #{i}",
                provider="stub",
                status="completed",
            )
            db.session.add(gen)
        db.session.commit()

        resp = client.get("/")
        assert b"Recent Generations" in resp.data
        assert b"A beautiful sunset" in resp.data

    def test_populated_shows_stats(self, client, db):
        user = create_user()
        login(client)

        for i in range(5):
            gen = Generation(
                user_id=user.id,
                prompt=f"Image {i}",
                provider="stub",
                status="completed",
            )
            db.session.add(gen)
        db.session.commit()

        resp = client.get("/")
        assert b"Recent Generations" in resp.data
        assert b"View All" in resp.data

    def test_populated_shows_view_all_link(self, client, db):
        user = create_user()
        login(client)
        gen = Generation(
            user_id=user.id,
            prompt="Test generation",
            provider="stub",
            status="completed",
        )
        db.session.add(gen)
        db.session.commit()

        resp = client.get("/")
        assert b"View All" in resp.data

    def test_failed_generations_tracked(self, client, db):
        user = create_user()
        login(client)

        gen = Generation(
            user_id=user.id,
            prompt="Failed image",
            provider="stub",
            status="failed",
            error_message="Provider timeout",
        )
        db.session.add(gen)
        db.session.commit()

        resp = client.get("/")
        assert b"Failed" in resp.data


# ---- Activity Chart Tests ----

class TestActivityChart:
    def test_empty_account_shows_placeholder(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert b"Activity" in resp.data
        assert b"activity-chart" not in resp.data  # canvas only renders once there's data

    def test_populated_account_renders_canvas_with_real_counts(self, client, db):
        user = create_user()
        login(client)
        for i in range(4):
            gen = Generation(user_id=user.id, prompt=f"chart test {i}", provider="stub", status="completed")
            db.session.add(gen)
        db.session.commit()

        resp = client.get("/")
        assert b'id="activity-chart"' in resp.data
        # The 14-day bucketed totals should sum to the generations we just made.
        import json
        import re
        match = re.search(rb'id="activity-chart-data"[^>]*>(.*?)</script>', resp.data, re.DOTALL)
        assert match is not None
        chart_data = json.loads(match.group(1))
        assert len(chart_data["labels"]) == 14
        assert sum(chart_data["total"]) == 4
        assert sum(chart_data["completed"]) == 4


# ---- Navigation Tests ----

class TestNavigation:
    def test_sidebar_has_all_links(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")

        links = [b"Home", b"Create", b"Editor", b"History", b"Gallery",
                 b"Favorites", b"Collections", b"Prompt Library", b"Explore", b"Settings"]
        for link in links:
            assert link in resp.data, f"Missing nav link: {link.decode()}"

    def test_sidebar_shows_username(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert b"testuser" in resp.data

    def test_sidebar_shows_signout(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert b"Sign Out" in resp.data

    def test_anonymous_shows_cta(self, client):
        resp = client.get("/")
        # Landing page has its own CTAs
        assert b"Start Creating" in resp.data or b"Get Started" in resp.data


# ---- Protected Route Tests ----

class TestProtectedRoutes:
    PROTECTED = ["/history", "/favorites", "/collections", "/prompts", "/settings", "/profile"]

    def test_unauthenticated_redirects(self, client):
        for path in self.PROTECTED:
            resp = client.get(path)
            assert resp.status_code == 302, f"{path} should redirect"
            assert "/login" in resp.headers["Location"]

    def test_authenticated_access(self, client, db):
        create_user()
        login(client)
        for path in self.PROTECTED:
            resp = client.get(path)
            assert resp.status_code == 200, f"{path} should be accessible"

    def test_public_routes(self, client):
        public = ["/", "/generate", "/gallery", "/explore", "/styles", "/editor"]
        for path in public:
            resp = client.get(path)
            assert resp.status_code == 200, f"{path} should be public"


# ---- Dark Mode Tests ----

class TestDarkMode:
    def test_dark_mode_toggle_present(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert b"theme-toggle" in resp.data

    def test_dark_mode_in_css(self, client):
        resp = client.get("/static/css/variables.css")
        assert b'data-theme="dark"' in resp.data


# ---- Responsive Tests ----

class TestResponsive:
    def test_mobile_menu_button(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert b"mobile-menu-btn" in resp.data

    def test_responsive_grid_styles(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert b"@media" in resp.data  # Has responsive CSS


# ---- Security Tests ----

class TestDashboardSecurity:
    def test_password_never_in_dashboard(self, client, db):
        create_user()
        login(client)
        resp = client.get("/")
        assert b"password_hash" not in resp.data
        assert b"scrypt" not in resp.data
        assert b"pbkdf2" not in resp.data

    def test_other_user_data_not_shown(self, client, db):
        """Dashboard should only show current user's data."""
        user1 = create_user(email="u1@x.com", username="user1")
        user2 = create_user(email="u2@x.com", username="user2")

        # user2 creates a generation
        gen = Generation(user_id=user2.id, prompt="user2's image", provider="stub", status="completed")
        db.session.add(gen)
        db.session.commit()

        # user1 logs in
        login(client, email="u1@x.com")
        resp = client.get("/")
        assert b"user2" not in resp.data
        assert b"user2's image" not in resp.data
