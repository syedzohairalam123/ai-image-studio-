"""Tests for the Pollinations.ai real-AI-generation provider and the
default-provider-resolution fix in generation_service.py.

Network calls to image.pollinations.ai are mocked throughout — this sandbox
has no outbound internet access to that domain, and tests shouldn't depend
on a third-party service being up anyway. What we're verifying is our own
code: request construction, response handling, and — critically — the
graceful per-image fallback to the local procedural engine when the network
call fails for any reason.
"""

from unittest.mock import patch, MagicMock

import pytest

from app.services.ai_provider import get_provider, list_providers
from app.services.providers.pollinations_provider import PollinationsProvider


def _fake_response(content=b"\xff\xd8\xff" + b"0" * 2000, content_type="image/jpeg", status_ok=True):
    resp = MagicMock()
    resp.content = content
    resp.headers = {"content-type": content_type}
    if status_ok:
        resp.raise_for_status = MagicMock()
    else:
        resp.raise_for_status = MagicMock(side_effect=Exception("HTTP error"))
    return resp


class TestPollinationsProviderSuccess:
    def test_registered_in_provider_list(self):
        assert "pollinations" in list_providers()

    def test_successful_generation_returns_real_bytes(self):
        provider = get_provider("pollinations")
        with patch("requests.get", return_value=_fake_response()) as mock_get:
            result = provider.text_to_image("a fluffy orange cat", width=512, height=512)

        assert result.success is True
        assert len(result.images) == 1
        assert result.images[0].file_bytes.startswith(b"\xff\xd8\xff")
        assert result.images[0].metadata["engine"] == "pollinations"
        mock_get.assert_called_once()

    def test_request_includes_prompt_and_params(self):
        provider = get_provider("pollinations")
        with patch("requests.get", return_value=_fake_response()) as mock_get:
            provider.text_to_image("a cat", width=768, height=512, style="anime", seed=42)

        called_url = mock_get.call_args[0][0]
        called_params = mock_get.call_args[1]["params"]
        assert "a%20cat" in called_url or "a+cat" in called_url or "cat" in called_url
        assert called_params["width"] == 768
        assert called_params["height"] == 512
        assert called_params["model"] == "flux-anime"  # anime style maps to flux-anime
        assert called_params["seed"] == 42
        assert called_params["nologo"] == "true"

    def test_style_maps_to_expected_model(self):
        provider = get_provider("pollinations")
        cases = {
            "photo": "flux-realism",
            "3d": "flux-3d",
            "pixel": "turbo",
            "auto": "flux",
        }
        for style, expected_model in cases.items():
            with patch("requests.get", return_value=_fake_response()) as mock_get:
                provider.text_to_image("a scene", style=style)
            assert mock_get.call_args[1]["params"]["model"] == expected_model

    def test_batch_produces_distinct_seeds(self):
        provider = get_provider("pollinations")
        with patch("requests.get", return_value=_fake_response()) as mock_get:
            result = provider.text_to_image("a dog", count=3, seed=100)
        seeds = [img.seed for img in result.images]
        assert seeds == [100, 101, 102]
        assert mock_get.call_count == 3

    def test_negative_prompt_passed_through(self):
        provider = get_provider("pollinations")
        with patch("requests.get", return_value=_fake_response()) as mock_get:
            provider.text_to_image("a castle", negative_prompt="blurry, low quality")
        assert mock_get.call_args[1]["params"]["negative"] == "blurry, low quality"


class TestPollinationsProviderFallback:
    """The whole point of the fallback: a broken/offline network should
    never make generation fail outright."""

    def test_network_exception_falls_back_to_procedural(self):
        provider = get_provider("pollinations")
        with patch("requests.get", side_effect=ConnectionError("network unreachable")):
            result = provider.text_to_image("a mountain lake", width=256, height=256)

        assert result.success is True
        assert len(result.images) == 1
        assert result.images[0].file_bytes is not None
        assert len(result.images[0].file_bytes) > 100
        assert result.images[0].metadata["engine"] == "procedural_fallback"

    def test_non_image_response_falls_back(self):
        """e.g. the service returns an HTML rate-limit page instead of an image."""
        provider = get_provider("pollinations")
        bad_response = _fake_response(content=b"<html>rate limited</html>", content_type="text/html")
        with patch("requests.get", return_value=bad_response):
            result = provider.text_to_image("a robot")
        assert result.success is True
        assert result.images[0].metadata["engine"] == "procedural_fallback"

    def test_http_error_falls_back(self):
        provider = get_provider("pollinations")
        with patch("requests.get", return_value=_fake_response(status_ok=False)):
            result = provider.text_to_image("a forest")
        assert result.success is True
        assert result.images[0].metadata["engine"] == "procedural_fallback"

    def test_mixed_batch_reports_any_real_generation_correctly(self):
        """First call succeeds, second fails -- provider_metadata should
        reflect that at least one real image was produced."""
        provider = get_provider("pollinations")
        responses = [_fake_response(), ConnectionError("timeout")]

        def side_effect(*args, **kwargs):
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with patch("requests.get", side_effect=side_effect):
            result = provider.text_to_image("a bird", count=2, seed=5)

        assert result.provider_metadata["any_real_generation"] is True
        engines = [img.metadata["engine"] for img in result.images]
        assert "pollinations" in engines
        assert "procedural_fallback" in engines


class TestDefaultProviderResolution:
    """generation_service.validate_generation_params used to hardcode
    provider="stub" regardless of the app's AI_PROVIDER config -- this
    verifies the fix."""

    def test_defaults_to_app_configured_provider(self, app):
        from app.services.generation_service import validate_generation_params
        original = app.config.get("AI_PROVIDER")
        try:
            with app.app_context():
                app.config["AI_PROVIDER"] = "pollinations"
                params = validate_generation_params({"prompt": "a sunset"})
            assert params["provider_name"] == "pollinations"
        finally:
            app.config["AI_PROVIDER"] = original

    def test_explicit_request_provider_overrides_default(self, app):
        from app.services.generation_service import validate_generation_params
        original = app.config.get("AI_PROVIDER")
        try:
            with app.app_context():
                app.config["AI_PROVIDER"] = "pollinations"
                params = validate_generation_params({"prompt": "a sunset", "provider": "stub"})
            assert params["provider_name"] == "stub"
        finally:
            app.config["AI_PROVIDER"] = original

    def test_testing_config_still_defaults_to_stub(self, app):
        """Sanity check: the test app's own config (TestingConfig) should
        still resolve to stub, so the rest of the suite is unaffected."""
        from app.services.generation_service import validate_generation_params
        with app.app_context():
            params = validate_generation_params({"prompt": "a sunset"})
        assert params["provider_name"] == "stub"
