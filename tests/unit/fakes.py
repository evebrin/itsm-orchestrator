"""A fake requests session: routes (method, path) to canned answers and records every call."""
import json as _json
from urllib.parse import urlparse


class FakeResp:
    def __init__(self, status=200, result=None, html=False):
        self.status_code = status
        self.headers = {"Content-Type": "text/html" if html else "application/json"}
        body = "<html>hibernating</html>" if html else _json.dumps({"result": result} if result is not None else {})
        self.text, self.content = body, body.encode()

    def json(self):
        return _json.loads(self.text)


class FakeSession:
    def __init__(self, routes=None):
        self.routes = routes or {}  # (METHOD, path-prefix) -> callable(params, json) -> FakeResp or FakeResp
        self.calls = []
        self.headers = {}
        self.auth = None

    def request(self, method, url, params=None, json=None, timeout=None):
        path = urlparse(url).path
        self.calls.append((method, path, params, json, self.auth[0] if self.auth else None))
        for (m, prefix), answer in sorted(self.routes.items(), key=lambda kv: -len(kv[0][1])):
            if m == method and path.startswith(prefix):
                return answer(params, json) if callable(answer) else answer
        return FakeResp(200, [] if method == "GET" else {"sys_id": f"id{len(self.calls)}"})
