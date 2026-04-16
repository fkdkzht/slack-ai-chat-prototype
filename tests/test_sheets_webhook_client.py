import json

import httpx

from app.exports.sheets_webhook import post_to_sheets_webhook


class DummyTransport(httpx.BaseTransport):
    def __init__(self):
        self.requests = []

    def handle_request(self, request):  # type: ignore[override]
        self.requests.append(request)
        return httpx.Response(200, text="ok")


def test_post_to_sheets_webhook_posts_json() -> None:
    t = DummyTransport()
    client = httpx.Client(transport=t)
    post_to_sheets_webhook(
        client=client,
        webhook_url="https://example.com/webhook",
        payload={"hello": "world"},
    )
    assert len(t.requests) == 1
    req = t.requests[0]
    assert req.method == "POST"
    assert req.url.host == "example.com"
    body = json.loads(req.content.decode("utf-8"))
    assert body["hello"] == "world"


def test_post_to_sheets_webhook_disables_redirect_following() -> None:
    captured: dict[str, object] = {}

    class DummyClient:
        def post(self, url, json=None, timeout=None, follow_redirects=None):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            captured["follow_redirects"] = follow_redirects
            req = httpx.Request("POST", url, json=json)
            return httpx.Response(200, text="ok", request=req)

    post_to_sheets_webhook(
        client=DummyClient(),  # type: ignore[arg-type]
        webhook_url="https://example.com/webhook",
        payload={"hello": "world"},
    )
    assert captured["follow_redirects"] is False


def test_post_to_sheets_webhook_follows_apps_script_302_with_get() -> None:
    calls: list[tuple[str, str]] = []

    class DummyClient:
        def post(self, url, json=None, timeout=None, follow_redirects=None):
            calls.append(("POST", str(url)))
            req = httpx.Request("POST", url, json=json)
            return httpx.Response(
                302,
                headers={"location": "https://script.googleusercontent.com/macros/echo?x=1"},
                request=req,
            )

        def get(self, url, timeout=None, follow_redirects=None):
            calls.append(("GET", str(url)))
            req = httpx.Request("GET", url)
            return httpx.Response(200, text="ok", request=req)

    post_to_sheets_webhook(
        client=DummyClient(),  # type: ignore[arg-type]
        webhook_url="https://script.google.com/macros/s/TEST/exec",
        payload={"hello": "world"},
    )
    assert calls[0][0] == "POST"
    assert calls[1][0] == "GET"
    assert calls[1][1].startswith("https://script.googleusercontent.com/macros/echo")

