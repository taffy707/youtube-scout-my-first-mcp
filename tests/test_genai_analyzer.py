from types import SimpleNamespace

import pytest
from google.genai import errors, types

from yt_scout.gemini import DETAIL_LEVELS, GeminiUnavailable, GenaiAnalyzer


class FakeModels:
    def __init__(self, text="{}", exc=None):
        self.text, self.exc, self.kwargs = text, exc, None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return SimpleNamespace(text=self.text)


def analyzer(models):
    return GenaiAnalyzer(None, "gemini-3.8-flash", client=SimpleNamespace(models=models))


def test_analyze_clip_builds_youtube_request():
    models = FakeModels(text='{"notes": []}')
    out = analyzer(models).analyze_clip("https://www.youtube.com/watch?v=vid00000001", 180, 360,
                                        DETAIL_LEVELS["high"], "PROMPT")
    assert out == '{"notes": []}'
    kw = models.kwargs
    assert kw["model"] == "gemini-3.8-flash"
    video, prompt = kw["contents"].parts
    assert video.file_data.file_uri == "https://www.youtube.com/watch?v=vid00000001"
    assert video.video_metadata.start_offset == "180s"
    assert video.video_metadata.end_offset == "360s"
    assert video.video_metadata.fps == 2.0
    assert prompt.text == "PROMPT"
    assert kw["config"].media_resolution == types.MediaResolution.MEDIA_RESOLUTION_HIGH
    assert kw["config"].response_mime_type == "application/json"


def test_complete_text_is_text_only():
    models = FakeModels(text="summary")
    assert analyzer(models).complete_text("merge these") == "summary"
    (part,) = models.kwargs["contents"].parts
    assert part.text == "merge these"


def test_empty_response_text_becomes_empty_string():
    models = FakeModels(text=None)
    assert analyzer(models).complete_text("x") == ""


def test_client_error_is_not_retryable():
    exc = errors.ClientError(403, {"error": {"code": 403, "message": "Video unavailable", "status": "PERMISSION_DENIED"}})
    with pytest.raises(GeminiUnavailable) as raised:
        analyzer(FakeModels(exc=exc)).analyze_clip("u", 0, 60, DETAIL_LEVELS["normal"], "p")
    assert raised.value.code == "gemini_rejected"
    assert "Video unavailable" in raised.value.message


@pytest.mark.parametrize("exc", [
    errors.ClientError(429, {"error": {"code": 429, "message": "slow down", "status": "RESOURCE_EXHAUSTED"}}),
    errors.ServerError(503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}}),
])
def test_rate_limit_and_server_errors_propagate_for_retry(exc):
    with pytest.raises(type(exc)):
        analyzer(FakeModels(exc=exc)).analyze_clip("u", 0, 60, DETAIL_LEVELS["normal"], "p")
