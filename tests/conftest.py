import pytest

from app import create_app
from app.config import TestingConfig
from app.extensions import db as _db


@pytest.fixture(scope="session")
def app():
    """Create application for testing."""
    app = create_app(TestingConfig)
    with app.app_context():
        yield app


@pytest.fixture(scope="function")
def db(app):
    """Create a fresh database for each test."""
    with app.app_context():
        import app.models  # noqa: F401 — ensure all models are registered
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create a test CLI runner."""
    return app.test_cli_runner()
