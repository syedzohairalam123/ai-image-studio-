from flask import jsonify, request
from marshmallow import ValidationError


class APIError(Exception):
    """Base API error with status code."""

    def __init__(self, message, status_code=400, payload=None):
        super().__init__()
        self.message = message
        self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = {"error": self.message, "status_code": self.status_code}
        if self.payload:
            rv["details"] = self.payload
        return rv


class NotFoundError(APIError):
    def __init__(self, message="Resource not found"):
        super().__init__(message, status_code=404)


class UnauthorizedError(APIError):
    def __init__(self, message="Authentication required"):
        super().__init__(message, status_code=401)


class ForbiddenError(APIError):
    def __init__(self, message="Access denied"):
        super().__init__(message, status_code=403)


class ConflictError(APIError):
    def __init__(self, message="Resource already exists"):
        super().__init__(message, status_code=409)


class RateLimitError(APIError):
    def __init__(self, message="Rate limit exceeded"):
        super().__init__(message, status_code=429)


def register_error_handlers(the_app):
    """Register centralized error handlers."""
    # Use register_error_handler to avoid module name collision
    # when the app package is also named 'app'

    def _handle_api_error(error):
        response = jsonify(error.to_dict())
        response.status_code = error.status_code
        return response

    def _handle_validation_error(error):
        return jsonify({
            "error": "Validation failed",
            "status_code": 422,
            "details": error.messages,
        }), 422

    def _bad_request(e):
        return jsonify({"error": "Bad request", "status_code": 400}), 400

    def _unauthorized(e):
        return jsonify({"error": "Authentication required", "status_code": 401}), 401

    def _forbidden(e):
        return jsonify({"error": "Access denied", "status_code": 403}), 403

    def _not_found(e):
        return jsonify({"error": "Resource not found", "status_code": 404}), 404

    def _method_not_allowed(e):
        return jsonify({"error": "Method not allowed", "status_code": 405}), 405

    def _conflict(e):
        return jsonify({"error": "Resource already exists", "status_code": 409}), 409

    def _request_entity_too_large(e):
        return jsonify({"error": "File too large", "status_code": 413}), 413

    def _unprocessable_entity(e):
        return jsonify({"error": "Unprocessable entity", "status_code": 422}), 422

    def _rate_limited(e):
        return jsonify({"error": "Rate limit exceeded", "status_code": 429}), 429

    def _internal_error(e):
        the_app.logger.exception("Internal error: %s", e)
        # SECURITY: Never expose stack traces or internal details to clients
        return jsonify({"error": "Internal server error", "status_code": 500}), 500

    the_app.register_error_handler(APIError, _handle_api_error)
    the_app.register_error_handler(ValidationError, _handle_validation_error)
    the_app.register_error_handler(400, _bad_request)
    the_app.register_error_handler(401, _unauthorized)
    the_app.register_error_handler(403, _forbidden)
    the_app.register_error_handler(404, _not_found)
    the_app.register_error_handler(405, _method_not_allowed)
    the_app.register_error_handler(409, _conflict)
    the_app.register_error_handler(413, _request_entity_too_large)
    the_app.register_error_handler(422, _unprocessable_entity)
    the_app.register_error_handler(429, _rate_limited)
    the_app.register_error_handler(500, _internal_error)
