from flask import Blueprint

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")
main_bp = Blueprint("main", __name__)


def register_routes(flask_app):
    """Register all blueprints with the app."""
    import app.routes.health  # noqa: F401 — registers health_check on api_bp
    from app.routes import api, views, auth, prompts, creative, editor, gallery, utilities  # noqa: F401
    from app.routes import sharing, explore, moderation  # noqa: F401 — Phase 12: sharing, explore, moderation
    from app.routes import settings  # noqa: F401 — Phase 13: settings & personalization
    from app.routes import admin  # noqa: F401 — Phase 14: admin & monitoring
    from app.routes import advanced_ai  # noqa: F401 — Advanced AI features

    flask_app.register_blueprint(main_bp)
    flask_app.register_blueprint(api_bp)
