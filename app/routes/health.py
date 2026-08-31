from flask import jsonify

from app.routes import api_bp


@api_bp.route("/health", methods=["GET"])
def health_check():
    """Application health endpoint.

    Reports basic application health without exposing secrets.
    Can be extended to check database connectivity.
    """
    from app.extensions import db

    health = {
        "status": "healthy",
        "checks": {
            "app": "ok",
            "database": "unknown",
        },
    }

    # Check database connectivity
    try:
        db.session.execute(db.text("SELECT 1"))
        health["checks"]["database"] = "ok"
    except Exception:
        health["checks"]["database"] = "error"
        health["status"] = "degraded"

    status_code = 200 if health["status"] == "healthy" else 503
    return jsonify(health), status_code
