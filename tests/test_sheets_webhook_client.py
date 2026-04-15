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

