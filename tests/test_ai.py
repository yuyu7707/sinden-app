"""女神の鏡（services/ai.py）の失敗時の動き。本物の Claude API は呼ばない"""

from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from sinden.services import ai
from sinden.services.ai import AIError

REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls, code):
    return cls("error", response=httpx.Response(code, request=REQUEST), body=None)


class FakeClient:
    """anthropic.Anthropic の代わり。作られたときの設定と、返す結果を持つ"""

    last_kwargs = None

    def __init__(self, result):
        self.result = result

    def __call__(self, **kwargs):
        FakeClient.last_kwargs = kwargs
        outer = self

        class Messages:
            def create(self, **_):
                if isinstance(outer.result, Exception):
                    raise outer.result
                return outer.result

        self.beta = SimpleNamespace(messages=Messages())
        return self


@pytest.fixture
def with_key(app):
    app.config["ANTHROPIC_API_KEY"] = "sk-test"
    return app


def use(monkeypatch, result):
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient(result))


def text_response(text, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)]
    )


def test_no_key(app):
    app.config["ANTHROPIC_API_KEY"] = ""
    with pytest.raises(AIError, match="API キーが未設定"):
        ai.reflect("聞いてほしい")


def test_success_and_timeout_setting(with_key, monkeypatch):
    use(
        monkeypatch,
        text_response('{"mirror": "あなたは…", "danger": false, "lamp": "わたしは…"}'),
    )
    result = ai.reflect("聞いてほしい")
    assert (result.mirror, result.danger, result.lamp) == (
        "あなたは…",
        False,
        "わたしは…",
    )
    assert FakeClient.last_kwargs["timeout"] == 30
    assert FakeClient.last_kwargs["max_retries"] == 1


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (anthropic.APITimeoutError(request=REQUEST), "時間内に映りませんでした"),
        (anthropic.APIConnectionError(request=REQUEST), "接続できませんでした"),
        (status_error(anthropic.AuthenticationError, 401), "いまは使えません"),
        (status_error(anthropic.RateLimitError, 429), "混み合っています"),
        # 残高切れは 400 として返ってくる
        (status_error(anthropic.BadRequestError, 400), "映せませんでした"),
    ],
)
def test_errors_become_short_messages(with_key, monkeypatch, error, message):
    use(monkeypatch, error)
    with pytest.raises(AIError, match=message):
        ai.reflect("聞いてほしい")


def test_refusal(with_key, monkeypatch):
    use(monkeypatch, text_response("", stop_reason="refusal"))
    with pytest.raises(AIError, match="映せませんでした"):
        ai.reflect("聞いてほしい")


def test_broken_json(with_key, monkeypatch):
    use(monkeypatch, text_response("not json"))
    with pytest.raises(AIError, match="映せませんでした"):
        ai.reflect("聞いてほしい")


def test_lamp_is_dropped_when_danger(with_key, monkeypatch):
    # 危険の気配があるときは、AI が灯を返しても使わない
    use(
        monkeypatch,
        text_response('{"mirror": "あなたは…", "danger": true, "lamp": "やわらかく"}'),
    )
    result = ai.reflect("聞いてほしい")
    assert result.danger is True
    assert result.lamp == ""
