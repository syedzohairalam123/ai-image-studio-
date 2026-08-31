import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """Base configuration."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    # On Vercel (serverless), only /tmp is writable. Use DATABASE_URL env
    # var for a real database (Postgres, etc.) in production. Fall back to
    # /tmp/ai_studio.db for ephemeral SQLite on Vercel cold starts.
    _default_db = "sqlite:////tmp/ai_studio.db" if os.environ.get("VERCEL") else f"sqlite:///{BASE_DIR / 'ai_studio.db'}"
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", _default_db)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    AI_PROVIDER = os.environ.get("AI_PROVIDER", "stub")
    AI_API_KEY = os.environ.get("AI_API_KEY", "")

    # Rembg settings
    REMBG_MODEL = os.environ.get("REMBG_MODEL", "u2net")
    REMBG_ALPHA_MATTING = os.environ.get("REMBG_ALPHA_MATTING", "false").lower() == "true"

    # Pillow upscale settings
    PILLOW_UPSCALE_SHARPEN = os.environ.get("PILLOW_UPSCALE_SHARPEN", "true").lower() == "true"
    PILLOW_UPSCALE_SHARPEN_FACTOR = float(os.environ.get("PILLOW_UPSCALE_SHARPEN_FACTOR", "1.2"))
    PILLOW_UPSCALE_MULTI_PASS = os.environ.get("PILLOW_UPSCALE_MULTI_PASS", "true").lower() == "true"

    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 10 * 1024 * 1024))  # 10MB
    # On Vercel only /tmp is writable
    _default_upload = "/tmp/uploads" if os.environ.get("VERCEL") else str(BASE_DIR / os.environ.get("UPLOAD_FOLDER", "uploads"))
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER_OVERRIDE", _default_upload)

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    # Session security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = 30  # days


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG")


class TestingConfig(Config):
    """Testing configuration."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    AI_PROVIDER = "stub"


class ProductionConfig(Config):
    """Production configuration."""

    DEBUG = False
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "WARNING")
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True


config_map = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config():
    env = os.environ.get("FLASK_ENV", "development")
    return config_map.get(env, DevelopmentConfig)
