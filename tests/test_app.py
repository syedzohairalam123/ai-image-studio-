import json


def test_health_endpoint(client):
    """Test health check endpoint."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "healthy"
    assert data["checks"]["app"] == "ok"


def test_api_status(client):
    """Test API status endpoint."""
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "running"
    assert "providers" in data
    assert "stub" in data["providers"]


def test_404(client):
    """Test 404 error handler."""
    response = client.get("/nonexistent")
    assert response.status_code == 404
    data = response.get_json()
    assert "error" in data


def test_homepage(client):
    """Test that the root URL returns a response."""
    response = client.get("/")
    # Should return 404 since no root route defined, not a 500
    assert response.status_code in (200, 404)
